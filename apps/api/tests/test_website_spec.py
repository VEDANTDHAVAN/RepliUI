"""Validation rules for the normalized spec models.

The analyzer is deliberately permissive: it must be able to persist a partial
extraction rather than crash a run. These tests pin the few invariants a
downstream generator relies on.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    AssetSpec,
    ColorSpec,
    ComponentSpec,
    GenerationPlan,
    NavigationSpec,
    PlannedComponent,
    PlannedPage,
    PlannedTheme,
    ResponsiveSpec,
    ScreenshotSpec,
    SectionSpec,
    SpacingSpec,
    ThemeSpec,
    TypographySpec,
    VisualSpec,
    WebsiteSpec,
)


def test_minimal_spec_is_valid():
    spec = WebsiteSpec(url="https://example.com")
    assert spec.title == "Untitled website"
    assert spec.sections == []
    assert spec.partial is False
    assert spec.warnings == []


def test_spec_normalises_url_and_tracks_partial_state():
    spec = WebsiteSpec(url="https://example.com", partial=True, warnings=["no title"])
    assert str(spec.url).rstrip("/") == "https://example.com"
    assert spec.partial is True
    assert spec.warnings == ["no title"]


def test_spec_rejects_a_non_http_url():
    with pytest.raises(ValidationError):
        WebsiteSpec(url="not-a-url")


def test_spec_never_carries_raw_html():
    # The LLM receives a normalized spec; raw markup must not be a field.
    assert "html" not in WebsiteSpec.model_fields
    assert "outer_html" not in WebsiteSpec.model_fields


def test_section_spec_infers_metadata_without_a_fixed_name():
    section = SectionSpec(
        name="band-3",
        section_type="feature-band",
        order=2,
        heading="Why teams switch",
        text="A short summary of the band.",
        layout={"display": "grid", "columns": 3},
        background="#f8fafc",
        spacing=SpacingSpec(md=32, unit=16),
        width=1440,
        height=420,
    )
    assert section.section_type == "feature-band"
    assert section.order == 2
    assert section.layout is not None and section.layout.columns == 3
    assert section.spacing.md == 32


def test_section_spec_defaults_are_generatable():
    section = SectionSpec(name="main")
    assert section.order == 0
    assert section.heading is None
    assert section.child_components == []
    assert section.image_urls == []
    assert section.component_hint == "content"


def test_asset_spec_records_source_metadata():
    asset = AssetSpec(
        source_url="https://cdn.example.com/hero.png",
        alt="Product hero",
        kind="image",
        width=1600,
        height=900,
        media_type="image/png",
        context="section:0",
    )
    assert asset.kind == "image"
    assert asset.width == 1600
    assert asset.alt == "Product hero"
    assert asset.section_index is None


def test_asset_spec_rejects_an_unknown_kind():
    with pytest.raises(ValidationError):
        AssetSpec(source_url="https://example.com/x", kind="spreadsheet")


def test_typography_spec_uses_representative_values():
    typography = TypographySpec(
        families=["Inter", "Arial"],
        sizes=["14px", "16px", "48px"],
        weights=["400", "600"],
        heading_sizes={"h1": 48, "h2": 24},
        body_size=16,
        line_heights=["1.5"],
    )
    assert typography.families[0] == "Inter"
    assert typography.body_size == 16
    assert typography.heading_sizes["h1"] >= int(typography.sizes[-1][:-2])


def test_color_spec_carries_name_value_and_usage():
    color = ColorSpec(name="primary", value="#0F172A", usage="text")
    assert color.value == "#0F172A"
    assert color.usage == "text"


def test_component_spec_tracks_observed_repeats():
    component = ComponentSpec(
        name="card",
        kind="card",
        count=6,
        role="repeated-content",
        sample_text=["First card", "Second card"],
        section_indexes=[1],
    )
    assert component.count == 6
    assert component.section_indexes == [1]
    assert component.sample_text == ["First card", "Second card"]


def test_theme_spec_defaults_to_empty_tokens():
    theme = ThemeSpec()
    assert theme.primary is None
    assert theme.background is None


def test_visual_spec_and_spacing_spec_shapes():
    visual = VisualSpec(
        radii=[12, 8],
        border_widths=[1],
        shadows=["0 1px 2px rgba(0,0,0,0.05)"],
        max_width=1200,
    )
    spacing = SpacingSpec(xs=4, sm=8, md=16, lg=32, xl=64, unit=16)
    assert visual.max_width == 1200
    assert visual.radii == [12, 8]
    assert spacing.xl == 64


def test_responsive_spec_captures_both_viewports():
    desktop = ResponsiveSpec(
        breakpoint="desktop",
        width=1440,
        height=900,
        is_mobile=False,
        navigation_items=5,
        max_columns=4,
    )
    mobile = ResponsiveSpec(
        breakpoint="mobile",
        width=390,
        height=844,
        is_mobile=True,
        navigation_items=0,
        max_columns=1,
        notes=["navigation collapses"],
    )
    assert desktop.max_columns == 4
    assert desktop.is_mobile is False
    assert mobile.is_mobile is True
    assert mobile.max_columns == 1
    assert "navigation collapses" in mobile.notes


def test_screenshot_spec_keeps_dimensions_and_path():
    shot = ScreenshotSpec(
        path="storage/screenshots/demo/desktop.png",
        label="desktop",
        width=1440,
        height=900,
        viewport_width=1440,
        viewport_height=900,
        device="desktop",
        full_page=True,
    )
    assert shot.label == "desktop"
    assert shot.width == 1440
    assert shot.full_page is True


def test_navigation_spec_flags_external_links():
    internal = NavigationSpec(label="Home", href="/")
    external = NavigationSpec(label="GitHub", href="https://github.com/x", is_external=True)
    assert internal.is_external is False
    assert external.is_external is True


def test_generation_plan_accepts_a_minimal_ai_response():
    plan = GenerationPlan(
        project_structure=["app/page.tsx"],
        pages=[PlannedPage(path="/", role="landing")],
        components=[PlannedComponent(name="Hero", kind="section")],
        theme=PlannedTheme(primary="#0f172a"),
        framework="next",
        source="ai",
    )
    assert plan.section_order == []
    assert plan.pages[0].path == "/"


def test_generation_plan_source_is_constrained():
    with pytest.raises(ValidationError):
        GenerationPlan(source="hallucinated")
