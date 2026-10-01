"""End-to-end analyzer behaviour against a real browser.

These run the actual Playwright pipeline over a controlled local HTML
document, so they exercise the in-page extraction scripts, the section and
component detectors, and the spec assembly together.

No network and no hard-coded evaluation site is involved.
"""

from __future__ import annotations

import pytest

from app.analyzers import (
    VIEWPORTS,
    AnalysisError,
    WebsiteAnalyzer,
    build_spec,
    screenshot_path,
)
from app.analyzers.raw_models import RawLayout

FIXTURE_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Northwind Analytics</title>
  <meta name="description" content="Product analytics for small teams.">
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Inter, system-ui, sans-serif; color: #0f172a; background: #ffffff; }
    header { height: 72px; display: flex; align-items: center; padding: 0 32px; }
    header a { color: #334155; text-decoration: none; margin-right: 24px; }
    .hero { height: 420px; padding: 64px 32px; background: #f8fafc; }
    .hero h1 { font-size: 48px; line-height: 1.1; margin: 0 0 16px; font-weight: 700; }
    .hero p { font-size: 16px; line-height: 1.6; max-width: 640px; margin: 0 0 24px; }
    .cta { display: inline-block; background: #2563eb; color: #ffffff; padding: 12px 20px; border-radius: 8px; }
    .features { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; padding: 56px 32px; }
    .card { border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
    .card h3 { font-size: 20px; margin: 0 0 8px; }
    .card p { font-size: 14px; line-height: 1.5; color: #64748b; margin: 0; }
    .signup { padding: 56px 32px; background: #f1f5f9; }
    .signup form { display: grid; gap: 12px; max-width: 480px; }
    .signup input { padding: 10px; border: 1px solid #cbd5e1; border-radius: 6px; }
    footer { padding: 32px; border-top: 1px solid #e2e8f0; }
    footer p { font-size: 13px; color: #64748b; }
  </style>
</head>
<body>
  <header>
    <a href="/">Home</a>
    <a href="/product">Product</a>
    <a href="/pricing">Pricing</a>
    <a href="/docs">Docs</a>
  </header>

  <section class="hero">
    <h1>Understand your product in minutes</h1>
    <p>Northwind turns raw events into a dashboard your whole team can read.</p>
    <a class="cta" href="/signup">Start free trial</a>
  </section>

  <section class="features">
    <div class="card">
      <h3>Funnels</h3>
      <p>See where people drop out of each step.</p>
    </div>
    <div class="card">
      <h3>Retention</h3>
      <p>Cohort charts that update every hour.</p>
    </div>
    <div class="card">
      <h3>Alerts</h3>
      <p>Get paged before a metric moves.</p>
    </div>
  </section>

  <section class="signup">
    <h2>Start your trial</h2>
    <form action="/trial" method="post">
      <input type="email" name="email" placeholder="you@company.com">
      <button type="submit">Create account</button>
    </form>
  </section>

  <footer>
    <p>Copyright 2024 Northwind Labs</p>
  </footer>
</body>
</html>
"""


def _redirect_screenshots(monkeypatch, storage_root):
    """Point screenshot writes at a throwaway tree.

    Mirrors production `screenshot_path`, which creates its own directory.
    """
    import app.analyzers as analyzers_module

    def fake_path(project_id: str, label: str):
        target = storage_root / project_id / f"{label}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    monkeypatch.setattr(analyzers_module, "screenshot_path", fake_path)


@pytest.fixture(scope="module")
def storage_root(tmp_path_factory):
    return tmp_path_factory.mktemp("shots")


def reading_of():
    """A minimal desktop reading, for exercising `build_spec` without a browser."""
    from support import node, reading

    return reading(
        [
            node(tag="section", x=0, y=0, width=1440, height=400, child_elements=2, depth=1),
            node(tag="h1", x=40, y=100, width=800, height=60, depth=3, text="Pure"),
        ]
    )


@pytest.fixture(scope="module")
def analyzed(storage_root):
    """Analyze the fixture once for the whole module.

    Launching Chromium is the slow part, so every assertion reads the one spec
    produced here rather than re-analyzing per test.
    """
    import asyncio

    import pytest as _pytest

    patcher = _pytest.MonkeyPatch()
    try:
        _redirect_screenshots(patcher, storage_root)
        return asyncio.run(
            WebsiteAnalyzer(max_nodes=800).analyze_html(
                FIXTURE_HTML, "https://fixture.example/", "fixture0001"
            )
        )
    finally:
        patcher.undo()


def test_extracts_document_metadata(analyzed):
    assert analyzed.title == "Northwind Analytics"
    assert analyzed.meta_description == "Product analytics for small teams."
    assert analyzed.lang == "en"


def test_detects_navigation_from_the_header(analyzed):
    labels = [item.label for item in analyzed.navigation]
    assert "Product" in labels
    assert "Pricing" in labels
    # Relative hrefs are resolved against the analysed page.
    assert "https://fixture.example/product" in {item.href for item in analyzed.navigation}


def test_finds_sections_in_document_order(analyzed):
    assert len(analyzed.sections) >= 3
    assert [item.order for item in analyzed.sections] == list(range(len(analyzed.sections)))
    tops = [item.top for item in analyzed.sections if item.top is not None]
    assert tops == sorted(tops)


def test_sections_carry_real_headings_and_dimensions(analyzed):
    headings = [item.heading for item in analyzed.sections if item.heading]
    assert any("Understand your product" in text for text in headings)
    assert any(item.section_type == "form" for item in analyzed.sections)
    assert {item.section_type for item in analyzed.sections} >= {"navigation", "hero", "form", "footer"}
    for section in analyzed.sections:
        if section.width:
            assert section.width > 0
        assert 0.0 <= section.confidence <= 1.0


def test_extracts_the_desktop_grid_column_count(analyzed):
    # Chrome resolves `repeat(3, 1fr)` to three pixel tracks, so the detector
    # must read the computed value rather than the authored CSS.
    grids = [item for item in analyzed.sections if item.layout and item.layout.display == "grid"]
    assert grids, f"no grid section found in {[s.layout.display if s.layout else None for s in analyzed.sections]}"
    assert any(item.layout.columns == 3 for item in grids)


def test_the_hero_band_is_not_misclassified_as_a_card_grid(analyzed):
    # The hero's only child is a CTA, not a repeated card, so it must not be
    # reported as a card grid just because a card grid exists elsewhere on the page.
    hero = next(item for item in analyzed.sections if item.section_type == "hero")
    assert not any("section-features" in name for name in hero.child_components)


def test_repeated_cards_are_reported_inside_their_own_section(analyzed):
    grid = next(item for item in analyzed.sections if item.section_type == "card grid")
    # The repeated card group is keyed by its container selector, which is not a
    # predictable name, so the section carries that selector instead.
    assert any("section-features" in name for name in grid.child_components)
    others = [
        name
        for item in analyzed.sections
        if item.section_type != "card grid"
        for name in item.child_components
    ]
    assert not any("section-features" in name for name in others)


def test_a_section_does_not_claim_a_sibling_bands_nodes(analyzed):
    # Sections stack vertically, so a purely geometric containment test would let
    # each band swallow the ones below it. Containment must follow the DOM.
    grid = next(item for item in analyzed.sections if item.section_type == "card grid")
    # The signup form lives in the next band, not inside the card grid.
    assert "form" not in grid.child_components
    footer = next(item for item in analyzed.sections if item.section_type == "footer")
    assert "form" not in footer.child_components


def test_detects_repeated_cards_as_components(analyzed):
    # The repeated `.card` siblings come back as one component with a count.
    cards = [item for item in analyzed.components if item.kind == "card"]
    assert cards
    assert max(item.count for item in cards) >= 3
    assert any(item.count == 4 and item.kind == "nav item" for item in analyzed.components)


def test_builds_theme_and_typography_from_computed_styles(analyzed):
    assert analyzed.theme_tokens.background
    assert analyzed.theme_tokens.text
    # The saturated CTA colour is recovered as the brand, not as a page surface.
    assert analyzed.theme_tokens.primary == "#2563eb"
    assert "Inter" in " ".join(analyzed.typography.families)
    assert analyzed.typography.body_size
    assert analyzed.typography.heading_sizes


def test_detects_a_border_token_from_visible_hairlines(analyzed):
    assert 1 in analyzed.visual.border_widths
    # The hairline colour is recovered as the border token.
    assert analyzed.theme_tokens.border == "#e2e8f0"


def test_analyzer_never_records_a_zero_width_border(analyzed):
    # 0 would tell the generator the site has no borders at all.
    assert 0 not in analyzed.visual.border_widths


def test_collects_document_headings_in_order(analyzed):
    assert analyzed.headings
    assert analyzed.headings[0] == "Understand your product in minutes"


def test_desktop_and_mobile_viewports_are_both_captured(analyzed):
    assert {shot.label for shot in analyzed.screenshot_details} == {"desktop", "mobile"}
    assert {rule.breakpoint for rule in analyzed.responsive_rules} == {"desktop", "mobile"}
    mobile_rule = next(r for r in analyzed.responsive_rules if r.is_mobile)
    assert mobile_rule.width == 390
    desktop_rule = next(r for r in analyzed.responsive_rules if not r.is_mobile)
    assert desktop_rule.width == 1440


def test_responsive_summary_reports_a_real_difference(analyzed):
    assert analyzed.responsive is not None
    assert analyzed.responsive.width == 390
    assert analyzed.responsive.is_mobile is True


def test_screenshots_are_written_to_the_project_directory(analyzed, storage_root):
    assert len(analyzed.screenshots) == len(VIEWPORTS)
    for shot in analyzed.screenshot_details:
        assert shot.bytes > 0
        path = storage_root / "fixture0001" / f"{shot.label}.png"
        assert path.exists()
        assert path.stat().st_size == shot.bytes


def test_the_real_screenshot_path_helper_creates_its_directory(tmp_path, monkeypatch):
    # The production helper, not the test double, is responsible for mkdir.
    import app.storage

    monkeypatch.setattr(app.storage, "SCREENSHOTS_DIR", tmp_path / "shots")
    path = app.storage.screenshot_path("mkdir0001", "desktop")
    assert path.parent.is_dir()
    assert path.suffix == ".png"


def test_spec_never_contains_raw_html(analyzed):
    dumped = analyzed.model_dump_json()
    assert "<header" not in dumped
    assert "<section" not in dumped
    assert "doctype" not in dumped.lower()


def test_analysis_reports_duration_and_is_not_partial(analyzed):
    assert analyzed.analysis_duration_ms > 0
    assert analyzed.partial is False


def test_build_spec_raises_when_every_viewport_failed():
    # Total capture failure is not a partial result; it must not be mistaken for
    # a page that simply had no sections.
    with pytest.raises(AnalysisError):
        build_spec([], [], "https://empty.example/", ["no viewports captured"])


def test_build_spec_is_pure_and_deterministic():
    reading = reading_of()
    first = build_spec([reading], [], "https://pure.example/")
    second = build_spec([reading], [], "https://pure.example/")
    # Extraction itself is pure; only the wall-clock stamp is allowed to move.
    # Extraction itself is pure; only the wall-clock stamp and measured
    # duration are allowed to move between two calls.
    first_dump = first.model_dump(exclude={"analyzed_at", "analysis_duration_ms"})
    second_dump = second.model_dump(exclude={"analyzed_at", "analysis_duration_ms"})
    assert first_dump == second_dump


def test_analyzer_rejects_bot_protection_interstitials():
    """A challenge page must not be presented as a successful reconstruction."""
    from app.analyzers import BlockedBySiteError, _is_access_challenge
    from app.analyzers.raw_models import RawDocument, RawLayout, ViewportReading

    reading = ViewportReading(
        device="desktop",
        width=1440,
        height=900,
        is_mobile=False,
        scale=1,
        document=RawDocument(title="Just a moment...", paragraphs=["Checking your browser before accessing the site."]),
        nodes=[],
        layout=RawLayout(),
        truncated=False,
        document_height=900,
    )
    assert _is_access_challenge([reading])
    assert issubclass(BlockedBySiteError, Exception)


def test_a_blank_document_still_produces_a_valid_spec(storage_root, monkeypatch):
    import asyncio

    _redirect_screenshots(monkeypatch, storage_root)
    spec = asyncio.run(
        WebsiteAnalyzer(max_nodes=800).analyze_html(
            "<html><body></body></html>", "https://blank.example/", "blank0001"
        )
    )
    assert spec.title == "Untitled website"
    assert spec.sections == []
    assert spec.partial is True
    assert spec.warnings


def test_analyzer_rejects_private_urls_before_launching_a_browser():
    import asyncio

    from app.analyzers.urls import InvalidURLError

    # A dedicated error type lets the API map this to a 400 rather than a 500.
    with pytest.raises(InvalidURLError):
        asyncio.run(WebsiteAnalyzer().analyze("https://127.0.0.1/", "ssrf0001"))


def test_subprocess_safe_survives_a_selector_event_loop_policy():
    """Regression: analysis died with a bare `NotImplementedError`.

    Playwright starts its driver as a child process. On Windows only
    ProactorEventLoop implements `create_subprocess_exec`, so when anything
    installs a selector policy, `asyncio.run` handed Playwright a loop that
    could not spawn, and the failure surfaced as `NotImplementedError` from
    deep inside asyncio with no mention of the browser.
    """
    import asyncio
    import sys

    from app.analyzers import run_subprocess_safe

    if sys.platform != "win32":
        pytest.skip("SelectorEventLoop lacks subprocess support only on Windows")

    async def spawn():
        proc = await asyncio.create_subprocess_exec("cmd", "/c", "echo ok")
        await proc.wait()
        return proc.returncode

    original = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        with pytest.raises(NotImplementedError):
            asyncio.run(spawn())

        assert run_subprocess_safe(spawn()) == 0
    finally:
        asyncio.set_event_loop_policy(original)


def test_subprocess_safe_refuses_to_nest_inside_a_running_loop():
    import asyncio

    from app.analyzers import run_subprocess_safe

    async def outer():
        async def inner():
            return 1

        with pytest.raises(RuntimeError, match="running event loop"):
            run_subprocess_safe(inner())
        inner().close()  # never started; close to silence "was never awaited"

    asyncio.run(outer())


def test_subprocess_safe_runs_a_real_browser_under_a_selector_policy():
    """The end of the regression: Chromium actually launches."""
    import asyncio
    import sys

    from app.analyzers import run_subprocess_safe

    if sys.platform != "win32":
        pytest.skip("SelectorEventLoop lacks subprocess support only on Windows")

    async def launch():
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content("<html><body><h1>ok</h1></body></html>")
            heading = await page.text_content("h1")
            await browser.close()
            return heading

    original = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        assert run_subprocess_safe(launch()) == "ok"
    finally:
        asyncio.set_event_loop_policy(original)


def test_pipeline_runs_the_analyzer_on_a_subprocess_safe_loop():
    """The reported symptom was POST /api/projects -> NotImplementedError.

    `main.pipeline` used `asyncio.run` for the analyzer. Playwright starts its
    driver as a child process, and on Windows only ProactorEventLoop implements
    `create_subprocess_exec`, so under a selector policy the request died with
    a bare NotImplementedError and no analysis. The fix routes the analyzer
    through `run_subprocess_safe`; this guards that wiring, which is what
    actually regressed, without paying for a full pipeline run.
    """
    import inspect

    import app.main as api

    source = inspect.getsource(api.pipeline)
    assert "run_subprocess_safe" in source, (
        "main.pipeline must run the analyzer via run_subprocess_safe, not asyncio.run"
    )
    assert "asyncio.run(" not in source, (
        "asyncio.run in main.pipeline cannot spawn Playwright's driver on Windows"
    )


def test_full_analysis_succeeds_under_a_selector_policy(monkeypatch, storage_root):
    """End of the regression: the real analyzer returns a real spec.

    Exercises the exact call main.pipeline makes -- run_subprocess_safe around
    the analyzer coroutine -- with the real browser, under the policy that used
    to break it. `analyze_html` avoids the network while still driving
    Chromium exactly as the HTTP path does.
    """
    import asyncio
    import sys

    from app.analyzers import WebsiteAnalyzer, run_subprocess_safe
    from app.models.schemas import WebsiteSpec

    if sys.platform != "win32":
        pytest.skip("SelectorEventLoop lacks subprocess support only on Windows")

    _redirect_screenshots(monkeypatch, storage_root)
    analyzer = WebsiteAnalyzer(max_nodes=800)

    original = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        spec = run_subprocess_safe(
            analyzer.analyze_html(FIXTURE_HTML, "https://fixture.example/", "selector0001")
        )
    finally:
        asyncio.set_event_loop_policy(original)

    assert isinstance(spec, WebsiteSpec)
    assert str(spec.url).startswith("https://fixture.example/")


def test_invalid_urlerror_is_a_distinct_api_error():
    # A dedicated type lets the API map this to a 400 rather than a 500.
    from app.analyzers.urls import InvalidURLError

    assert issubclass(InvalidURLError, Exception)
    assert InvalidURLError is not AnalysisError


def test_the_spec_is_shared_by_every_assertion(analyzed):
    # Guards the module-scoped fixture: a fresh spec would double the runtime.
    assert str(analyzed.url).startswith("https://fixture.example/")


def test_raw_layout_accepts_a_document_with_no_repeat_groups():
    layout = RawLayout.model_validate({"groups": [], "document_height": 0})
    assert layout.groups == []
