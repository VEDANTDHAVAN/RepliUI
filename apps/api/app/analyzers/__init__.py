"""Browser-backed website analyzer.

`WebsiteAnalyzer` is a thin orchestrator: it drives the browser, hands the
readings to small deterministic extraction modules, and assembles a
`WebsiteSpec`. No model is involved in any extraction step, and raw HTML is
never returned to the caller or to the LLM.

Two entry points share one pipeline:

* `analyze(url)` loads a public page over HTTP(S).
* `analyze_html(html, base_url)` renders a caller-supplied document, which is how
  tests exercise the real browser against a controlled fixture.

`build_spec` is deliberately pure (readings in, spec out) so the whole analysis
can be unit-tested without a browser.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from ..models.schemas import AssetSpec, ScreenshotSpec, ViewportSpec, WebsiteSpec
from ..storage import screenshot_path
from . import assets as asset_extractor
from . import colors, components as component_extractor, document as document_extractor
from . import responsive as responsive_extractor
from . import scripts, sections as section_extractor
from . import typography as typography_extractor
from . import urls
from .raw_models import RawDocument, RawExtraction, RawLayout, ViewportReading

__all__ = [
    "WebsiteAnalyzer",
    "build_spec",
    "AnalysisError",
    "BrowserUnavailableError",
    "InaccessibleSiteError",
    "BlockedBySiteError",
    "NavigationTimeoutError",
    "InvalidURLError",
    "VIEWPORTS",
    "ViewportTarget",
    "urls",
]

InvalidURLError = urls.InvalidURLError


class AnalysisError(RuntimeError):
    """Analysis failed in a way that is safe to show a user."""


class BrowserUnavailableError(AnalysisError):
    """Playwright or its browser binary is not usable."""


class NavigationTimeoutError(AnalysisError):
    """The page did not reach a loadable state in time."""


class InaccessibleSiteError(AnalysisError):
    """The URL could not be reached."""


class BlockedBySiteError(InaccessibleSiteError):
    """The site returned a bot-protection/interstitial page instead of content."""


@dataclass(frozen=True)
class ViewportTarget:
    name: str
    width: int
    height: int
    is_mobile: bool = False
    scale: float = 1.0
    full_page: bool = True


VIEWPORTS: tuple[ViewportTarget, ...] = (
    ViewportTarget("desktop", 1440, 900, False, 1.0, True),
    ViewportTarget("mobile", 390, 844, True, 3.0, True),
)

DEFAULT_NAVIGATION_TIMEOUT_MS = int(os.getenv("ANALYSIS_TIMEOUT_MS", "30000"))
# Time allowed for client-side rendering to settle before measuring the DOM.
RENDER_SETTLE_MS = int(os.getenv("ANALYSIS_SETTLE_MS", "400"))


class WebsiteAnalyzer:
    """Collects a structured WebsiteSpec from a live page."""

    def __init__(
        self,
        nav_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
        max_nodes: int = 3000,
        headless: bool | None = None,
    ) -> None:
        self.nav_timeout_ms = nav_timeout_ms
        self.max_nodes = max_nodes
        self.headless = os.getenv("PLAYWRIGHT_HEADLESS", "1") != "0" if headless is None else headless

    # -- public API -----------------------------------------------------

    async def analyze(self, url: str, project_id: str) -> WebsiteSpec:
        target = urls.validate_url(url)
        host = urlparse(target).hostname or ""
        if host and not urls.is_reachable_host(host):
            raise InaccessibleSiteError(f"Could not resolve host {host}")
        return await self._run(target, project_id, loader=self._load_over_http)

    async def analyze_html(self, html: str, base_url: str, project_id: str) -> WebsiteSpec:
        """Render a supplied document; used for tests and local fixtures."""
        return await self._run(base_url or "", project_id, loader=self._load_from_html(html))

    # -- orchestration --------------------------------------------------

    async def _run(self, base_url: str, project_id: str, loader) -> WebsiteSpec:
        from playwright.async_api import async_playwright

        started = time.perf_counter()
        readings: list[ViewportReading] = []
        screenshots: list[ScreenshotSpec] = []
        warnings: list[str] = []

        try:
            async with async_playwright() as playwright:
                try:
                    browser = await playwright.chromium.launch(headless=self.headless)
                except Exception as exc:  # pragma: no cover - environment dependent
                    raise BrowserUnavailableError("Browser engine unavailable; install Playwright Chromium") from exc
                try:
                    for target in VIEWPORTS:
                        try:
                            reading, shot = await self._read_viewport(browser, target, base_url, loader, project_id)
                        except AnalysisError as exc:
                            warnings.append(f"{target.name}: {exc}")
                            if not readings:
                                raise
                            continue
                        readings.append(reading)
                        screenshots.append(shot)
                finally:
                    await browser.close()
        except AnalysisError:
            raise
        except TimeoutError as exc:
            raise NavigationTimeoutError("Timed out while loading the page") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise AnalysisError(f"Analysis failed: {type(exc).__name__}") from exc

        if not readings:
            raise InaccessibleSiteError("No viewport could be captured for this URL")

        spec = build_spec(readings, screenshots, base_url, warnings)
        if _is_access_challenge(readings):
            raise BlockedBySiteError(
                "The site returned a bot-protection challenge instead of its webpage. "
                "RepliUI cannot reconstruct content that the source site did not make available."
            )
        spec.analysis_duration_ms = int((time.perf_counter() - started) * 1000)
        return spec

    async def _read_viewport(
        self,
        browser,
        target: ViewportTarget,
        base_url: str,
        loader,
        project_id: str,
    ) -> tuple[ViewportReading, ScreenshotSpec]:
        context = await browser.new_context(
            viewport={"width": target.width, "height": target.height},
            is_mobile=target.is_mobile,
            device_scale_factor=target.scale,
            java_script_enabled=True,
        )
        try:
            page = await context.new_page()
            await loader(page, base_url)
            await page.wait_for_timeout(RENDER_SETTLE_MS)
            payload = RawExtraction.model_validate(
                await page.evaluate(scripts.EXTRACT_SCRIPT, scripts.extract_config(max_nodes=self.max_nodes))
            )
            document = RawDocument.model_validate(await page.evaluate(scripts.DOCUMENT_SCRIPT))
            layout = RawLayout.model_validate(await page.evaluate(scripts.LAYOUT_SCRIPT))
            shot = await self._capture(page, target, project_id)
            reading = ViewportReading(
                device=target.name,
                width=target.width,
                height=target.height,
                is_mobile=target.is_mobile,
                scale=target.scale,
                document=document,
                nodes=payload.nodes,
                layout=layout,
                truncated=payload.truncated,
                document_height=max(payload.scroll_height, layout.document_height),
                max_nodes=self.max_nodes,
            )
            return reading, shot
        finally:
            await context.close()

    async def _capture(self, page, target: ViewportTarget, project_id: str) -> ScreenshotSpec:
        destination = screenshot_path(project_id, target.name)
        data = await page.screenshot(full_page=target.full_page, type="png")
        destination.write_bytes(data)
        return ScreenshotSpec(
            path=str(destination),
            label=target.name,
            width=target.width,
            height=target.height,
            viewport_width=target.width,
            viewport_height=target.height,
            device=target.name,
            full_page=target.full_page,
            bytes=len(data),
        )

    async def _load_over_http(self, page, url: str) -> None:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.nav_timeout_ms)
        except TimeoutError as exc:
            raise NavigationTimeoutError("Timed out while loading the page") from exc
        except Exception as exc:
            raise InaccessibleSiteError("The site could not be reached") from exc

    def _load_from_html(self, html: str):
        async def _load(page, _base_url: str) -> None:
            await page.set_content(html, wait_until="domcontentloaded", timeout=self.nav_timeout_ms)

        return _load


# ---------------------------------------------------------------------------
# Spec assembly (pure; no browser, no network).
# ---------------------------------------------------------------------------


def build_spec(
    readings: list[ViewportReading],
    screenshots: list[ScreenshotSpec],
    base_url: str,
    warnings: list[str] | None = None,
) -> WebsiteSpec:
    """Assemble a WebsiteSpec from viewport readings. Deterministic and pure."""
    warnings = list(warnings or [])
    desktop = _pick(readings, is_mobile=False)
    mobile = _pick(readings, is_mobile=True)
    primary = desktop or mobile
    if primary is None:
        raise AnalysisError("No viewport readings were collected")

    palette = colors.extract_palette(primary.nodes)
    detected_components = component_extractor.detect_components(primary.layout, primary.nodes, primary.width)
    index = component_extractor.component_index(detected_components)
    detected_sections = section_extractor.detect_sections(primary, index)
    asset_list = asset_extractor.extract_assets(primary.nodes, base_url)
    _attribute_assets_to_sections(detected_sections, asset_list)
    responsive_spec = responsive_extractor.compare(desktop, mobile) if desktop and mobile else None
    document = primary.document

    if primary.truncated:
        warnings.append(f"DOM extraction stopped at the {element_cap(primary)} element cap")
    if not document.title:
        warnings.append("Page has no title element")
    if not detected_sections:
        warnings.append("No section candidates passed the structural thresholds")

    return WebsiteSpec(
        url=base_url or "https://localhost",  # type: ignore[arg-type]
        final_url=base_url,
        title=document.title or "Untitled website",
        meta_description=document_extractor.meta_value(
            document, "description", "og:description", "twitter:description"
        ),
        lang=document.lang,
        viewport=ViewportSpec(
            width=primary.width,
            height=primary.height,
            device=primary.device,
            is_mobile=primary.is_mobile,
        ),
        theme=palette,
        theme_tokens=colors.build_theme_tokens(primary.nodes, palette),
        typography=typography_extractor.extract_typography(primary.nodes),
        navigation=document_extractor.extract_navigation(primary.nodes, base_url),
        sections=detected_sections,
        components=detected_components,
        assets=asset_list,
        responsive=responsive_spec,
        responsive_rules=responsive_extractor.viewport_rules(readings),
        screenshots=[shot.path for shot in screenshots],
        screenshot_details=screenshots,
        headings=document_extractor.dedupe([item.text for item in document.headings], 60),
        paragraphs=document_extractor.dedupe(document.paragraphs, 40),
        buttons=document_extractor.dedupe(document.buttons, 30),
        links=document_extractor.dedupe([link.href for link in document.links], 80),
        links_count=len(document.links),
        forms=document.form_count,
        form_fields=document_extractor.extract_form_fields(document, primary.nodes),
        dom_node_count=document.node_count or len(primary.nodes),
        document_height=primary.document_height,
        spacing=typography_extractor.extract_spacing(primary.nodes),
        visual=typography_extractor.extract_visual(primary.nodes),
        raw_metadata={
            key: value
            for key, value in document.meta.items()
            if key.startswith(("og:", "twitter:", "description", "author", "theme-color", "application-name"))
        },
        partial=primary.truncated or not document.title,
        warnings=warnings,
    )


_CHALLENGE_MARKERS = (
    "just a moment",
    "checking your browser",
    "verify you are human",
    "performing security verification",
    "enable javascript and cookies",
    "ddos protection",
    "attention required",
)


def _is_access_challenge(readings: list[ViewportReading]) -> bool:
    """Detect common interstitials before they become misleading generated sites.

    This is intentionally conservative: a marker must appear in the title or
    visible document text, and the page must have no meaningful section
    structure. It does not attempt to bypass the challenge.
    """
    for reading in readings:
        title = reading.document.title.strip().lower()
        visible_text = " ".join(
            [
                *reading.document.paragraphs,
                *reading.document.buttons,
                *(heading.text for heading in reading.document.headings),
                *(node.text for node in reading.nodes if node.visible),
            ]
        ).lower()
        marker_found = any(marker in title or marker in visible_text for marker in _CHALLENGE_MARKERS)
        structural_content = len(reading.document.headings) + len(reading.document.paragraphs) + len(reading.layout.groups)
        if marker_found and structural_content < 4:
            return True
    return False


def element_cap(reading: ViewportReading) -> int:
    """The configured element budget for a reading (0 when uncapped)."""
    return reading.max_nodes


def _attribute_assets_to_sections(sections, asset_list: list[AssetSpec]) -> None:
    """Record which section each asset was observed in."""
    for asset in asset_list:
        for section in sections:
            if asset.source_url in section.image_urls:
                asset.section_index = section.order
                break


def _pick(readings: list[ViewportReading], is_mobile: bool) -> ViewportReading | None:
    for reading in readings:
        if reading.is_mobile is is_mobile:
            return reading
    return readings[0] if readings else None


def run(coro):
    """Synchronous entry point for callers that are not already async.

    Runs on a loop that can spawn subprocesses. See `run_subprocess_safe`.
    """
    return run_subprocess_safe(coro)


def run_subprocess_safe(coro):
    """Run `coro` to completion on a loop that supports subprocesses.

    Playwright starts its driver as a child process, which on Windows is only
    implemented by ProactorEventLoop. The default Windows policy is already a
    proactor, but anything that swaps in a selector policy -- an embedding
    host, a test harness, or a server started under one -- makes Playwright
    fail with a bare `NotImplementedError` from
    `asyncio.create_subprocess_exec`, well away from the real cause.

    A fresh ProactorEventLoop is used directly rather than mutating global
    state with `asyncio.set_event_loop_policy`, so concurrent callers are
    unaffected. If another loop is already running in this thread the caller
    is inside async code and should await the coroutine instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:  # pragma: no cover - guards misuse, not a supported path
        raise RuntimeError(
            "run_subprocess_safe() cannot be called from a running event loop; "
            "await the coroutine directly instead."
        )

    if sys.platform != "win32":
        return asyncio.run(coro)

    loop = asyncio.ProactorEventLoop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
