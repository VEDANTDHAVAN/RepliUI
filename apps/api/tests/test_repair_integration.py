"""Integration tests for the repair loop, driven through the real API path.

These exercise the same `validate_project` the `/validate` background task
calls. The validator and the AI gateway are the only fakes: the patch
application, path validation, state machine, manifest persistence and
diagnostic parsing are the real implementations.

No real `next build` runs here (see `_manual_repair.py` for that), and no
AI Gateway API key is required.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.ai.gateway import AIGatewayCompletion
from app.main import app
from app.models.schemas import AgentState, ProjectManifest, ValidationResult
from app.repair.agent import RepairAgent
from app.repair.loop import RepairLoop

BUILD_FAILURE = (
    "Failed to compile.\n"
    "./app/page.tsx:1:10\n"
    "Type error: 'title' is possibly 'undefined'.\n"
)


class FakeValidator:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def validate(self, project_id: str) -> ValidationResult:
        self.calls += 1
        if len(self._results) > 1:
            return self._results.pop(0)
        return self._results[0]


def _fail() -> ValidationResult:
    return ValidationResult(
        success=False, stage="build", stdout=BUILD_FAILURE, package_manager="pnpm"
    )


def _ok() -> ValidationResult:
    return ValidationResult(success=True, stage="build", stdout="Compiled successfully", package_manager="pnpm")


class FakeGateway:
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls: list[dict] = []

    def complete_detailed(self, *, system: str, user: str, operation: str):
        self.calls.append({"user": user})
        reply = self._replies.pop(0) if self._replies else '{"summary":"none","changes":[]}'
        if isinstance(reply, Exception):
            raise reply
        return AIGatewayCompletion(content=reply, model="test/model", latency_ms=5, total_tokens=11)


def _change(replacement: str) -> str:
    return json.dumps(
        {
            "summary": "optional prop dereferenced",
            "changes": [
                {
                    "file": "app/page.tsx",
                    "original": "<h1>broken</h1>",
                    "replacement": replacement,
                    "reason": "title may be undefined",
                }
            ],
        }
    )


def _chain(count: int) -> list[str]:
    """`count` replies with distinct anchors, so each patch is applicable."""
    out, previous = [], "<h1>broken</h1>"
    for i in range(count):
        nxt = f"<h1>b{i}</h1>" if i + 1 < count else f"<h1>done{i}</h1>"
        out.append(
            json.dumps(
                {
                    "summary": "fix",
                    "changes": [
                        {
                            "file": "app/page.tsx",
                            "original": previous,
                            "replacement": nxt,
                            "reason": "still wrong",
                        }
                    ],
                }
            )
        )
        previous = nxt
    return out


@pytest.fixture()
def project() -> str:
    from app import storage

    project_id = "integration01"
    root = storage.PROJECTS_DIR / project_id
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "page.tsx").write_text(
        "export default function Page() {\n  return <h1>broken</h1>;\n}\n", encoding="utf-8"
    )
    (root / "components").mkdir(parents=True, exist_ok=True)
    (root / "components" / "Hero.tsx").write_text("export const Hero = 1;\n", encoding="utf-8")
    (root / "package.json").write_text('{"name":"site"}', encoding="utf-8")
    storage.save_manifest(ProjectManifest(project_id=project_id, url="https://example.com"))
    return project_id


def _wire(monkeypatch, validator, gateway):
    """Point main.py and the loop at the fakes.

    main.validate_project builds its own BuildValidator() for the initial
    build and constructs its own RepairLoop, so both names are patched
    here; otherwise a real `next build` would run in the test process.
    """
    import app.main as main_mod
    import app.repair.loop as loop_mod

    agent = RepairAgent(gateway)
    loop = RepairLoop(agent=agent, validator=validator)
    monkeypatch.setattr(main_mod, "BuildValidator", lambda *a, **k: validator)
    monkeypatch.setattr(loop_mod, "RepairLoop", lambda *a, **k: loop)
    return loop, agent


def _run_endpoint(client, project_id, monkeypatch, validator, gateway):
    loop, agent = _wire(monkeypatch, validator, gateway)
    response = client.post(f"/api/projects/{project_id}/validate?run_repair=true")
    assert response.status_code == 200
    from app import storage

    return storage.load_manifest(project_id), loop, agent


# --- Test 1: builds successfully, no repair call ------------------------


def test_successful_build_makes_no_repair_call(project, monkeypatch):
    validator = FakeValidator([_ok()])
    gateway = FakeGateway([_change("<h1>unused</h1>")])
    with TestClient(app) as client:
        manifest, loop, agent = _run_endpoint(client, project, monkeypatch, validator, gateway)

    assert manifest.state == AgentState.READY
    assert gateway.calls == [], "a green build must not reach the model"
    assert agent.telemetry == []


# --- Test 2: first repair fixes it --------------------------------------


def test_first_repair_succeeds(project, monkeypatch):
    from app import storage

    validator = FakeValidator([_fail(), _ok()])
    gateway = FakeGateway([_change("<h1>fixed</h1>")])
    with TestClient(app) as client:
        manifest, loop, _ = _run_endpoint(client, project, monkeypatch, validator, gateway)

    assert manifest.state == AgentState.READY
    assert len(gateway.calls) == 1
    assert validator.calls == 2, "the full lifecycle reruns after a repair"
    page = (storage.PROJECTS_DIR / project / "app" / "page.tsx").read_text(encoding="utf-8")
    assert "<h1>fixed</h1>" in page


# --- Test 3: second repair succeeds -------------------------------------


def test_second_repair_succeeds(project, monkeypatch):
    validator = FakeValidator([_fail(), _fail(), _ok()])
    gateway = FakeGateway(_chain(2))
    with TestClient(app) as client:
        manifest, loop, _ = _run_endpoint(client, project, monkeypatch, validator, gateway)

    assert manifest.state == AgentState.READY
    assert len(gateway.calls) == 2


# --- Test 4: three failures => FAILED -----------------------------------


def test_failed_after_three_attempts(project, monkeypatch):
    validator = FakeValidator([_fail()])
    gateway = FakeGateway(_chain(3))
    with TestClient(app) as client:
        manifest, loop, _ = _run_endpoint(client, project, monkeypatch, validator, gateway)

    assert manifest.state == AgentState.FAILED
    assert len(gateway.calls) == 3
    assert validator.calls == 4, "initial build plus one rebuild per attempt"


def test_failure_does_not_claim_success(project, monkeypatch):
    validator = FakeValidator([_fail()])
    gateway = FakeGateway(_chain(3))
    with TestClient(app) as client:
        manifest, _, _ = _run_endpoint(client, project, monkeypatch, validator, gateway)

    assert manifest.state != AgentState.READY
    assert manifest.validation is not None
    assert manifest.validation.success is False


def test_dashboard_progress_shows_attempts(project, monkeypatch):
    validator = FakeValidator([_fail()])
    gateway = FakeGateway(_chain(3))
    with TestClient(app) as client:
        manifest, _, _ = _run_endpoint(client, project, monkeypatch, validator, gateway)

    assert any("Repair attempt 1/3" in line for line in manifest.progress)
    assert any("Repair attempt 3/3" in line for line in manifest.progress)


# --- Test 5: ../outside-file is rejected --------------------------------


def test_traversal_change_rejected(project, monkeypatch):
    from app import storage

    validator = FakeValidator([_fail()])
    escape = storage.PROJECTS_DIR.parent / "escape.tsx"
    reply = json.dumps(
        {"summary": "x", "changes": [{"file": "../escape.tsx", "original": "a", "replacement": "b"}]}
    )
    gateway = FakeGateway([reply] * 3)
    with TestClient(app) as client:
        manifest, _, _ = _run_endpoint(client, project, monkeypatch, validator, gateway)

    assert manifest.state == AgentState.FAILED
    assert not escape.exists()


def test_backend_source_is_untouched(project, monkeypatch):
    """A repair aimed at the backend is rejected, not merely reported."""
    from app import storage

    marker = storage.PROJECTS_DIR / project / "app" / "page.tsx"
    before = marker.read_text(encoding="utf-8")
    validator = FakeValidator([_fail()])
    reply = json.dumps(
        {
            "summary": "x",
            "changes": [
                {
                    "file": "../../../apps/api/app/main.py",
                    "original": "a",
                    "replacement": "b",
                }
            ],
        }
    )
    gateway = FakeGateway([reply] * 3)
    with TestClient(app) as client:
        _run_endpoint(client, project, monkeypatch, validator, gateway)
    assert marker.read_text(encoding="utf-8") == before


# --- Test 6: arbitrary command execution is rejected --------------------


def test_command_injection_rejected(project, monkeypatch):
    from app import storage

    validator = FakeValidator([_fail()])
    reply = json.dumps(
        {
            "summary": "x",
            "changes": [
                {
                    "file": "app/page.tsx",
                    "original": "<h1>broken</h1>",
                    "replacement": "import {execSync} from 'child_process'; execSync('rm -rf /');",
                }
            ],
        }
    )
    gateway = FakeGateway([reply] * 3)
    with TestClient(app) as client:
        manifest, _, _ = _run_endpoint(client, project, monkeypatch, validator, gateway)

    assert manifest.state == AgentState.FAILED
    page = (storage.PROJECTS_DIR / project / "app" / "page.tsx").read_text(encoding="utf-8")
    assert "child_process" not in page
    assert "execSync" not in page


def test_env_file_is_never_modified(project, monkeypatch):
    from app import storage

    env = storage.PROJECTS_DIR / project / ".env"
    env.write_text("AI_GATEWAY_API_KEY=secret\n", encoding="utf-8")
    validator = FakeValidator([_fail()])
    reply = json.dumps(
        {"summary": "x", "changes": [{"file": ".env", "original": "secret", "replacement": "leaked"}]}
    )
    gateway = FakeGateway([reply] * 3)
    with TestClient(app) as client:
        _run_endpoint(client, project, monkeypatch, validator, gateway)
    assert env.read_text(encoding="utf-8") == "AI_GATEWAY_API_KEY=secret\n"


def test_env_contents_never_reach_the_prompt(project, monkeypatch):
    from app import storage

    (storage.PROJECTS_DIR / project / ".env").write_text("KEY=DO_NOT_LEAK\n", encoding="utf-8")
    validator = FakeValidator([_fail()])
    gateway = FakeGateway(_chain(3))
    with TestClient(app) as client:
        _run_endpoint(client, project, monkeypatch, validator, gateway)
    assert "DO_NOT_LEAK" not in gateway.calls[0]["user"]


# --- a repaired project is still previewable ----------------------------


def test_repaired_project_gets_a_preview_url(project, monkeypatch):
    """A project that only reaches READY via repair must be previewable.

    main.validate_project sets preview_url on the initial-success path, so
    without this the repair path returned READY with preview_url=None and
    the dashboard had nothing to embed.
    """
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "preview_available", lambda pid: True)
    monkeypatch.setattr(main_mod, "preview_url", lambda pid: f"/api/projects/{pid}/preview/")

    validator = FakeValidator([_fail(), _ok()])
    gateway = FakeGateway([_change("<h1>fixed</h1>")])
    with TestClient(app) as client:
        manifest, _, _ = _run_endpoint(client, project, monkeypatch, validator, gateway)

    assert manifest.state == AgentState.READY
    assert manifest.preview_url == f"/api/projects/{project}/preview/"


def test_repair_without_an_export_leaves_preview_url_unset(project, monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "preview_available", lambda pid: False)
    monkeypatch.setattr(main_mod, "preview_url", lambda pid: "/should/not/be/used/")

    validator = FakeValidator([_fail(), _ok()])
    gateway = FakeGateway([_change("<h1>fixed</h1>")])
    with TestClient(app) as client:
        manifest, _, _ = _run_endpoint(client, project, monkeypatch, validator, gateway)

    assert manifest.state == AgentState.READY
    assert manifest.preview_url is None, "must not advertise a preview that does not exist"


# --- repair can be disabled --------------------------------------------


def test_run_repair_false_fails_without_calling_the_model(project, monkeypatch):
    validator = FakeValidator([_fail()])
    gateway = FakeGateway(_chain(3))
    with TestClient(app) as client:
        response = client.post(f"/api/projects/{project}/validate?run_repair=false")
        assert response.status_code == 200
    from app import storage

    manifest = storage.load_manifest(project)
    assert manifest.state == AgentState.FAILED
    assert gateway.calls == []


# --- polling interface is preserved ------------------------------------


def test_validate_returns_manifest_immediately(project, monkeypatch):
    validator = FakeValidator([_ok()])
    gateway = FakeGateway([])
    with TestClient(app) as client:
        response = client.post(f"/api/projects/{project}/validate")
        assert response.status_code == 200
        body = response.json()
        assert body["project_id"] == project
        assert "state" in body and "progress" in body
