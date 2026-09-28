"""Color, typography and spacing extraction.

All deterministic: no browser, no model.
"""

from __future__ import annotations

import pytest
from support import node

from app.analyzers.colors import (
    build_theme_tokens,
    collect_color_usage,
    contrast_ratio,
    extract_palette,
    luminance,
    parse_color,
    to_hex,
)
from app.analyzers.typography import (
    extract_spacing,
    extract_typography,
    extract_visual,
    node_background,
    node_font_size,
    node_text_color,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("rgb(15, 23, 42)", (15, 23, 42, 1.0)),
        ("rgba(15, 23, 42, 0.5)", (15, 23, 42, 0.5)),
        ("#0f172a", (15, 23, 42, 1.0)),
        ("#fff", (255, 255, 255, 1.0)),
        ("white", (255, 255, 255, 1.0)),
        ("transparent", (255, 255, 255, 0.0)),
        ("inherit", None),
        ("", None),
    ],
)
def test_parse_color_accepts_computed_style_values(raw, expected):
    assert parse_color(raw) == expected


def test_to_hex_drops_alpha():
    assert to_hex((15, 23, 42, 1.0)) == "#0f172a"


def test_luminance_and_contrast_are_ordered():
    black = luminance((0, 0, 0, 1.0))
    white = luminance((255, 255, 255, 1.0))
    assert black < white
    assert contrast_ratio((0, 0, 0, 1.0), (255, 255, 255, 1.0)) > contrast_ratio(
        (0, 0, 0, 1.0), (128, 128, 128, 1.0)
    )


def test_palette_ranks_by_actual_usage():
    nodes = [
        node(styles={"color": "rgb(15, 23, 42)"}),
        node(styles={"background-color": "rgb(15, 23, 42)"}),
        node(styles={"color": "rgb(239, 68, 68)"}),
    ]
    palette = extract_palette(nodes)
    values = [entry.value for entry in palette]
    assert values[0] == "#0f172a"
    assert "#ef4444" in values


def test_palette_is_bounded_and_ignores_invisible_nodes():
    nodes = [node(styles={"color": f"rgb({i}, {i}, {i})"}) for i in range(40)]
    nodes.append(node(visible=False, styles={"color": "rgb(1, 2, 3)"}))
    palette = extract_palette(nodes, limit=5)
    assert len(palette) <= 5


def test_collect_color_usage_counts_repeats():
    nodes = [
        node(styles={"color": "rgb(15, 23, 42)"}),
        node(styles={"color": "rgb(15, 23, 42)"}),
        node(styles={"background-color": "rgb(248, 250, 252)"}),
    ]
    usage = collect_color_usage(nodes)
    assert usage["#0f172a"] == 2
    assert usage["#f8fafc"] == 1


def test_build_theme_tokens_infers_semantic_roles():
    nodes = [
        node(tag="body", styles={"background-color": "rgb(255, 255, 255)"}),
        node(tag="h1", styles={"color": "rgb(15, 23, 42)"}),
        node(tag="p", styles={"color": "rgb(100, 116, 139)"}),
        node(styles={"border-top-color": "rgb(226, 232, 240)", "border-top-width": "1px"}),
        # A brand gradient is the only place the accent hue appears.
        node(
            styles={
                "background-image": (
                    "linear-gradient(90deg, rgb(37, 99, 235), rgb(219, 39, 119))"
                )
            }
        ),
    ]
    theme = build_theme_tokens(nodes, extract_palette(nodes))
    # A `body` background is the page background regardless of its usage rank.
    assert theme.background == "#ffffff"
    assert theme.text == "#0f172a"
    assert theme.border == "#e2e8f0"
    assert theme.accent == "#2563eb"
    assert theme.primary == "#2563eb"


def test_typography_collects_families_and_a_type_scale():
    nodes = [
        node(
            tag="h1",
            styles={
                "font-family": "Inter, sans-serif",
                "font-size": "48px",
                "font-weight": "700",
                "line-height": "1.1",
            },
        ),
        node(
            tag="p",
            styles={
                "font-family": "Inter, sans-serif",
                "font-size": "16px",
                "font-weight": "400",
                "line-height": "1.6",
            },
        ),
    ]
    typography = extract_typography(nodes)
    assert typography.families[0].startswith("Inter")
    # 48px lands in the "display" bucket of the inferred type scale.
    assert typography.heading_sizes.get("display") == 48
    assert typography.body_size == 16
    assert "700" in typography.weights
    assert typography.line_heights


def test_typography_is_empty_rather_than_wrong_for_blank_input():
    typography = extract_typography([])
    assert typography.families == []
    assert typography.body_size is None


def test_node_helpers_read_the_style_map():
    sample = node(
        styles={
            "color": "rgb(15, 23, 42)",
            "background-color": "rgb(248, 250, 252)",
            "font-size": "20px",
        }
    )
    assert node_text_color(sample) == "#0f172a"
    assert node_background(sample) == "#f8fafc"
    assert node_font_size(sample) == 20


def test_node_background_resolves_transparent_to_empty():
    assert node_background(node(styles={"background-color": "transparent"})) == ""


def test_spacing_reports_a_representative_scale():
    nodes = [
        node(styles={"padding-top": "32px", "padding-bottom": "32px", "gap": "16px"}),
        node(styles={"padding-top": "16px", "padding-bottom": "16px", "gap": "8px"}),
        node(styles={"margin-top": "64px"}),
    ]
    spacing = extract_spacing(nodes)
    assert spacing.md and spacing.lg
    assert spacing.md <= spacing.lg
    assert spacing.unit


def test_visual_collects_radii_shadows_and_max_width():
    nodes = [
        node(styles={"border-radius": "12px", "box-shadow": "0 1px 2px rgba(0,0,0,0.1)"}),
        node(styles={"border-radius": "6px", "border-top-width": "1px"}),
        node(styles={"max-width": "1200px"}),
    ]
    visual = extract_visual(nodes)
    assert 12 in visual.radii
    assert visual.shadows
    assert visual.max_width == 1200
    # A 1px border must not be quantised down to "no border".
    assert 1 in visual.border_widths
    assert 0 not in visual.border_widths
