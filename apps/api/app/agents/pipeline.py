"""Analysis → planning pipeline.

One place that wires the deterministic analyzer to the AI planner and handles
persistence, so the API layer stays thin. Failures are translated into safe,
user-facing messages; internal exception detail never reaches the client.
"""

from __future__ import annotations

from ..analyzers import (
    AnalysisError,
    BrowserUnavailableError,
    InaccessibleSiteError,
    NavigationTimeoutError,
    WebsiteAnalyzer,
    urls,
)
from ..models.schemas import GenerationPlan, WebsiteSpec
from ..planners import Planner
from ..storage import (
    load_generation_plan,
    load_website_spec,
    save_generation_plan,
    save_website_spec,
)

__all__ = [
    "AnalysisPipeline",
    "AnalysisError",
    "BrowserUnavailableError",
    "InaccessibleSiteError",
    "NavigationTimeoutError",
    "UserFacingError",
]


class UserFacingError(Exception):
    """An error whose message is safe to return to the client."""


def to_user_message(exc: Exception) -> str:
    """Map an internal failure to a message with no internals in it."""
    if isinstance(exc, UserFacingError):
        return str(exc)
    if isinstance(exc, urls.InvalidURLError):
        return str(exc)
    if isinstance(exc, InaccessibleSiteError):
        return f"Could not reach this website: {exc}"
    if isinstance(exc, NavigationTimeoutError):
        return "The website took too long to load. Try again or use a lighter page."
    if isinstance(exc, BrowserUnavailableError):
        return "The analysis browser is unavailable on this server."
    if isinstance(exc, AnalysisError):
        return f"Analysis failed: {exc}"
    if isinstance(exc, TimeoutError):
        return "The analysis timed out."
    return "The analysis could not be completed."


class AnalysisPipeline:
    """Runs the analyzer, persists the spec, then plans from it."""

    def __init__(self, analyzer: WebsiteAnalyzer | None = None, planner: Planner | None = None) -> None:
        self.analyzer = analyzer or WebsiteAnalyzer()
        self.planner = planner or Planner()

    async def analyze(self, url: str, project_id: str) -> WebsiteSpec:
        """Analyze a URL and persist the resulting spec.

        The plan is not produced here: planning is a separate, explicit step so a
        caller can inspect the analysis first.
        """
        try:
            spec = await self.analyzer.analyze(url, project_id)
        except (AnalysisError, urls.InvalidURLError, TimeoutError) as exc:
            raise UserFacingError(to_user_message(exc)) from exc
        if not spec.sections and not spec.headings and not spec.paragraphs and not spec.navigation:
            raise UserFacingError(
                "The page loaded, but no usable website structure was captured. "
                "It may require a browser challenge, login, or client-side interaction."
            )
        save_website_spec(project_id, spec)
        return spec

    async def analyze_html(self, html: str, base_url: str, project_id: str) -> WebsiteSpec:
        """Analyze a caller-supplied document; used by tests and local fixtures."""
        try:
            spec = await self.analyzer.analyze_html(html, base_url, project_id)
        except (AnalysisError, urls.InvalidURLError, TimeoutError) as exc:
            raise UserFacingError(to_user_message(exc)) from exc
        save_website_spec(project_id, spec)
        return spec

    def plan(self, project_id: str, spec: WebsiteSpec | None = None) -> GenerationPlan:
        """Produce and persist a GenerationPlan from the stored or given spec."""
        target = spec if spec is not None else self._load_spec(project_id)
        plan = self.planner.create(target)
        save_generation_plan(project_id, plan)
        return plan

    async def analyze_and_plan(self, url: str, project_id: str) -> tuple[WebsiteSpec, GenerationPlan]:
        spec = await self.analyze(url, project_id)
        return spec, self.plan(project_id, spec)

    def _load_spec(self, project_id: str) -> WebsiteSpec:
        try:
            return load_website_spec(project_id)
        except FileNotFoundError as exc:
            raise UserFacingError("No analysis exists for this project yet.") from exc
        except ValueError as exc:
            raise UserFacingError("The stored analysis is unreadable. Re-run the analysis.") from exc

    def load_plan(self, project_id: str) -> GenerationPlan:
        try:
            return load_generation_plan(project_id)
        except FileNotFoundError as exc:
            raise UserFacingError("No generation plan exists for this project yet.") from exc
        except ValueError as exc:
            raise UserFacingError("The stored plan is unreadable. Re-run the plan.") from exc
