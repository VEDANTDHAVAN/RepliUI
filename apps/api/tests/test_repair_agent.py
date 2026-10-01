"""Unit tests for the RepairAgent: structured output, telemetry, and limits."""

from __future__ import annotations

import json

import pytest

from app.ai.gateway import AIGatewayCompletion
from app.repair.agent import (
    RepairAgent,
    _extract_json,
    _parse_plan,
    build_prompt,
)
from app.repair.diagnostics import MODULE_NOT_FOUND, TYPESCRIPT_ERROR, BuildDiagnostic


class FakeGateway:
    """Stands in for AIGatewayProvider; records what the agent sent."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete_detailed(self, *, system: str, user: str, operation: str):
        self.calls.append({"system": system, "user": user, "operation": operation})
        reply = self._responses.pop(0) if self._responses else "{}"
        if isinstance(reply, Exception):
            raise reply
        return AIGatewayCompletion(
            content=reply,
            model="test/model",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            latency_ms=42,
        )


@pytest.fixture()
def project() -> str:
    from app import storage

    project_id = "agentproject12"
    root = storage.PROJECTS_DIR / project_id
    (root / "components").mkdir(parents=True, exist_ok=True)
    (root / "components" / "Hero.tsx").write_text(
        "export function Hero() {\n  return <h1>hi</h1>;\n}\n", encoding="utf-8"
    )
    (root / "package.json").write_text('{"name": "site"}', encoding="utf-8")
    return project_id


def _diag(**kw) -> BuildDiagnostic:
    base = dict(stage="build", command="npm run build", message="err")
    base.update(kw)
    return BuildDiagnostic(**base)


def _reply(changes, summary="fix") -> str:
    return json.dumps({"summary": summary, "changes": changes})


# --- prompt construction ------------------------------------------------


def test_prompt_keeps_json_example_braces():
    # Regression: str.format choked on the embedded JSON example.
    prompt = build_prompt("p1", 1, "diag", "files")
    assert '"summary"' in prompt
    assert "__PROJECT_ID__" not in prompt


def test_prompt_includes_diagnostics_and_files(project):
    gateway = FakeGateway([_reply([])])
    agent = RepairAgent(gateway)
    agent.build_plan(
        project,
        [_diag(file="components/Hero.tsx", category=TYPESCRIPT_ERROR, message="bad prop")],
    )
    prompt = gateway.calls[0]["user"]
    assert "bad prop" in prompt
    assert "components/Hero.tsx" in prompt
    assert TYPESCRIPT_ERROR in prompt


def test_prompt_does_not_include_unrelated_files(project):
    from app import storage

    root = storage.PROJECTS_DIR / project
    (root / "components" / "Unrelated.tsx").write_text("SECRET_UNRELATED_MARKER", encoding="utf-8")
    gateway = FakeGateway([_reply([])])
    RepairAgent(gateway).build_plan(
        project, [_diag(file="components/Hero.tsx", category=TYPESCRIPT_ERROR)]
    )
    # Hero is the diagnosed file; Unrelated.tsx is not implicated by a
    # diagnostic, a type error, or an import edge, so it must stay out.
    assert "components/Hero.tsx" in gateway.calls[0]["user"]
    assert "SECRET_UNRELATED_MARKER" not in gateway.calls[0]["user"]


def test_env_file_never_reaches_prompt(project):
    from app import storage

    (storage.PROJECTS_DIR / project / ".env").write_text("API_KEY=TOPSECRET", encoding="utf-8")
    gateway = FakeGateway([_reply([])])
    RepairAgent(gateway).build_plan(project, [_diag(file=".env", category=TYPESCRIPT_ERROR)])
    assert "TOPSECRET" not in gateway.calls[0]["user"]


# --- response parsing ---------------------------------------------------


def test_parses_plain_json():
    plan = _parse_plan(_reply([{"file": "a.tsx", "original": "x", "replacement": "y"}]))
    assert len(plan.changes) == 1
    assert plan.changes[0].file == "a.tsx"


def test_parses_fenced_json():
    text = "```json\n" + _reply([{"file": "a.tsx", "original": "x", "replacement": "y"}]) + "\n```"
    assert len(_parse_plan(text).changes) == 1


def test_parses_json_with_surrounding_prose():
    text = "Sure! Here is the plan:\n" + _reply([]) + "\nHope that helps."
    assert _parse_plan(text).changes == []


@pytest.mark.parametrize(
    "bad",
    ["not json at all", "", "{", "[1,2,3]", '{"summary": "s", "changes": "not-a-list"}'],
)
def test_malformed_response_raises(bad):
    with pytest.raises(ValueError):
        _parse_plan(bad)


def test_malformed_response_yields_empty_plan(project):
    agent = RepairAgent(FakeGateway(["totally not json"]))
    plan = agent.build_plan(project, [_diag(category=TYPESCRIPT_ERROR)])
    # A malformed response must not modify files or claim success.
    assert plan.changes == []
    assert "rejected" in plan.summary


def test_gateway_exception_yields_empty_plan(project):
    agent = RepairAgent(FakeGateway([RuntimeError("gateway down")]))
    plan = agent.build_plan(project, [_diag(category=TYPESCRIPT_ERROR)])
    assert plan.changes == []
    assert "unavailable" in plan.summary


# --- plan validation ----------------------------------------------------


def test_valid_plan_is_kept(project):
    reply = _reply(
        [
            {
                "file": "components/Hero.tsx",
                "original": "<h1>hi</h1>",
                "replacement": "<h1>hello</h1>",
                "reason": "unused var",
            }
        ]
    )
    plan = RepairAgent(FakeGateway([reply])).build_plan(project, [_diag(category=TYPESCRIPT_ERROR)])
    assert len(plan.changes) == 1
    assert plan.changes[0].reason == "unused var"


def test_change_to_nonexistent_file_is_dropped(project):
    reply = _reply([{"file": "components/Ghost.tsx", "original": "a", "replacement": "b"}])
    plan = RepairAgent(FakeGateway([reply])).build_plan(project, [_diag(category=TYPESCRIPT_ERROR)])
    assert plan.changes == []


def test_change_outside_project_is_dropped(project):
    reply = _reply([{"file": "../escape.tsx", "original": "a", "replacement": "b"}])
    plan = RepairAgent(FakeGateway([reply])).build_plan(project, [_diag(category=TYPESCRIPT_ERROR)])
    assert plan.changes == []


def test_env_change_is_dropped(project):
    from app import storage

    (storage.PROJECTS_DIR / project / ".env").write_text("K=v", encoding="utf-8")
    reply = _reply([{"file": ".env", "original": "K=v", "replacement": "K=hacked"}])
    plan = RepairAgent(FakeGateway([reply])).build_plan(project, [_diag(category=TYPESCRIPT_ERROR)])
    assert plan.changes == []


def test_extra_fields_are_ignored(project):
    reply = json.dumps(
        {
            "summary": "s",
            "changes": [
                {
                    "file": "components/Hero.tsx",
                    "original": "<h1>hi</h1>",
                    "replacement": "<h1>hey</h1>",
                    "junk": 1,
                }
            ],
            "unrelated": "ignored",
        }
    )
    plan = RepairAgent(FakeGateway([reply])).build_plan(project, [_diag(category=TYPESCRIPT_ERROR)])
    assert len(plan.changes) == 1


def test_empty_changes_list_is_valid(project):
    plan = RepairAgent(FakeGateway([_reply([], summary="I cannot fix this safely")])).build_plan(
        project, [_diag(category=TYPESCRIPT_ERROR)]
    )
    assert plan.changes == []


# --- telemetry ----------------------------------------------------------


def test_telemetry_recorded_per_call(project):
    agent = RepairAgent(FakeGateway([_reply([]), _reply([])]))
    agent.build_plan(project, [_diag(category=TYPESCRIPT_ERROR)], attempt=1)
    agent.build_plan(project, [_diag(category=TYPESCRIPT_ERROR)], attempt=2)
    assert len(agent.telemetry) == 2
    entry = agent.telemetry[0]
    assert entry["model"] == "test/model"
    assert entry["operation"] == "repair"
    assert entry["latency_ms"] == 42
    assert entry["total_tokens"] == 15
    assert entry["attempt"] == 1


def test_telemetry_recorded_even_for_malformed_response(project):
    agent = RepairAgent(FakeGateway(["garbage"]))
    agent.build_plan(project, [_diag(category=TYPESCRIPT_ERROR)])
    # The call was made and cost tokens, so it must be recorded.
    assert len(agent.telemetry) == 1
    assert agent.telemetry[0]["total_tokens"] == 15


def test_operation_name_is_repair(project):
    gateway = FakeGateway([_reply([])])
    RepairAgent(gateway).build_plan(project, [_diag(category=TYPESCRIPT_ERROR)])
    assert gateway.calls[0]["operation"] == "repair"
