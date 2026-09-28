"""Section, component, asset and responsive detection.

Section detection is geometric, so these tests build explicit box-model
fixtures. Classification is asserted for the structural signals it actually
uses, never for a particular website's section names.
"""

from __future__ import annotations

import pytest
from support import group, node, reading

from app.analyzers import assets, components, responsive, sections
from app.models.schemas import ComponentSpec


def _band(tag, y, height, **kwargs):
    return node(
        tag=tag,
        x=0,
        y=y,
        width=1440,
        height=height,
        child_elements=kwargs.pop("child_elements", 3),
        depth=1,
        **kwargs,
    )


def _band(tag, y, height, **kwargs):
    """A full-width content band with room for descendants."""
    return node(
        tag=tag,
        x=0,
        y=y,
        width=1440,
        height=height,
        child_elements=kwargs.pop("child_elements", 3),
        depth=1,
        **kwargs,
    )


def test_detects_vertically_stacked_bands_and_orders_them():
    nodes = [
        node(tag="header", x=0, y=0, width=1440, height=72, child_elements=2),
        node(tag="a", x=40, y=24, width=120, height=24, depth=3, href="/a", text="A"),
        node(tag="a", x=200, y=24, width=120, height=24, depth=3, href="/b", text="B"),
        _band("section", y=72, height=400, class_name="hero"),
        node(tag="h1", x=40, y=140, width=800, height=60, depth=3, text="Build faster"),
        node(tag="p", x=40, y=220, width=700, height=50, depth=3, text="Some copy"),
        _band("section", y=472, height=300, class_name="features"),
        node(tag="h2", x=40, y=520, width=500, height=40, depth=3, text="Features"),
        node(tag="p", x=40, y=560, width=500, height=30, depth=3, text="Details"),
        node(tag="footer", x=0, y=772, width=1440, height=128, child_elements=1),
        node(tag="p", x=40, y=820, width=600, height=20, depth=3, text="Copyright"),
    ]
    found = sections.detect_sections(reading(nodes), {})

    assert len(found) >= 3
    assert [item.order for item in found] == list(range(len(found)))
    tops = [item.top for item in found if item.top is not None]
    assert tops == sorted(tops), "sections must be in document order"


def test_header_and_footer_are_inferred_from_geometry():
    nodes = [
        node(tag="header", x=0, y=0, width=1440, height=96, child_elements=2),
        node(tag="a", x=40, y=24, width=120, height=24, depth=3, href="/a", text="A"),
        node(tag="a", x=200, y=24, width=120, height=24, depth=3, href="/b", text="B"),
        node(tag="a", x=360, y=24, width=120, height=24, depth=3, href="/c", text="C"),
        node(tag="footer", x=0, y=1800, width=1440, height=120, child_elements=1),
        node(tag="p", x=40, y=1850, width=600, height=20, depth=3, text="Copyright"),
        node(tag="a", x=700, y=1850, width=80, height=20, depth=3, href="/tos", text="Terms"),
    ]
    found = sections.detect_sections(reading(nodes, document_height=1920), {})
    kinds = {item.section_type for item in found}
    assert "navigation" in kinds
    assert "footer" in kinds


def test_nested_wrappers_collapse_to_one_band():
    # An outer <main> and the <section> inside it describe the same area.
    nodes = [
        node(tag="main", x=0, y=0, width=1440, height=500, child_elements=2),
        _band("section", y=0, height=500, class_name="inner"),
        node(tag="h2", x=40, y=40, width=500, height=40, depth=3, text="Only one band"),
        node(tag="p", x=40, y=100, width=500, height=30, depth=3, text="Body copy"),
    ]
    found = sections.detect_sections(reading(nodes), {})
    assert len(found) == 1


def test_section_carries_heading_layout_and_dimensions():
    nodes = [
        _band("section", y=0, height=420, class_name="band"),
        node(tag="h1", x=40, y=120, width=800, height=60, depth=3, text="Ship it"),
        node(tag="p", x=40, y=200, width=700, height=40, depth=3, text="Body copy"),
    ]
    section = sections.detect_sections(reading(nodes), {})[0]
    assert section.heading == "Ship it"
    assert section.width == 1440
    assert section.height == 420
    assert section.top == 0
    assert section.layout is not None
    assert "heading" in section.child_components
    assert 0.0 < section.confidence <= 1.0


def test_grid_sections_report_their_column_count():
    nodes = [
        node(
            tag="section",
            x=0,
            y=0,
            width=1440,
            height=400,
            child_elements=3,
            styles={"display": "grid", "grid-template-columns": "repeat(3, 1fr)", "gap": "24px"},
        ),
        node(tag="h2", x=40, y=40, width=500, height=40, depth=3, text="Grid"),
        node(tag="p", x=40, y=100, width=500, height=30, depth=3, text="Copy"),
    ]
    section = sections.detect_sections(reading(nodes), {})[0]
    assert section.layout is not None
    assert section.layout.columns == 3
    assert section.layout.gap == 24


def test_repeated_cards_are_inferred_from_observed_repetition():
    nodes = [
        _band("section", y=0, height=500, class_name="cards", selector="section.cards"),
        node(tag="h2", x=40, y=40, width=500, height=40, depth=3, text="Plans"),
        node(tag="p", x=40, y=100, width=500, height=30, depth=3, text="Copy"),
    ]
    index = {
        "cards": [
            ComponentSpec(
                name="cards",
                kind="card",
                count=4,
                selectors=["section.cards"],
                section_indexes=[0],
            )
        ]
    }
    section = sections.detect_sections(reading(nodes), index)[0]
    assert section.section_type == "card grid"
    # The repeated group is reported under its own component name.
    assert "cards" in section.child_components


def test_form_sections_are_detected_without_a_fixed_name():
    nodes = [
        _band("section", y=0, height=400, class_name="signup"),
        node(tag="form", x=40, y=60, width=600, height=240, depth=3, form={"action": "/join", "method": "post", "fields": ["email"]}),
        node(tag="p", x=40, y=320, width=400, height=20, depth=3, text="Copy"),
    ]
    section = sections.detect_sections(reading(nodes), {})[0]
    assert section.section_type == "form"
    assert "form" in section.child_components


def test_sections_are_never_named_after_a_fixed_template():
    # A band with no heading and no class falls back to a generic name.
    nodes = [
        _band("div", y=0, height=300),
        node(tag="p", x=20, y=40, width=400, height=30, depth=3, text="Copy"),
        node(tag="p", x=20, y=90, width=400, height=30, depth=3, text="More copy"),
    ]
    found = sections.detect_sections(reading(nodes), {})
    assert found
    assert "hero" not in {item.name.lower() for item in found}
    assert "pricing" not in {item.name.lower() for item in found}


def test_component_detection_groups_repeated_nodes():
    layout = reading(
        [node(width=1440)],
        groups=[group(key="div.card", count=6, tag="div", parent_display="grid", parent_columns=3)],
    )
    found = components.detect_components(layout.layout, layout.nodes, 1440)
    assert found
    assert any(item.count == 6 for item in found)
    assert any(item.kind == "card" for item in found)


def test_single_occurrence_is_not_a_component():
    layout = reading([node(width=1440)], groups=[group(key="div.thing", count=1)])
    found = components.detect_components(layout.layout, layout.nodes, 1440)
    assert not any(item.count == 1 for item in found)


def test_component_index_groups_by_name():
    specs = [
        ComponentSpec(name="card", kind="card", count=4),
        ComponentSpec(name="button", kind="button", count=12),
    ]
    index = components.component_index(specs)
    assert "card" in index
    assert index["button"][0].count == 12


def test_assets_resolve_relative_urls_and_classify_kinds():
    nodes = [
        node(tag="img", image={"src": "/static/hero.png", "alt": "Hero", "natural_width": 1600, "natural_height": 900}),
        node(tag="img", image={"src": "https://cdn.example.com/logo.svg", "alt": "Logo"}),
        node(tag="video", child_elements=0),
    ]
    found = assets.extract_assets(nodes, "https://example.com/page", limit=20)
    by_url = {item.source_url: item for item in found}

    hero = by_url["https://example.com/static/hero.png"]
    assert hero.kind == "image"
    assert hero.alt == "Hero"
    assert hero.width == 1600
    assert by_url["https://cdn.example.com/logo.svg"].kind == "svg"


def test_assets_are_deduplicated_and_bounded():
    nodes = [node(tag="img", image={"src": f"/img/{i}.png"}) for i in range(60)]
    found = assets.extract_assets(nodes, "https://example.com", limit=10)
    assert len(found) <= 10
    assert len({item.source_url for item in found}) == len(found)


def test_data_uri_assets_are_summarised_not_inlined():
    # Inline data is described by kind but never carried verbatim into the spec,
    # so a multi-megabyte base64 payload can never reach the model.
    nodes = [node(tag="img", image={"src": "data:image/gif;base64,R0lGODlhAQABAAAAACw="})]
    found = assets.extract_assets(nodes, "https://example.com")
    assert found
    assert all("base64" not in item.source_url for item in found)
    assert all(not item.source_url.startswith("data:image/gif;base64") for item in found)


def test_background_image_assets_are_discovered():
    nodes = [
        node(tag="div", styles={"background-image": "url('https://cdn.example.com/bg.jpg')"}),
    ]
    found = assets.extract_assets(nodes, "https://example.com")
    assert any("bg.jpg" in item.source_url for item in found)


def test_responsive_compare_reports_column_collapse():
    desktop = reading(
        [node(tag="div", x=0, y=0, width=1440, height=200, child_elements=3, styles={"display": "grid", "grid-template-columns": "repeat(3, 1fr)"})],
        width=1440,
        height=900,
    )
    mobile = reading(
        [node(tag="div", x=0, y=0, width=390, height=400, child_elements=3, styles={"display": "block"})],
        width=390,
        height=844,
        is_mobile=True,
    )
    # The spec describes what the page does at mobile width, measured on mobile.
    spec = responsive.compare(desktop, mobile)
    assert spec.is_mobile is True
    assert spec.breakpoint == "mobile"
    assert spec.width == 390
    assert spec.max_columns == 1
    assert any("collapse" in note for note in spec.notes)
    assert any("3 columns" in note for note in spec.notes)


def test_responsive_rules_cover_both_viewports():
    desktop = reading([node(tag="div", width=1440, height=200, child_elements=1)], width=1440, height=900)
    mobile = reading([node(tag="div", width=390, height=200, child_elements=1)], width=390, height=844, is_mobile=True)
    rules = responsive.viewport_rules([desktop, mobile])
    assert {rule.breakpoint for rule in rules} >= {"desktop", "mobile"}
    assert any(rule.is_mobile for rule in rules)


def test_responsive_summarize_reports_measured_geometry():
    summary = responsive.summarize(
        reading([node(tag="div", x=0, y=0, width=1440, height=300, child_elements=1, styles={"display": "grid", "grid-template-columns": "repeat(4, 1fr)"})])
    )
    assert summary["max_columns"] == 4
    assert summary["content_width"] == 1440


def test_responsive_viewport_rules_use_semantic_breakpoint_names():
    desktop = reading([node(tag="div", width=1440, height=200, child_elements=1)], width=1440, height=900)
    mobile = reading([node(tag="div", width=390, height=200, child_elements=1)], width=390, height=844, is_mobile=True)
    rules = responsive.viewport_rules([desktop, mobile])
    assert {rule.breakpoint for rule in rules} == {"desktop", "mobile"}
    assert [rule.width for rule in rules] == [1440, 390]
