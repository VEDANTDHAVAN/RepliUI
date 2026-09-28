"""Responsive comparison between the desktop and mobile observations.

The two viewport readings are compared structurally: navigation item counts,
section visibility, column counts, heading/body sizes, content width, and which
component kinds appear or disappear. Every note describes something that was
actually observed on both sides.
"""

from __future__ import annotations

from ..models.schemas import ResponsiveSpec
from .components import count_grid_columns, detect_components
from .raw_models import ViewportReading

DESKTOP = ("desktop", 1440, 900)
MOBILE = ("mobile", 390, 844)


def compare(desktop: ViewportReading, mobile: ViewportReading) -> ResponsiveSpec:
    """Build a ResponsiveSpec from the two viewport readings."""
    desktop_summary = summarize(desktop)
    mobile_summary = summarize(mobile)

    notes: list[str] = []
    if mobile_summary["navigation_items"] < desktop_summary["navigation_items"]:
        hidden = desktop_summary["navigation_items"] - mobile_summary["navigation_items"]
        notes.append(f"navigation collapses from {desktop_summary['navigation_items']} to {mobile_summary['navigation_items']} items ({hidden} hidden behind a toggle)")
    elif mobile_summary["navigation_items"] > desktop_summary["navigation_items"]:
        notes.append("navigation exposes more items on mobile, consistent with a stacked or always-open menu")

    if desktop_summary["max_columns"] > mobile_summary["max_columns"]:
        notes.append(f"multi-column grids collapse from {desktop_summary['max_columns']} columns to {mobile_summary['max_columns']}")
    if desktop_summary["visible_sections"] != mobile_summary["visible_sections"]:
        notes.append(f"{desktop_summary['visible_sections']} visible sections on desktop vs {mobile_summary['visible_sections']} on mobile")

    if desktop_summary["heading_size"] and mobile_summary["heading_size"]:
        if mobile_summary["heading_size"] < desktop_summary["heading_size"]:
            notes.append(f"headings scale down from {desktop_summary['heading_size']}px to {mobile_summary['heading_size']}px")
    if desktop_summary["body_size"] and mobile_summary["body_size"]:
        if mobile_summary["body_size"] < desktop_summary["body_size"]:
            notes.append(f"body text scales down from {desktop_summary['body_size']}px to {mobile_summary['body_size']}px")

    desktop_width = desktop_summary["content_width"]
    mobile_width = mobile_summary["content_width"]
    if desktop_width and mobile_width and mobile_width < desktop_width:
        notes.append(f"content width shrinks from {desktop_width}px to {mobile_width}px")

    hidden_kinds = sorted(set(desktop_summary["component_kinds"]) - set(mobile_summary["component_kinds"]))
    shown_kinds = sorted(set(mobile_summary["component_kinds"]) - set(desktop_summary["component_kinds"]))
    for kind in hidden_kinds:
        notes.append(f"{kind} patterns are hidden at mobile width")
    for kind in shown_kinds:
        notes.append(f"{kind} patterns appear only at mobile width")

    spec = ResponsiveSpec(
        breakpoint="mobile",
        notes=notes,
        width=mobile.width,
        height=mobile.height,
        is_mobile=True,
        navigation_items=mobile_summary["navigation_items"],
        visible_sections=mobile_summary["visible_sections"],
        max_columns=mobile_summary["max_columns"],
        heading_size=mobile_summary["heading_size"],
        body_size=mobile_summary["body_size"],
        content_width=mobile_summary["content_width"],
        hidden_component_kinds=hidden_kinds,
        shown_component_kinds=shown_kinds,
    )
    if not spec.notes:
        spec.notes.append("layout is largely unchanged between the sampled viewports")
    return spec


def summarize(reading: ViewportReading) -> dict:
    """Compact, comparable summary of one viewport reading."""
    visible = [node for node in reading.nodes if node.visible]
    nav_items = 0
    for node in visible:
        if node.tag in {"nav"} or node.role == "navigation":
            nav_items = max(nav_items, sum(1 for child in reading.nodes if child.tag == "a" and child.visible))
    if nav_items == 0:
        header = next((node for node in visible if node.tag == "header"), None)
        if header is not None:
            nav_items = sum(
                1
                for node in visible
                if node.tag == "a" and header.rect.y <= node.rect.y <= header.rect.y + header.rect.height
            )

    columns = 1
    for node in visible:
        display = node.styles.get("display", "")
        if display.startswith("grid"):
            template = node.styles.get("grid-template-columns", "").strip()
            if template and template != "none":
                columns = max(columns, count_grid_columns(template))
        elif display.startswith("flex") and node.styles.get("flex-wrap", "") == "wrap":
            columns = max(columns, 2)

    heading_size = 0
    body_size = 0
    for node in visible:
        raw = node.styles.get("font-size", "")
        if not raw.endswith("px"):
            continue
        try:
            size = int(float(raw[:-2]))
        except ValueError:
            continue
        if node.tag in {"h1", "h2", "h3"}:
            heading_size = max(heading_size, size)
        elif node.tag == "p":
            body_size = max(body_size, size)

    content_width = max((node.rect.width for node in visible), default=0)
    return {
        "navigation_items": nav_items,
        "visible_sections": len([node for node in visible if node.tag in {"section", "main", "article"}]),
        "max_columns": columns,
        "heading_size": heading_size,
        "body_size": body_size,
        "content_width": content_width,
        "component_kinds": [spec.kind for spec in detect_components(reading.layout, reading.nodes, reading.width)],
    }


def viewport_rules(readings: list[ViewportReading]) -> list[ResponsiveSpec]:
    """One ResponsiveSpec per observed viewport, for the plural field."""
    return [
        ResponsiveSpec(
            breakpoint="mobile" if reading.is_mobile else "desktop",
            notes=[f"{reading.width}x{reading.height} {'mobile' if reading.is_mobile else 'desktop'} reading"],
            width=reading.width,
            height=reading.height,
            is_mobile=reading.is_mobile,
        )
        for reading in readings
    ]
