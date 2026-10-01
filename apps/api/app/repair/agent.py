"""Repair agent: turn build diagnostics into a targeted patch plan.

The agent is deliberately narrow. It never executes shell commands, never
writes outside the generated project, and never regenerates whole files. It
receives a small set of relevant source files plus structured diagnostics and
returns a list of exact-match replacements.
"""

from __future__ import annotations

import json
import re
import logging
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, Field, ValidationError

from ..ai.gateway import AIGatewayProvider
from ..models.schemas import WebsiteSpec
from ..storage import project_dir
from .diagnostics import BuildDiagnostic
from .patch import (
    RepairChange,
    project_file_tree,
    read_context,
    select_relevant_files,
    validate_patch,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
MAX_REPAIR_CALLS = 3


class RepairPlan(BaseModel):
    """Structured output from the repair agent."""

    summary: str = ""
    changes: list[RepairChange] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


_REPAIR_SYSTEM = (
    "You repair build errors in a generated Next.js + React + TypeScript project. "
    "You return only a JSON repair plan. You never run commands, never write files, "
    "and never access anything outside the project."
)

_REPAIR_PROMPT = """You are a repair agent for a generated Next.js 14 + React 18 + TypeScript project.

Your job is to make MINIMAL, TARGETED changes to fix the build errors listed below.
Do NOT rewrite whole files. Do NOT add new features. Do NOT change styling.

Return ONLY a JSON object with this exact shape:
{
  "summary": "one sentence describing the fix",
  "changes": [
    {
      "file": "relative/path/from/project/root",
      "action": "replace",
      "original": "exact existing text to replace",
      "replacement": "new text",
      "reason": "why this change fixes the error"
    }
  ]
}

Rules:
- "original" must be an EXACT substring of the current file content.
- Prefer the smallest possible change.
- If a file is missing or a module cannot be found, fix the import path or add the
  missing dependency name to the reason so the caller can handle it.
- If you cannot fix an error safely, omit it from "changes" and explain in "summary".
- Never propose changes to files outside the project root.
- Never propose shell commands, package.json scripts, or .env edits.

This is repair attempt __ATTEMPT__. If you have already tried and failed, choose a different fix.

Project root: __PROJECT_ID__

Build errors:
__DIAGNOSTICS__

Relevant files:
__FILES__
"""


def build_prompt(project_id: str, attempt: int, diagnostics: str, files: str) -> str:
    """Fill the repair prompt.

    Uses explicit placeholders rather than ``str.format``: the prompt embeds a
    JSON example, whose braces ``str.format`` would try to substitute.
    """
    return (
        _REPAIR_PROMPT.replace("__ATTEMPT__", str(attempt))
        .replace("__PROJECT_ID__", project_id)
        .replace("__DIAGNOSTICS__", diagnostics)
        .replace("__FILES__", files)
    )


def _format_diagnostics(diagnostics: Sequence[BuildDiagnostic]) -> str:
    lines: list[str] = []
    for d in diagnostics:
        loc = f" ({d.file}" + (f":{d.line}" if d.line else "") + (f":{d.column}" if d.column else "") + ")" if d.file else ""
        lines.append(f"- [{d.category}] {d.message}{loc}")
    return "\n".join(lines) if lines else "- (no structured diagnostics)"


def _format_files(context: dict[str, str], tree: str = "") -> str:
    if not context:
        # Nothing was implicated: give the shape of the project instead of
        # its contents.
        return f"(no file could be identified; project files)\n{tree}"
    parts: list[str] = []
    for path, content in context.items():
        parts.append(f"--- {path} ---\n{content}\n")
    return "\n".join(parts)


def _extract_json(text: str) -> str:
    """Pull the first JSON object out of a model response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    return text[start : end + 1]


def _parse_plan(text: str) -> RepairPlan:
    """Parse and validate the model's repair response."""
    payload = _extract_json(text)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        raise ValueError("repair response is not valid JSON")
    try:
        return RepairPlan.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"repair response failed validation: {exc}")


class RepairAgent:
    """Produces targeted repair plans from build diagnostics."""

    def __init__(self, gateway: AIGatewayProvider | None = None) -> None:
        # Resolve environment configuration at construction time. Using the
        # dataclass defaults here would silently ignore AI_GATEWAY_API_KEY and
        # make repair appear unavailable even when the gateway is configured.
        self.gateway = gateway or AIGatewayProvider.from_environment()
        # Per-call usage, appended by build_plan. Read by the loop for
        # reporting; it is never a reason to skip a repair.
        self.telemetry: list[dict] = []

    def build_plan(
        self,
        project_id: str,
        diagnostics: list[BuildDiagnostic],
        spec: WebsiteSpec | None = None,
        attempt: int = 1,
    ) -> RepairPlan:
        """Generate a repair plan for the given diagnostics."""
        root = project_dir(project_id)
        relpaths = select_relevant_files(diagnostics, root)
        context = read_context(project_id, relpaths)

        prompt = build_prompt(
            project_id=project_id,
            attempt=attempt,
            diagnostics=_format_diagnostics(diagnostics),
            files=_format_files(context, project_file_tree(root)),
        )

        try:
            completion = self.gateway.complete_detailed(
                system=_REPAIR_SYSTEM, user=prompt, operation="repair"
            )
        except Exception as exc:  # noqa: BLE001 - gateway failure is a repair error
            logger.warning("repair gateway call failed: %s", exc)
            return RepairPlan(summary=f"repair unavailable: {exc}", changes=[])

        # Telemetry is recorded per call so a project's repair cost is
        # auditable; it is never used to decide whether to continue.
        self.telemetry.append(
            {
                "operation": "repair",
                "model": completion.model,
                "latency_ms": completion.latency_ms,
                "prompt_tokens": completion.prompt_tokens,
                "completion_tokens": completion.completion_tokens,
                "total_tokens": completion.total_tokens,
                "attempt": attempt,
            }
        )

        try:
            plan = _parse_plan(completion.content)
        except ValueError as exc:
            # A malformed response is a repair failure, not a repair: no file
            # is touched and the loop is allowed to try again.
            logger.warning("repair plan parse failed: %s", exc)
            return RepairPlan(summary=f"repair plan rejected: {exc}", changes=[])

        plan.changes = [c for c in plan.changes if _is_safe_change(project_id, c)]
        return plan


def _is_safe_change(project_id: str, change: RepairChange) -> bool:
    """Reject a proposed change the backend would refuse to apply.

    This runs the same ``validate_patch`` the applier runs, so a change is
    filtered at plan time and again at apply time. Filtering early keeps an
    unsafe proposal from being reported as a planned repair; filtering again
    is deliberate — the plan is untrusted input either way.
    """
    from .patch import _resolve

    if validate_patch(project_id, change) is not None:
        return False
    try:
        target = _resolve(project_id, change.file)
    except ValueError:
        return False
    return target.is_file()
