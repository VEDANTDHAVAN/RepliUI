"""Repeated UI pattern detection.

Patterns come from the repeated-sibling groups the in-page layout script
collects, plus tag semantics. A group is described, not assumed to be a
"pricing card" or a "testimonial" — the role label is derived from what the
group actually contains.
"""

from __future__ import annotations

import re

from ..models.schemas import ComponentSpec
from .raw_models import RawNode, RawLayout

# A group must repeat at least this many times to be a reusable pattern.
MIN_REPEAT = 2
MAX_REPEAT = 48

# A whole `repeat(...)` call, so its arguments are not counted as tracks.
# `minmax(...)` inside it is one level of nesting. The count group is empty for
# keyword repeats (`auto-fit`, `auto-fill`), whose track count is not knowable
# from the declaration alone.
_REPEAT_CALL = re.compile(r"repeat\(\s*(\d+)?\s*,[^()]*(?:\([^()]*\)[^()]*)*\)", re.I)


def count_grid_columns(template: str) -> int:
    """Count CSS grid tracks in a `grid-template-columns` value.

    The value comes from the browser's computed style, which may be either the
    authored form (`repeat(3, 1fr) 1fr`, where a `repeat()` contains a comma) or
    the resolved form (`442.656px 442.672px 442.656px`, space-separated). Both
    are handled by scanning for top-level separators only, and a `repeat(n, ...)`
    entry contributes exactly n tracks.
    """
    normalized = template.strip().lower()
    if not normalized or normalized in {"none", "subgrid", "inherit", "initial"}:
        return 0

    total = 0
    depth = 0
    token = ""

    def flush() -> None:
        # One top-level token is one track, whether it is a size (`1fr`, `200px`)
        # or a function (`minmax(0, 1fr)`). A `repeat(n, ...)` stands for n; a
        # keyword repeat's count is not knowable, so it contributes nothing.
        nonlocal total
        remainder = _REPEAT_CALL.sub("", token).strip()
        for match in _REPEAT_CALL.finditer(token):
            if match.group(1):
                total += int(match.group(1))
        if remainder and remainder.lower() not in {"none", "subgrid"}:
            total += 1

    for char in template:
        if char == "(":
            depth += 1
            token += char
            continue
        if char == ")":
            depth = max(0, depth - 1)
            token += char
            continue

        if depth == 0 and char in ", \t":
            if token.strip():
                flush()
            token = ""
        else:
            token += char

    if token.strip():
        flush()
    return total


def detect_components(layout: RawLayout, nodes: list[RawNode], reading_width: int) -> list[ComponentSpec]:
    specs: list[ComponentSpec] = []
    seen: set[tuple[str, int]] = set()

    for group in layout.groups:
        if not (MIN_REPEAT <= group.count <= MAX_REPEAT):
            continue
        # Near-identical heights across siblings is the card/row signature.
        card_like = group.height_spread <= max(48, group.average_height * 0.5)
        kind = _kind_for(group.tag, group.parent_display, card_like, group.count)
        if kind is None:
            continue
        key = (kind, group.count)
        if key in seen:
            continue
        seen.add(key)
        specs.append(
            ComponentSpec(
                name=_name_for(kind, group.parent_tag, group.selector),
                kind=kind,
                count=group.count,
                role=_role_for(kind, group.sample_text, group.parent_columns),
                sample_text=group.sample_text[:3],
                selectors=[group.selector] if group.selector else [],
            )
        )

    specs.extend(_semantic_components(nodes))
    specs.sort(key=lambda spec: (-spec.count, spec.kind))
    return specs[:20]


def _kind_for(tag: str, parent_display: str, card_like: bool, count: int) -> str | None:
    if tag in {"li", "a", "button"} and count <= 12:
        return "nav item" if parent_display in {"flex", "block", "inline-flex", ""} else None
    if tag in {"article", "li", "div", "a", "button", "figure", "blockquote", "td"}:
        return "card" if card_like else None
    return None


def _name_for(kind: str, parent_tag: str, selector: str) -> str:
    readable = selector.split(">")[-1].strip() if selector else parent_tag
    cleaned = readable.replace(".", "-").replace("#", "")
    return (cleaned or f"{kind} group")[:48]


def _role_for(kind: str, sample_text: list[str], columns: int) -> str:
    if kind == "nav item":
        return f"{len(sample_text)} inline links in a {parent_display_of(columns)} row"
    if columns > 1:
        return f"repeated item in a {columns}-column grid"
    return "repeated vertical item"


def parent_display_of(columns: int) -> str:
    return "multi-column" if columns > 1 else "single-column"


def _semantic_components(nodes: list[RawNode]) -> list[ComponentSpec]:
    """Tag-driven patterns that do not depend on sibling repetition."""
    specs: list[ComponentSpec] = []
    counts: dict[str, int] = {}
    for node in nodes:
        if not node.visible:
            continue
        if node.tag == "nav" or (node.tag == "header" and node.child_elements > 0):
            counts["navigation"] = counts.get("navigation", 0) + 1
        elif node.form is not None:
            counts["form"] = counts.get("form", 0) + 1
        elif node.tag == "blockquote":
            counts["quote"] = counts.get("quote", 0) + 1
        elif node.tag == "footer":
            counts["footer columns"] = counts.get("footer columns", 0) + 1
    for kind, count in counts.items():
        specs.append(ComponentSpec(name=kind, kind=kind, count=count, role=_semantic_role(kind)))
    return specs


def _semantic_role(kind: str) -> str:
    return {
        "navigation": "primary site navigation",
        "form": "input form",
        "quote": "blockquote or pull quote",
        "footer columns": "site footer",
    }.get(kind, kind)


def component_index(specs: list[ComponentSpec]) -> dict[str, list[ComponentSpec]]:
    """Index used by section detection to attribute patterns to sections."""
    index: dict[str, list[ComponentSpec]] = {}
    for spec in specs:
        index.setdefault(spec.kind, []).append(spec)
    return index
