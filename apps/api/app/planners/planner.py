"""AI planner: WebsiteSpec -> GenerationPlan.

This is the only place the pipeline calls a model, and it makes exactly one call
per plan. Everything before it — DOM extraction, colors, typography, section
metadata, screenshots, URL validation — is deterministic and done in the
browser.

Failure policy: a missing, slow, or malformed model response never loses work.
The deterministic builder produces a valid plan from the same spec, and the
reason is recorded in `plan.warnings` and `plan.source`.
"""

from __future__ import annotations

import time

from ..ai.gateway import AIGatewayCompletion, AIGatewayProvider
from ..models.schemas import GenerationPlan, WebsiteSpec
from .parsing import PlanParseError, diff_from_expected, repair_and_parse
from .plan_builder import build_fallback_plan
from .prompt import SYSTEM_PROMPT, build_prompt

MAX_PROMPT_CHARS = 120_000


class Planner:
    """Turns a WebsiteSpec into a GenerationPlan."""

    def __init__(self, provider: AIGatewayProvider | None = None, force_fallback: bool = False) -> None:
        self.provider = provider if provider is not None else AIGatewayProvider.from_environment()
        self.force_fallback = force_fallback

    @property
    def configured(self) -> bool:
        return bool(self.provider.configured) and not self.force_fallback

    def create(self, spec: WebsiteSpec) -> GenerationPlan:
        if not self.configured:
            return build_fallback_plan(
                spec,
                warnings=["AI Gateway is not configured; plan built deterministically from the analyzed spec."],
            )

        prompt = build_prompt(spec)
        if len(prompt) > MAX_PROMPT_CHARS:
            # Compression failed to bound the payload; do not spend tokens on it.
            return build_fallback_plan(
                spec,
                warnings=[
                    f"Compressed spec was {len(prompt)} characters, above the {MAX_PROMPT_CHARS} limit; "
                    "skipped the model call and built the plan deterministically."
                ],
            )

        started = time.perf_counter()
        try:
            completion = self.provider.complete_detailed(
                system=SYSTEM_PROMPT, user=prompt, operation="generation-plan"
            )
        except Exception as exc:
            return build_fallback_plan(
                spec,
                warnings=[f"AI Gateway call failed ({type(exc).__name__}); plan built deterministically."],
            )

        plan, warnings = self._parse(completion, spec)
        plan.latency_ms = int((time.perf_counter() - started) * 1000)
        plan.warnings = [*warnings, *plan.warnings]
        return plan

    def _parse(self, completion: AIGatewayCompletion, spec: WebsiteSpec) -> tuple[GenerationPlan, list[str]]:
        warnings: list[str] = []
        try:
            plan = repair_and_parse(completion.content)
        except PlanParseError as exc:
            # A malformed response must not lose the analysis that produced it.
            fallback = build_fallback_plan(
                spec,
                warnings=[f"Model response rejected: {exc.message} ({exc.detail or 'no detail'})."],
            )
            self._apply_usage(fallback, completion)
            return fallback, warnings

        plan = self._reconcile(plan, spec)
        plan.source = "ai"
        self._apply_usage(plan, completion)
        return plan, warnings

    def _reconcile(self, plan: GenerationPlan, spec: WebsiteSpec) -> GenerationPlan:
        """Fill gaps and clamp drift against the analyzed spec.

        A model may omit sections or invent ones. The spec is the source of
        truth for ordering, so any section index the analyzer found but the
        plan dropped is appended in the observed order.
        """
        warnings: list[str] = []
        analyzed = [section.order for section in spec.sections]
        if analyzed:
            if not plan.section_order:
                plan.section_order = analyzed
                warnings.append("Model returned no section order; used the analyzed order.")
            else:
                missing = [index for index in analyzed if index not in plan.section_order]
                extra = [index for index in plan.section_order if index not in analyzed]
                if missing:
                    # Preserve the analyzed sequence, keep any model extras.
                    ordered = [index for index in analyzed if index in plan.section_order]
                    ordered.extend(index for index in plan.section_order if index not in analyzed)
                    plan.section_order = ordered + [index for index in missing if index not in ordered]
                    warnings.append(f"Restored {len(missing)} section(s) the model omitted.")
                if extra:
                    warnings.append(f"Model referenced {len(extra)} section index(es) not present in the analysis.")
        warnings.extend(diff_from_expected(plan, len(analyzed)))

        known = {section.order for section in spec.sections}
        plan.components = [
            component
            for component in plan.components
            if not component.source_section_indexes
            or set(component.source_section_indexes) <= known
        ]
        return plan

    def _apply_usage(self, plan: GenerationPlan, completion: AIGatewayCompletion) -> None:
        plan.model = completion.model
        plan.prompt_tokens = completion.prompt_tokens
        plan.completion_tokens = completion.completion_tokens
        plan.total_tokens = completion.total_tokens
        if not plan.latency_ms:
            plan.latency_ms = completion.latency_ms
