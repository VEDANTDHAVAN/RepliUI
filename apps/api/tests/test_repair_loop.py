"""Repair loop tests: retry limit, state transitions, and cost controls.

The validator and the AI gateway are both faked. Nothing here shells out and
nothing here needs an API key; the point is the loop's control flow.
"""

from __future__ import annotations

import json

import pytest

from app.ai.gateway import AIGatewayCompletion
from app.models.schemas import AgentState, ProjectManifest, ValidationResult
from app.repair.agent import RepairAgent
from app.repair.loop import RepairLoop
from app.repair.patch import RepairChange

BUILD_FAILURE = """> next build
./app/page.tsx:3:5
Type error: Property 'nope' does not exist on type 'Props'.
"""


class FakeValidator:
    """Returns a queued sequence of validation results, then repeats the last."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def validate(self, project_id: str) -> ValidationResult:
        self.calls += 1
        if len(self._results) > 1:
            return self._results.pop(0)
        return self._results[0]


def _failure(stage: str = "build") -> ValidationResult:
    return ValidationResult(
        success=False,
        stage=stage,
        stdout=BUILD_FAILURE if stage == "build" else "",
        stderr="ERR_PNPM_OUTDATED_LOCKFILE" if stage == "install" else "",
        package_manager="pnpm",
    )


def _success() -> ValidationResult:
    return ValidationResult(success=True, stage="build", stdout="Compiled successfully", package_manager="pnpm")


class FakeGateway:
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls: list[dict] = []

    def complete_detailed(self, *, system: str, user: str, operation: str):
        self.calls.append({"user": user})
        reply = self._replies.pop(0) if self._replies else json.dumps({"summary": "nothing", "changes": []})
        if isinstance(reply, Exception):
            raise reply
        return AIGatewayCompletion(content=reply, model="test/model", latency_ms=1, total_tokens=7)


def _reply(changes, summary="fixed") -> str:
    return json.dumps({"summary": summary, "changes": changes})


def _chain(count: int) -> list[str]:
    """``count`` replies, each editing a distinct anchor.

    A patch whose original text is no longer present is correctly refused, so
    a loop that keeps retrying needs a fresh anchor per attempt.
    """
    replies = []
    previous = "<h1>nope</h1>"
    for i in range(count):
        replacement = f"<h1>broken{i}</h1>" if i + 1 < count else f"<h1>final{i}</h1>"
        replies.append(_reply([{"file": "app/page.tsx", "original": previous, "replacement": replacement, "reason": "still wrong"}]))
        previous = replacement
    return replies


def _fix_change(replacement="<p>fixed</p>") -> str:
    """A single valid edit. The anchor must exist verbatim in app/page.tsx."""
    return _reply(
        [
            {
                "file": "app/page.tsx",
                "original": "<h1>nope</h1>",
                "replacement": replacement,
                "reason": "unknown prop",
            }
        ]
    )


def _followup_change(replacement="<h1>fixed</h1>") -> str:
    """A second edit whose anchor only exists after the first one applied."""
    return _reply(
        [
            {
                "file": "app/page.tsx",
                "original": "<h1>still-broken</h1>",
                "replacement": replacement,
                "reason": "prop type still wrong",
            }
        ]
    )


@pytest.fixture()
def project() -> str:
    from app import storage

    project_id = "loopproject12"
    root = storage.PROJECTS_DIR / project_id
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "page.tsx").write_text(
        "export default function Page() {\n  return <h1>nope</h1>;\n}\n", encoding="utf-8"
    )
    (root / "package.json").write_text('{"name": "site"}', encoding="utf-8")
    storage.save_manifest(ProjectManifest(project_id=project_id, url="https://example.com"))
    return project_id


def _run(project, validator, gateway, max_attempts=3):
    manifest = ProjectManifest(project_id=project, url="https://example.com")
    agent = RepairAgent(gateway)
    loop = RepairLoop(agent=agent, validator=validator, max_attempts=max_attempts)
    return loop.run(project, manifest, validator.validate(project))


# --- Scenario 1: build already succeeds ---------------------------------


def test_successful_build_makes_no_repair_call(project):
    validator = FakeValidator([_success()])
    gateway = FakeGateway([_fix_change()])
    manifest, attempts, calls = _run(project, validator, gateway)

    assert manifest.state == AgentState.READY
    assert attempts == 0
    assert calls == 0
    assert gateway.calls == [], "no AI call on a successful build"


# --- Scenario 2: one repair fixes it ------------------------------------


def test_first_repair_succeeds(project):
    validator = FakeValidator([_failure(), _success()])
    gateway = FakeGateway([_fix_change()])
    manifest, attempts, calls = _run(project, validator, gateway)

    assert manifest.state == AgentState.READY
    assert attempts == 1
    assert calls == 1
    assert validator.calls == 2, "rebuild must rerun the full lifecycle"


def test_repair_change_is_applied_to_disk(project):
    from app import storage

    validator = FakeValidator([_failure(), _success()])
    _run(project, validator, FakeGateway([_fix_change()]))
    assert "<p>fixed</p>" in (storage.PROJECTS_DIR / project / "app" / "page.tsx").read_text(encoding="utf-8")


# --- Scenario 3: second repair succeeds ---------------------------------


def test_second_attempt_succeeds(project):
    validator = FakeValidator([_failure(), _failure(), _success()])
    # Attempt 1 changes the code but the build still fails; attempt 2 fixes it.
    # Each edit needs a distinct anchor, since a patch whose original is
    # already gone is correctly refused.
    gateway = FakeGateway([_fix_change("<h1>still-broken</h1>"), _followup_change()])
    manifest, attempts, calls = _run(project, validator, gateway)

    assert manifest.state == AgentState.READY
    assert attempts == 2
    assert calls == 2
    assert len(gateway.calls) == 2


# --- Scenario 4: all three attempts fail --------------------------------


def test_fails_after_exactly_three_attempts(project):
    # Each attempt must apply a *distinct* edit, so a chain of increasingly
    # wrong but still-applicable fixes is what drives the loop to its limit.
    validator = FakeValidator([_failure()])
    gateway = FakeGateway(_chain(3))
    manifest, attempts, calls = _run(project, validator, gateway)

    assert manifest.state == AgentState.FAILED
    assert attempts == 3
    assert calls == 3
    assert len(gateway.calls) == 3, "must never exceed three repair calls"


def test_failure_records_progress_for_dashboard(project):
    validator = FakeValidator([_failure()])
    gateway = FakeGateway(_chain(3))
    manifest, _, _ = _run(project, validator, gateway)

    assert any("Repair attempt 1/3" in p for p in manifest.progress)
    assert any("Repair attempt 3/3" in p for p in manifest.progress)
    assert any("failed" in p.lower() for p in manifest.progress)


def test_manifest_is_persisted(project):
    validator = FakeValidator([_failure()])
    from app import storage

    gateway = FakeGateway(_chain(3))
    _run(project, validator, gateway)
    saved = storage.load_manifest(project)
    assert saved is not None
    assert saved.state == AgentState.FAILED


def test_validation_result_is_attached(project):
    validator = FakeValidator([_failure()])
    gateway = FakeGateway(_chain(3))
    manifest, _, _ = _run(project, validator, gateway)
    assert manifest.validation is not None
    assert manifest.validation.success is False


# --- retry limit is configurable and honoured ---------------------------


def test_custom_max_attempts(project):
    validator = FakeValidator([_failure()])
    gateway = FakeGateway([_fix_change()])
    manifest, attempts, calls = _run(project, validator, gateway, max_attempts=1)
    assert manifest.state == AgentState.FAILED
    assert attempts == 1
    assert calls == 1


def test_repair_call_budget_is_independent(project):
    validator = FakeValidator([_failure()])
    gateway = FakeGateway(_chain(5))
    loop = RepairLoop(
        agent=RepairAgent(gateway),
        validator=validator,
        max_attempts=5,
        max_repair_calls=2,
    )
    manifest = ProjectManifest(project_id=project, url="https://example.com")
    _, attempts, calls = loop.run(project, manifest, _failure())
    assert calls == 2
    assert attempts <= 5
    assert manifest.state == AgentState.FAILED


# --- Scenario 5: path traversal is rejected -----------------------------


def test_traversal_change_is_rejected_and_project_fails(project):
    from app import storage

    validator = FakeValidator([_failure()])
    escape = storage.PROJECTS_DIR.parent / "escape.tsx"
    reply = _reply([{"file": "../escape.tsx", "original": "a", "replacement": "b"}])
    manifest, _, calls = _run(project, validator, FakeGateway([reply] * 3))

    assert manifest.state == AgentState.FAILED
    assert not escape.exists()
    assert calls >= 1


def test_escape_file_is_never_created(project):
    from app import storage

    validator = FakeValidator([_failure()])
    reply = _reply([{"file": "../../escape.tsx", "original": "a", "replacement": "b"}])
    _run(project, validator, FakeGateway([reply] * 3))
    assert not (storage.PROJECTS_DIR.parent.parent / "escape.tsx").exists()


# --- Scenario 6: command execution is rejected --------------------------


def test_command_injection_change_is_rejected(project):
    from app import storage

    validator = FakeValidator([_failure()])
    reply = _reply(
        [
            {
                "file": "app/page.tsx",
                "original": "<h1>nope</h1>",
                "replacement": "import {execSync} from 'child_process'; execSync('rm -rf /');",
            }
        ]
    )
    manifest, _, _ = _run(project, validator, FakeGateway([reply] * 3))

    assert manifest.state == AgentState.FAILED
    page = storage.PROJECTS_DIR / project / "app" / "page.tsx"
    assert "child_process" not in page.read_text(encoding="utf-8")


def test_agent_is_never_given_a_shell(project):
    """The repair agent's only output is data; nothing in the loop runs a command."""
    gateway = FakeGateway([_fix_change()])
    _run(project, FakeValidator([_failure()]), gateway)
    prompt = gateway.calls[0]["user"]
    assert "child_process" not in prompt


# --- malformed AI responses --------------------------------------------


def test_malformed_response_does_not_crash_loop(project):
    # A malformed response yields no changes, so the loop stops after one
    # call rather than spending the remaining budget on identical garbage.
    validator = FakeValidator([_failure()])
    gateway = FakeGateway(["not json"] * 3)
    manifest, attempts, calls = _run(project, validator, gateway)
    assert manifest.state == AgentState.FAILED
    assert calls == 1


def test_malformed_response_leaves_files_untouched(project):
    from app import storage

    path = storage.PROJECTS_DIR / project / "app" / "page.tsx"
    before = path.read_text(encoding="utf-8")
    validator = FakeValidator([_failure()])
    _run(project, validator, FakeGateway(["{ broken"] * 3))
    assert path.read_text(encoding="utf-8") == before


def test_empty_plan_stops_immediately(project):
    validator = FakeValidator([_failure()])
    gateway = FakeGateway([_reply([], summary="I cannot fix this safely")])
    manifest, attempts, calls = _run(project, validator, gateway)
    # No changes means retrying would be pointless; the loop stops rather
    # than burning two more model calls on an unchanged build.
    assert manifest.state == AgentState.FAILED
    assert calls == 1


# --- install-stage failures --------------------------------------------


def test_install_failure_is_diagnosed_as_install(project):
    from app.repair.loop import RepairLoop as RL

    loop = RL(agent=RepairAgent(FakeGateway([_fix_change()])), validator=FakeValidator([_failure("install")]))
    diags = loop._diagnostics(_failure("install"), 1)
    assert diags[0].stage == "install"


def test_build_command_is_labelled_for_display(project):
    from app.repair.loop import _stage_command

    assert _stage_command(_failure("install")) == "npm install"
    assert _stage_command(_failure("build")) == "pnpm run build"
