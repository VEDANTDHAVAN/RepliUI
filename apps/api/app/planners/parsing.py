"""Safe parsing of AI planner responses.

A model can return fenced JSON, prose before or after the object, an empty
body, or a structurally wrong object. None of that should surface as a stack
trace or as a crash mid-pipeline, so parsing is isolated here and reports
exactly what went wrong.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from ..models.schemas import GenerationPlan, PlannedPage

# ```json ... ``` and bare ``` ... ``` fences.
FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
# A bare object anywhere in the response, used when fences are missing/broken.
OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


class PlanParseError(ValueError):
    """The model response could not be turned into a GenerationPlan."""

    def __init__(self, message: str, raw: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.raw = raw[:4000]
        self.detail = detail[:1000]


def extract_json(raw: str) -> str:
    """Pull the JSON object out of a model response."""
    if not raw or not raw.strip():
        raise PlanParseError("The model returned an empty response", raw=raw)
    fenced = FENCE_PATTERN.search(raw)
    candidate = fenced.group(1).strip() if fenced else raw.strip()
    if candidate.startswith(("{", "[")):
        return candidate
    loose = OBJECT_PATTERN.search(candidate)
    if loose:
        return loose.group(0)
    raise PlanParseError("No JSON object found in the model response", raw=raw)


def parse_plan(raw: str) -> GenerationPlan:
    """Parse and validate a model response into a GenerationPlan."""
    payload = _loads(extract_json(raw), raw)
    if not isinstance(payload, dict):
        raise PlanParseError("Model response was not a JSON object", raw=raw, detail=type(payload).__name__)
    return _validate(payload, raw)


def _loads(text: str, raw: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanParseError(
            "Model response was not valid JSON",
            raw=raw,
            detail=f"{exc.msg} at line {exc.lineno} column {exc.colno}",
        ) from exc


def _validate(payload: dict, raw: str) -> GenerationPlan:
    try:
        return GenerationPlan.model_validate(payload)
    except ValidationError as exc:
        missing = _missing_fields(exc)
        raise PlanParseError(
            "Model response did not match the expected plan shape",
            raw=raw,
            detail="missing or invalid: " + ", ".join(missing) if missing else str(exc)[:500],
        ) from exc


def _missing_fields(exc: ValidationError) -> list[str]:
    problems: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        problems.append(f"{location} ({error['type']})")
    return problems[:10]


def repair_and_parse(raw: str) -> GenerationPlan:
    """Best-effort parse for a partial response.

    Keeps whatever the model got right: the plan's fields all have defaults, so
    a partial object still validates into a usable (if incomplete) plan. Raises
    only when nothing usable can be recovered.
    """
    try:
        return parse_plan(raw)
    except PlanParseError as first:
        repaired = _repair_shape(raw)
        if repaired is None:
            raise
        try:
            return _validate(repaired, raw)
        except PlanParseError:
            raise first from None


def _repair_shape(raw: str) -> dict | None:
    """Coerce near-miss shapes into a GenerationPlan-compatible dict."""
    try:
        payload = _loads(extract_json(raw), raw)
    except PlanParseError:
        return None
    if not isinstance(payload, dict):
        return None
    repaired = dict(payload)
    # A model may return a single component object instead of a list.
    if isinstance(repaired.get("components"), dict):
        repaired["components"] = [repaired["components"]]
    if isinstance(repaired.get("pages"), dict):
        page = dict(repaired["pages"])
        page.setdefault("path", "/")
        repaired["pages"] = [PlannedPage.model_validate(page).model_dump()]
    if isinstance(repaired.get("assets"), dict):
        repaired["assets"] = [repaired["assets"]]
    if isinstance(repaired.get("implementation_notes"), str):
        repaired["implementation_notes"] = [repaired["implementation_notes"]]
    if isinstance(repaired.get("project_structure"), str):
        repaired["project_structure"] = [repaired["project_structure"]]
    return repaired


def diff_from_expected(plan: GenerationPlan, expected_sections: int) -> list[str]:
    """Report, as warnings, how far a plan drifted from the analyzed spec."""
    warnings: list[str] = []
    if expected_sections and len(plan.section_order) < expected_sections:
        warnings.append(
            f"plan covers {len(plan.section_order)} of {expected_sections} detected sections"
        )
    if not plan.pages:
        warnings.append("plan defines no pages")
    if not plan.components:
        warnings.append("plan defines no components")
    if not plan.theme.primary and not plan.theme.background:
        warnings.append("plan carries no theme tokens")
    return warnings


def usage_from_response(payload: dict | None) -> dict[str, int | None]:
    """Extract approximate token usage from a gateway response, if reported."""
    if not isinstance(payload, dict):
        return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    return {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }
