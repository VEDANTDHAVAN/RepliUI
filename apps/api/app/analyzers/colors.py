"""Deterministic color extraction.

Colors are resolved from computed styles, not from CSS text, and the palette is
ranked by how often each color actually paints. Representative tokens
(background / surface / text / border) are then assigned from the ranked
palette, so a generator can start from a coherent theme without the LLM
inventing colors.
"""

from __future__ import annotations

import re
from collections import Counter

from ..models.schemas import ColorSpec, ThemeSpec
from .raw_models import RawNode

RGB_PATTERN = re.compile(r"rgba?\(([^)]+)\)")
HEX_PATTERN = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
NAMED_COLORS = {
    "black", "white", "red", "green", "blue", "yellow", "orange", "purple",
    "gray", "grey", "silver", "navy", "teal", "maroon", "olive", "lime",
    "aqua", "fuchsia", "transparent",
}

# Rough luminance thresholds used only to classify roles.
LIGHT_LUMINANCE = 0.85
DARK_LUMINANCE = 0.2
# Saturation above which a color is treated as a deliberate brand hue.
SATURATED = 0.35


def parse_color(value: str) -> tuple[int, int, int, float] | None:
    """Parse a computed color into rgba components, or None if not a color."""
    if not value:
        return None
    value = value.strip().lower()
    if not value or value in {"none", "auto", "inherit", "initial", "unset", "currentcolor"}:
        return None
    if value in NAMED_COLORS:
        named = {
            "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
            "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
            "orange": (255, 165, 0), "purple": (128, 0, 128), "gray": (128, 128, 128),
            "grey": (128, 128, 128), "silver": (192, 192, 192), "navy": (0, 0, 128),
            "teal": (0, 128, 128), "maroon": (128, 0, 0), "olive": (128, 128, 0),
            "lime": (0, 255, 0), "aqua": (0, 255, 255), "fuchsia": (255, 0, 255),
            "transparent": (255, 255, 255),
        }
        r, g, b = named[value]
        return r, g, b, 0.0 if value == "transparent" else 1.0
    match = HEX_PATTERN.match(value)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        r, g, b = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
        alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
        return r, g, b, alpha
    match = RGB_PATTERN.match(value)
    if match:
        parts = [p.strip() for p in match.group(1).split(",")]
        if len(parts) < 3:
            return None
        try:
            r, g, b = (int(float(p)) for p in parts[:3])
        except ValueError:
            return None
        alpha = float(parts[3]) if len(parts) > 3 else 1.0
        return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)), alpha
    return None


def to_hex(color: tuple[int, int, int, float]) -> str:
    r, g, b, _alpha = color
    return f"#{r:02x}{g:02x}{b:02x}"


def luminance(color: tuple[int, int, int, float]) -> float:
    r, g, b, _alpha = (channel / 255 for channel in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first: tuple[int, int, int, float], second: tuple[int, int, int, float]) -> float:
    l1, l2 = luminance(first), luminance(second)
    lighter, darker = max(l1, l2), min(l1, l2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def _border_colors(node: RawNode) -> list[tuple[int, int, int, float]]:
    """Computed border colours, expanding the `border-top` shorthand.

    `border-top: 1px solid #e2e8f0` is common in authored CSS, and the
    side-specific `border-top-color` is empty in that case.
    """
    found: list[tuple[int, int, int, float]] = []
    for side in ("top", "bottom", "left", "right"):
        color = parse_color(node.styles.get(f"border-{side}-color", ""))
        if not color:
            shorthand = node.styles.get(f"border-{side}", "")
            if shorthand:
                for token in shorthand.split():
                    color = parse_color(token)
                    if color:
                        break
        if color:
            found.append(color)
    return found


def _border_color(node: RawNode) -> str:
    """The most-used border colour on a node, or an empty string."""
    for color in _border_colors(node):
        return to_hex(color)
    return ""


def collect_color_usage(nodes: list[RawNode]) -> dict[str, int]:
    """Count how often each opaque color paints, by computed style property."""
    counter: Counter[str] = Counter()
    for node in nodes:
        if not node.visible:
            continue
        for prop in ("color", "background-color"):
            raw = node.styles.get(prop, "")
            parsed = parse_color(raw)
            if parsed is None or parsed[3] < 0.1:
                continue
            counter[to_hex(parsed)] += 1
        for parsed in _border_colors(node):
            counter[to_hex(parsed)] += 1
        background_image = node.styles.get("background-image", "")
        for match in RGB_PATTERN.finditer(background_image or ""):
            candidate = f"rgb({match.group(1)})"
            parsed = parse_color(candidate)
            if parsed and parsed[3] > 0.1:
                counter[to_hex(parsed)] += 1
    return dict(counter)


def extract_palette(nodes: list[RawNode], limit: int = 12) -> list[ColorSpec]:
    """Ranked color palette with a coarse usage label for each entry."""
    usage_counts = collect_color_usage(nodes)
    palette: list[ColorSpec] = []
    for value, count in sorted(usage_counts.items(), key=lambda item: (-item[1], item[0]))[:limit]:
        parsed = parse_color(value)
        if parsed is None:
            continue
        palette.append(ColorSpec(name=_usage_name(nodes, parsed), value=value, usage=f"{count} elements"))
    return palette


def _usage_name(nodes: list[RawNode], color: tuple[int, int, int, float]) -> str:
    hex_value = to_hex(color)
    light = luminance(color) >= LIGHT_LUMINANCE
    dark = luminance(color) <= DARK_LUMINANCE
    as_text = as_background = as_border = 0
    for node in nodes:
        if not node.visible:
            continue
        if (parsed := parse_color(node.styles.get("color", ""))) and to_hex(parsed) == hex_value:
            as_text += 1
        if (parsed := parse_color(node.styles.get("background-color", ""))) and to_hex(parsed) == hex_value:
            as_background += 1
        if any(to_hex(parsed) == hex_value for parsed in _border_colors(node)):
            as_border += 1
    if as_text >= as_background and as_text > 0:
        return "text" if dark else "light text"
    if as_background > 0:
        # A saturated colour used as a background is a brand colour, not a page
        # surface: brand blues and greens must not be lost as "background".
        if _saturation(color) >= SATURATED and not light and not dark:
            return "accent"
        return "surface" if light else "background"
    if as_border > 0:
        return "border"
    return "accent"


def build_theme_tokens(nodes: list[RawNode], palette: list[ColorSpec]) -> ThemeSpec:
    """Assign representative theme tokens from the observed palette."""
    tokens = ThemeSpec()
    if not palette:
        return tokens

    backgrounds = [c for c in palette if c.name in {"background", "surface", "light text"}]
    texts = [c for c in palette if c.name in {"text", "light text"}]
    borders = [c for c in palette if c.name == "border"]

    document_background = _document_background(nodes)
    if document_background:
        tokens.background = document_background
    elif backgrounds:
        tokens.background = backgrounds[0].value
    if len(backgrounds) > 1:
        tokens.surface = backgrounds[1].value
    if texts:
        tokens.text = texts[0].value
        if len(texts) > 1:
            tokens.muted_text = texts[1].value
    if borders:
        tokens.border = borders[0].value

    # Accents drive the brand tokens, even when the palette's top entries are
    # text and background colours.
    accents = [c for c in palette if c.name == "accent"]
    if accents:
        tokens.accent = accents[0].value
        # A saturated, mid-lumination color is the likeliest interactive hue.
        candidates = [
            c
            for c in palette
            if c.value not in {tokens.text, tokens.background, tokens.surface, tokens.border}
        ]
        tokens.primary = _most_saturated(candidates) or (accents[0].value if accents else None)
        tokens.secondary = next((c.value for c in candidates if c.value != tokens.primary), None)
    return tokens


def _document_background(nodes: list[RawNode]) -> str | None:
    for node in nodes:
        if node.tag in {"html", "body"} and node.visible:
            parsed = parse_color(node.styles.get("background-color", ""))
            if parsed and parsed[3] > 0.5:
                return to_hex(parsed)
    return None


def _saturation(color: tuple[int, int, int, float]) -> float:
    """HSL saturation for a parsed rgba colour, in [0, 1]."""
    r, g, b, _alpha = (channel / 255 for channel in color)
    high, low = max(r, g, b), min(r, g, b)
    return 0.0 if high == 0 else (high - low) / high


def _most_saturated(palette: list[ColorSpec]) -> str | None:
    best: tuple[float, str] | None = None
    for entry in palette:
        parsed = parse_color(entry.value)
        if parsed is None:
            continue
        saturation = _saturation(parsed)
        if best is None or saturation > best[0]:
            best = (saturation, entry.value)
    return best[1] if best else None
