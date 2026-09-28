"""Deterministic typography and spacing extraction from computed styles.

Representative values, not a dump: the most frequent font size becomes the body
size, sizes are bucketed into a heading scale, and spacing is reduced to a small
scale derived from the values that actually appear.
"""

from __future__ import annotations

import re
from collections import Counter

from ..models.schemas import SpacingSpec, TypographySpec, VisualSpec
from .colors import parse_color, to_hex
from .raw_models import RawNode

PX_PATTERN = re.compile(r"^(-?\d+(?:\.\d+)?)px$")
NUMBER_PATTERN = re.compile(r"^(-?\d+(?:\.\d+)?)$")
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BUTTON_TAGS = {"button"}


def _px(value: str) -> float | None:
    if not value:
        return None
    match = PX_PATTERN.match(value.strip())
    if match:
        return float(match.group(1))
    match = NUMBER_PATTERN.match(value.strip())
    return float(match.group(1)) if match else None


def _normalize_family(value: str) -> str:
    """Reduce a computed font stack to its primary family."""
    if not value:
        return ""
    first = value.split(",")[0].strip().strip("'\"")
    return first[:60]


def _quantize(value: float) -> int:
    return int(round(value / 2) * 2)


def extract_typography(nodes: list[RawNode]) -> TypographySpec:
    families: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    weights: Counter[str] = Counter()
    line_heights: Counter[str] = Counter()
    letter_spacings: Counter[str] = Counter()
    heading_sizes: dict[str, int] = {}
    body_candidates: list[int] = []
    button_candidates: list[int] = []

    for node in nodes:
        if not node.visible:
            continue
        styles = node.styles
        family = _normalize_family(styles.get("font-family", ""))
        if family:
            families[family] += 1
        size = _px(styles.get("font-size", ""))
        if size and size > 0:
            sizes[f"{_quantize(size)}px"] += 1
            if node.tag in HEADING_TAGS:
                weight = styles.get("font-weight", "400").strip()
                bucket = "display" if size >= 40 else ("h1" if size >= 32 else "h2" if size >= 24 else "h3")
                current = heading_sizes.get(bucket)
                if current is None or size > current:
                    heading_sizes[bucket] = _quantize(size)
            elif node.tag in BUTTON_TAGS or node.role == "button":
                button_candidates.append(_quantize(size))
            elif node.tag in {"p", "li", "span", "div", "td", "label"}:
                body_candidates.append(_quantize(size))
        weight = styles.get("font-weight", "").strip()
        if weight in {"bold", "bolder"}:
            weights["700"] += 1
        elif NUMBER_PATTERN.match(weight):
            weights[weight] += 1
        line_height = styles.get("line-height", "")
        if line_height and line_height != "normal":
            line_heights[line_height[:24]] += 1
        letter_spacing = styles.get("letter-spacing", "")
        if letter_spacing and letter_spacing not in {"normal", "0px"}:
            letter_spacings[letter_spacing[:24]] += 1

    return TypographySpec(
        families=[name for name, _ in families.most_common(4)],
        sizes=[size for size, _ in sizes.most_common(8)],
        weights=[weight for weight, _ in weights.most_common(4)],
        heading_sizes=heading_sizes,
        body_size=_mode(body_candidates) or _mode([int(s.rstrip("px")) for s in sizes]),
        line_heights=[value for value, _ in line_heights.most_common(3)],
        letter_spacings=[value for value, _ in letter_spacings.most_common(2)],
    )


def _mode(values: list[int]) -> int | None:
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def extract_spacing(nodes: list[RawNode]) -> SpacingSpec:
    """Reduce observed padding/gap values to a small spacing scale."""
    gaps: list[int] = []
    pads: list[int] = []
    section_gaps: list[int] = []
    units: list[int] = []

    for node in nodes:
        if not node.visible:
            continue
        gap = _px(node.styles.get("gap", "")) or _px(node.styles.get("row-gap", ""))
        if gap and gap > 0:
            gaps.append(_quantize(gap))
        padding_values = [
            _px(node.styles.get(f"padding-{side}", "")) for side in ("top", "right", "bottom", "left")
        ]
        horizontal = _mode([int(v) for v in padding_values if v is not None and v > 0])
        if horizontal:
            pads.append(horizontal)
            if node.tag in {"section", "main", "article"}:
                section_gaps.append(horizontal)
        margin = _px(node.styles.get("margin-top", ""))
        if margin and margin > 0:
            units.append(_quantize(margin))

    combined = sorted({value for value in pads + gaps if value > 0})
    if not combined:
        return SpacingSpec()
    base = _mode(combined) or combined[0]
    return SpacingSpec(
        xs=_nearest(combined, base // 4),
        sm=_nearest(combined, base // 2),
        md=base,
        lg=_nearest(combined, base * 2),
        xl=_nearest(combined, base * 3),
        section_gap=_mode(section_gaps) or _nearest(combined, base * 4),
        unit=base,
    )


def _nearest(values: list[int], target: int) -> int | None:
    if not values:
        return None
    return min(values, key=lambda value: (abs(value - target), value))


def extract_visual(nodes: list[RawNode]) -> VisualSpec:
    radii: Counter[int] = Counter()
    borders: Counter[int] = Counter()
    shadows: Counter[str] = Counter()
    max_widths: list[int] = []

    for node in nodes:
        if not node.visible:
            continue
        radius = _px(node.styles.get("border-radius", ""))
        if radius and radius > 0:
            radii[_quantize(radius)] += 1
        border = _px(node.styles.get("border-top-width", ""))
        if border and border > 0:
            # Keep a visible minimum: quantising 1px down to 0 would tell the
            # generator the site has no borders.
            borders[max(1, _quantize(border))] += 1
        shadow = (node.styles.get("box-shadow", "") or "").strip()
        if shadow and shadow != "none" and len(shadow) <= 120:
            shadows[_normalize_shadow(shadow)] += 1
        max_width = _px(node.styles.get("max-width", ""))
        if max_width and max_width >= 320:
            max_widths.append(int(max_width))

    return VisualSpec(
        radii=[value for value, _ in radii.most_common(3)],
        border_widths=[value for value, _ in borders.most_common(3)],
        shadows=[value for value, _ in shadows.most_common(3)],
        max_width=_mode(max_widths),
    )


def _normalize_shadow(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip()
    return collapsed[:120]


def node_text_color(node: RawNode) -> str:
    parsed = parse_color(node.styles.get("color", ""))
    return to_hex(parsed) if parsed else ""


def node_background(node: RawNode) -> str:
    for prop in ("background-color", "background-image"):
        value = node.styles.get(prop, "")
        if not value or value in {"none", "transparent"}:
            continue
        parsed = parse_color(value) if "rgb" in value or value.startswith("#") else None
        if parsed:
            return to_hex(parsed)
    return ""


def node_font_size(node: RawNode) -> int | None:
    size = _px(node.styles.get("font-size", ""))
    return _quantize(size) if size else None
