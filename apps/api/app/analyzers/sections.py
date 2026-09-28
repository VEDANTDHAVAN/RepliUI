"""Deterministic section detection.

Sections are derived from the rendered box model: large, full-width, vertically
stacked containers that hold real content. Classification is based on the
structure each section *has* (counted headings, cards, links, forms, media) —
never on a fixed list of expected section names for any particular website.
"""

from __future__ import annotations

from ..models.schemas import ComponentSpec, LayoutSpec, SectionSpec
from . import typography as ty
from .components import count_grid_columns
from .raw_models import RawNode, ViewportReading

# Section candidates must be at least this wide to count as a full-width band.
MIN_SECTION_WIDTH_RATIO = 0.55
MIN_SECTION_HEIGHT = 80
MIN_SECTION_NODES = 2
# Containers that merely wrap a single section add noise rather than structure.
CONTAINER_TAGS = {"div", "main", "section", "article", "header", "footer", "aside", "ul", "nav"}

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# Semantic landmarks are kept whatever their size: a 64px site header is the
# navigation, and a footer with one copyright line is still the footer.
LANDMARK_TAGS = {"header", "footer", "nav"}


def detect_sections(reading: ViewportReading, component_index: dict[str, list[ComponentSpec]]) -> list[SectionSpec]:
    """Find section candidates and describe each one."""
    nodes = reading.nodes
    viewport_width = max(node.rect.width for node in nodes) if nodes else reading.width
    candidates = _candidates(nodes, viewport_width)
    document_height = max((node.rect.y + node.rect.height for node in nodes), default=1)

    sections: list[SectionSpec] = []
    for node in candidates:
        contained = _descendants(node, nodes)
        # A landmark rarely holds more than a couple of children.
        required = 1 if node.tag in LANDMARK_TAGS else MIN_SECTION_NODES
        if len(contained) < required:
            continue
        section = _describe(node, contained, document_height, reading, component_index)
        if section is not None:
            sections.append(section)

    sections = _drop_nested(sections)
    sections.sort(key=lambda item: (item.top if item.top is not None else 0, -(item.width or 0)))
    for order, section in enumerate(sections):
        section.order = order
    return sections


def _candidates(nodes: list[RawNode], viewport_width: int) -> list[RawNode]:
    threshold = viewport_width * MIN_SECTION_WIDTH_RATIO
    candidates: list[RawNode] = []
    for node in nodes:
        if not node.visible or node.tag not in CONTAINER_TAGS:
            continue
        if node.rect.width < threshold or node.child_elements < 1:
            continue
        if node.tag not in LANDMARK_TAGS and node.rect.height < MIN_SECTION_HEIGHT:
            continue
        candidates.append(node)
    return candidates


def _descendants(node: RawNode, nodes: list[RawNode]) -> list[RawNode]:
    """Nodes strictly inside ``node``'s rectangle (viewport coordinates).

    Section bands tile the page and share their edges, so the bottom and right
    bounds are exclusive: with an inclusive test a band would swallow the top
    row of the section stacked directly below it. Selectors cannot be used to
    settle this — the browser script caps a node's path at four segments
    (``scripts.pathOf``), which truncates the top of any deep node's selector.
    """
    top, left = node.rect.y, node.rect.x
    bottom, right = top + node.rect.height, left + node.rect.width
    return [
        candidate
        for candidate in nodes
        if candidate is not node
        and candidate.rect.width > 0
        and candidate.rect.height > 0
        and candidate.rect.y >= top
        and candidate.rect.y < bottom
        and candidate.rect.x >= left
        and candidate.rect.x < right
    ]


def _drop_nested(sections: list[SectionSpec]) -> list[SectionSpec]:
    """Keep the outermost band when two candidates describe the same area.

    Section bands normally tile the page; a near-identical area means one is a
    wrapper of the other and the wrapper is the real band.
    """
    kept: list[SectionSpec] = []
    for section in sorted(sections, key=lambda item: -(item.width or 0) * (item.height or 0)):
        duplicate = False
        for existing in kept:
            if (
                existing.top is not None
                and section.top is not None
                and abs(existing.top - section.top) <= 24
                and abs((existing.width or 0) - (section.width or 0)) <= 8
            ):
                duplicate = True
                break
        if not duplicate:
            kept.append(section)
    return kept


def _describe(
    node: RawNode,
    contained: list[RawNode],
    document_height: int,
    reading: ViewportReading,
    component_index: dict[str, list[ComponentSpec]],
) -> SectionSpec | None:
    headings = [item for item in contained if item.tag in HEADING_TAGS and item.text]
    links = [item for item in contained if item.tag == "a" and item.href]
    images = [item for item in contained if item.tag == "img" and item.visible]
    buttons = [item for item in contained if item.tag in {"button"} or item.role == "button"]
    forms = [item for item in contained if item.form is not None]
    cards = _count_cards(node, contained, component_index)
    columns = _columns(node)

    heading = headings[0].text[:160] if headings else None
    text = " ".join(item.text for item in contained if item.text)[:400].strip()

    section = SectionSpec(
        name=_section_name(node, heading),
        tag=node.tag,
        heading=heading,
        text=text,
        order=0,
        section_type=_classify(
            node=node,
            headings=headings,
            cards=cards,
            links=links,
            buttons=buttons,
            forms=forms,
            images=images,
            reading=reading,
        ),
        layout=LayoutSpec(
            display=node.styles.get("display", "block"),
            columns=columns,
            gap=int(ty._px(node.styles.get("gap", "")) or 0) or None,
            padding=_padding(node),
            max_width=int(ty._px(node.styles.get("max-width", "")) or 0) or None,
            align_items=node.styles.get("align-items", "stretch"),
            justify_content=node.styles.get("justify-content", "start"),
        ),
        background=ty.node_background(node),
        text_color=ty.node_text_color(node),
        spacing=_section_spacing(contained),
        visual=_section_visual(contained),
        width=node.rect.width,
        height=node.rect.height,
        top=node.rect.y,
        top_ratio=round(node.rect.y / document_height, 4) if document_height else 0.0,
        link_count=len(links),
        asset_count=len(images),
    )
    section.image_urls = [item.image.src for item in images if item.image and item.image.src][:12]
    section.child_components = _child_components(node, contained, component_index)
    section.confidence = round(_confidence(section, headings, cards), 2)
    return section


def _section_name(node: RawNode, heading: str | None) -> str:
    if heading:
        return heading[:60]
    if node.attributes.class_:
        first = node.attributes.class_.split()[0]
        if len(first) <= 40:
            return first
    return f"{node.tag} section"


def _columns(node: RawNode) -> int:
    if node.styles.get("display", "").startswith("grid"):
        template = node.styles.get("grid-template-columns", "").strip()
        if template and template != "none":
            return max(1, count_grid_columns(template))
    if node.styles.get("display", "").startswith("flex"):
        if node.styles.get("flex-wrap", "") == "wrap":
            return 2
        return 1
    return 1


CARD_KINDS = {"card", "item", "tile"}


def _selector_matches(selector: str, node_selector: str) -> bool:
    """True when a stored component selector names this node.

    The component index records the short form (`section.features`) while nodes
    carry the full path (`html > body > section.features`), so the last segment
    is compared when the paths are not identical.
    """
    if selector == node_selector:
        return True
    return node_selector.endswith(f"> {selector}") or node_selector == selector


def _repeated_selectors(component_index: dict[str, list[ComponentSpec]]) -> dict[str, str]:
    """Map every repeated-component selector to its component name.

    Keyed by selector, not name: a card grid is detected from sibling repetition
    and is usually named after its container (`section-features`), so the name is
    not predictable. The selector names the repeated group.
    """
    mapping: dict[str, str] = {}
    for specs in component_index.values():
        for spec in specs:
            if spec.kind not in CARD_KINDS:
                continue
            for selector in spec.selectors:
                mapping.setdefault(selector, spec.name)
    return mapping


def _count_cards(
    node: RawNode,
    contained: list[RawNode],
    component_index: dict[str, list[ComponentSpec]],
) -> int:
    """Cards *inside this section*, counted from observed sibling repetition.

    Only this section's own node and descendants may vote: a card grid on another
    part of the page must not make every band look like a card grid. The repeated
    group is usually the container itself, so the section node counts too.
    """
    selectors = _repeated_selectors(component_index)
    if not selectors:
        return 0

    best = 0
    for selector, name in selectors.items():
        if _selector_matches(selector, node.selector):
            # The container is reported as the grid, so the section itself is
            # one match and its repeated children add no extra count.
            best = max(best, max(1, spec_count(component_index, selector)))
            continue
        inside = sum(
            1 for child in contained if child.visible and _selector_matches(selector, child.selector)
        )
        best = max(best, min(inside, 24))
    return best


def spec_count(component_index: dict[str, list[ComponentSpec]], selector: str) -> int:
    for specs in component_index.values():
        for spec in specs:
            if selector in spec.selectors:
                return spec.count
    return 1


def _child_components(
    node: RawNode,
    contained: list[RawNode],
    component_index: dict[str, list[ComponentSpec]],
) -> list[str]:
    names: list[str] = []
    for child in contained:
        tag = child.tag
        if tag == "nav" and "navigation" not in names:
            names.append("navigation")
        elif tag == "form" and "form" not in names:
            names.append("form")
        elif tag == "img" and "image" not in names:
            names.append("image")
        elif tag == "svg" and "icon" not in names:
            names.append("icon")
        elif tag == "button" and "button" not in names:
            names.append("button")
        elif tag == "a" and "link" not in names:
            names.append("link")
        elif tag in {"h1", "h2", "h3"} and "heading" not in names:
            names.append("heading")
    # Repeated components are reported only when this section matches or contains
    # their selector: a card grid elsewhere must not label every band.
    present = [node.selector] + [child.selector for child in contained if child.visible]
    for selector, name in _repeated_selectors(component_index).items():
        if any(_selector_matches(selector, candidate) for candidate in present) and name not in names:
            names.append(name)
    return names[:10]


def _section_spacing(contained: list[RawNode]) -> "SpacingSpec":
    from ..models.schemas import SpacingSpec

    paddings = [
        int(ty._px(node.styles.get("padding-top", "")) or 0)
        for node in contained
        if node.visible
    ]
    paddings = [value for value in paddings if value >= 8]
    if not paddings:
        return SpacingSpec()
    return SpacingSpec(unit=ty._quantize(max(paddings)), section_gap=ty._quantize(max(paddings)))


def _section_visual(contained: list[RawNode]):
    from ..models.schemas import VisualSpec

    radii: set[int] = set()
    shadows: set[str] = set()
    for node in contained:
        if not node.visible:
            continue
        radius = ty._px(node.styles.get("border-radius", ""))
        if radius and radius > 0:
            radii.add(ty._quantize(radius))
        shadow = (node.styles.get("box-shadow", "") or "").strip()
        if shadow and shadow != "none":
            shadows.add(shadow[:80])
    return VisualSpec(radii=sorted(radii)[:3], shadows=sorted(shadows)[:2])


def _padding(node: RawNode) -> tuple[int, int, int, int]:
    values = []
    for side in ("top", "right", "bottom", "left"):
        value = ty._px(node.styles.get(f"padding-{side}", ""))
        values.append(int(value) if value else 0)
    return tuple(values)  # type: ignore[return-value]


def _classify(
    node: RawNode,
    headings: list[RawNode],
    cards: int,
    links: list[RawNode],
    buttons: list[RawNode],
    forms: list[RawNode],
    images: list[RawNode],
    reading: ViewportReading,
) -> str:
    """Infer a section role from observed structure only."""
    if node.tag == "header" or (node.rect.y <= 8 and links and not headings):
        return "navigation"
    if node.tag == "footer" or (node.rect.y > reading.document_height * 0.8 and node.rect.height < reading.document_height * 0.4 and cards < 3):
        return "footer"
    if forms:
        return "form"
    if node.tag == "nav":
        return "navigation"
    if cards >= 3:
        # A genuinely repeated card group is a card grid. This is checked before
        # the heading heuristics so a card grid is never relabelled from its
        # heading count alone.
        return "card grid"
    if len(headings) >= 3 and len(headings) > len(buttons) * 2 and not images:
        return "feature grid"
    if len(buttons) >= 1 and (len(headings) <= 1 or len(buttons) > len(links) / 4):
        return "call to action"
    if images and not headings and len(images) >= 2:
        return "media"
    if len(links) >= 4 and not headings:
        return "link list"
    if len(headings) == 1 and node.rect.y <= 96:
        return "hero"
    if headings:
        return "content"
    return "content" if node.text else "container"


def _confidence(section: SectionSpec, headings: list[RawNode], cards: int) -> float:
    score = 0.3
    if headings:
        score += 0.25
    if section.background:
        score += 0.1
    if cards or section.link_count:
        score += 0.15
    if section.width:
        score += 0.1
    if section.height and section.height > 200:
        score += 0.1
    return min(1.0, score)
