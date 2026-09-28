"""Document-level extraction: metadata, headings, navigation, forms, links.

All of it is derived from the in-page document payload, so nothing here needs a
network round trip or a model.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from ..models.schemas import NavigationSpec
from .raw_models import RawDocument, RawNode

# Items further down the document stop being treated as primary navigation.
NAVIGATION_DEPTH_LIMIT = 3


def meta_value(document: RawDocument, *keys: str) -> str:
    for key in keys:
        value = document.meta.get(key)
        if value:
            return value
    return ""


def extract_navigation(nodes: list[RawNode], base_url: str) -> list[NavigationSpec]:
    """Primary navigation: the links inside the first header/nav landmark."""
    container = _navigation_container(nodes)
    links = []
    if container is not None:
        top, left = container.rect.y, container.rect.x
        bottom, right = top + container.rect.height, left + container.rect.width
        links = [
            node
            for node in nodes
            if node.tag == "a"
            and node.visible
            and node.rect.width > 0
            and top <= node.rect.y <= bottom
            and left <= node.rect.x <= right
        ]
    if not links:
        # Fall back to the first links in document order.
        links = [node for node in nodes if node.tag == "a" and node.visible and node.href][:12]

    items: list[NavigationSpec] = []
    seen: set[tuple[str, str]] = set()
    for link in links:
        label = (link.text or link.aria_label or "").replace("\n", " ").strip()[:80]
        href = link.href.strip()
        if not label and not href:
            continue
        key = (label.lower(), href)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            NavigationSpec(
                label=label or href,
                href=_absolute(href, base_url),
                is_external=_is_external(href, base_url),
                aria_label=link.aria_label[:120],
                is_active=link.attributes.class_.split("active")[-1] == link.attributes.class_[-6:],
            )
        )
        if len(items) >= 20:
            break
    return items


def _navigation_container(nodes: list[RawNode]) -> RawNode | None:
    candidates = [
        node
        for node in nodes
        if node.visible and (node.tag == "nav" or node.tag == "header") and node.rect.height > 0
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda node: (node.rect.y, -node.rect.height))
    return candidates[0]


def _absolute(href: str, base_url: str) -> str:
    if not href:
        return ""
    if href.startswith(("http://", "https://", "mailto:", "tel:")):
        return href
    if not base_url:
        return href
    return urljoin(base_url, href)


def _is_external(href: str, base_url: str) -> bool:
    if not href or not base_url.startswith(("http://", "https://")):
        return False
    if href.startswith(("mailto:", "tel:", "#")):
        return False
    return urlparse(_absolute(href, base_url)).netloc != urlparse(base_url).netloc


def extract_form_fields(document: RawDocument, nodes: list[RawNode]) -> list[str]:
    fields: list[str] = []
    for node in nodes:
        if node.form is not None:
            fields.extend(node.form.fields)
    return list(dict.fromkeys(field for field in fields if field))[:25]


def dedupe(values: list[str], limit: int) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))[:limit]
