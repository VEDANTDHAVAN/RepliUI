"""Planner tests with the AI gateway stubbed out.

The planner must turn a WebsiteSpec into a GenerationPlan without ever calling a
real model: the fallback path is exercised when the gateway is unconfigured, and
the parse/repair path is exercised with a canned response.
"""

from __future__ import annotations

import json

import pytest

from app.models.schemas import (
    AssetSpec,
    NavigationSpec,
    SectionSpec,
    ThemeSpec,
    TypographySpec,
    WebsiteSpec,
)
from app.planners import build_fallback_plan
from app.planners.parsing import extract_json, parse_plan, repair_and_parse


def _spec() -> WebsiteSpec:
    return WebsiteSpec(
        url="https://example.com",
        title="Example Domain",
        headings=["Example Domain", "Pricing"],
        navigation=[NavigationSpec(label="Home", href="/")],
        sections=[
            SectionSpec(
                name="hero",
                tag="section",
                heading="Example Domain",
                section_type="hero",
                order=0,
            ),
            SectionSpec(
                name="pricing",
                tag="section",
                heading="Pricing",
                section_type="card grid",
                order=1,
            ),
        ],
        theme_tokens=ThemeSpec(
            primary="#2563eb",
            secondary="#334155",
            background="#ffffff",
            surface="#f1f5f9",
            text="#0f172a",
            muted_text="#475569",
            border="#e2e8f0",
            accent="#2563eb",
        ),
        typography=TypographySpec(
            families=["Inter"],
            sizes=["16px", "24px"],
            weights=["400", "700"],
            heading_sizes={"h1": 24, "h2": 20},
            body_size=16,
        ),
        assets=[AssetSpec(source_url="https://example.com/logo.png", kind="image", section_index=0)],
    )


def test_fallback_plan_is_complete_and_deterministic():
    plan = build_fallback_plan(_spec(), source="fallback")
    assert plan.source == "fallback"
    assert plan.section_order == [0, 1]
    assert [component.name for component in plan.components] == ["HeroSection", "CardGrid1"]
    assert plan.theme.primary == "#2563eb"
    assert plan.theme.border == "#e2e8f0"
    assert plan.typography.heading_family == "Inter"
    assert plan.pages[0].path == "/"
    assert plan.pages[0].section_order == [0, 1]
    assert plan.implementation_notes


def test_fallback_plan_includes_detected_assets():
    plan = build_fallback_plan(_spec())
    assert plan.assets
    assert plan.assets[0].source_url == "https://example.com/logo.png"


def test_fallback_plan_warns_when_a_section_type_is_unknown():
    spec = _spec()
    spec.sections[0].section_type = "mystery band"
    plan = build_fallback_plan(spec)
    assert any("mystery band" in warning for warning in plan.warnings)


def test_parse_plan_accepts_a_clean_json_envelope():
    raw = json.dumps(
        {
            "project_structure": ["app/layout.tsx", "app/page.tsx"],
            "pages": [{"path": "/", "title": "Example Domain", "section_order": [0]}],
            "components": [
                {"name": "HeroSection", "kind": "component", "role": "hero", "source_section_indexes": [0]}
            ],
            "section_order": [0],
            "section_roles": {"0": "hero"},
            "reusable_components": ["HeroSection"],
            "theme": {"primary": "#2563eb"},
            "typography": {"heading_family": "Inter"},
            "layout_strategy": "stacked",
            "responsive_strategy": "fluid",
            "navigation_behavior": "expanded",
            "assets": [],
            "implementation_notes": ["ok"],
        }
    )
    plan = parse_plan(raw)
    assert plan.components[0].name == "HeroSection"
    assert plan.pages[0].path == "/"


def test_extract_json_strips_a_code_fence():
    raw = "```json\n" + json.dumps({"project_structure": ["app/page.tsx"]}) + "\n```"
    assert json.loads(extract_json(raw))["project_structure"] == ["app/page.tsx"]


def test_extract_json_strips_prose_around_the_json():
    raw = "Here is the plan:\n" + json.dumps({"project_structure": ["app/page.tsx"]}) + "\nThanks."
    assert json.loads(extract_json(raw))["project_structure"] == ["app/page.tsx"]


def test_extract_json_raises_on_garbage():
    with pytest.raises(Exception):
        extract_json("not json at all, just prose")


def test_parse_plan_falls_back_when_the_model_returns_garbage():
    with pytest.raises(Exception):
        parse_plan("totally not a plan")


def test_repair_and_parse_recovers_a_canned_response():
    raw = "```json\n" + json.dumps({
        "project_structure": ["app/page.tsx"],
        "pages": [{"path": "/", "title": "Example Domain", "section_order": [0]}],
        "components": [],
        "section_order": [0],
        "section_roles": {"0": "hero"},
        "reusable_components": [],
        "theme": {},
        "typography": {},
        "layout_strategy": "stacked",
        "responsive_strategy": "fluid",
        "navigation_behavior": "expanded",
        "assets": [],
        "implementation_notes": ["ok"],
    }) + "\n```"
    plan = repair_and_parse(raw)
    assert plan.pages[0].path == "/"


def test_fallback_plan_handles_a_section_with_no_layout():
    spec = _spec()
    spec.sections[0].layout = None
    plan = build_fallback_plan(spec)
    assert plan.components[0].name == "HeroSection"


def test_fallback_plan_handles_empty_sections():
    spec = _spec()
    spec.sections = []
    plan = build_fallback_plan(spec)
    assert plan.section_order == []
    assert plan.components == []


def test_fallback_plan_handles_no_responsive_block():
    spec = _spec()
    spec.responsive = None
    plan = build_fallback_plan(spec)
    assert "single-column" in plan.responsive_strategy.lower() or plan.responsive_strategy