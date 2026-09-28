"""Asset description extraction.

Assets are *described*, not downloaded: the generator needs a source URL, type,
intrinsic dimensions, alt text and the section the asset appeared in so it can
decide what to reference. Nothing is fetched here.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ..models.schemas import AssetSpec
from .raw_models import RawNode

SVG_PATTERN = re.compile(r"\.svg(\?|#|$)", re.IGNORECASE)
VIDEO_PATTERN = re.compile(r"\.(mp4|webm|ogg|mov)(\?|#|$)", re.IGNORECASE)
ICON_PATTERN = re.compile(r"(icon|logo|favicon|glyph|badge)", re.IGNORECASE)
DATA_URI_PATTERN = re.compile(r"^data:(image|video)/([a-zA-Z0-9.+-]+);base64,")


def is_svg(url: str) -> bool:
    return bool(SVG_PATTERN.search(url)) or url.startswith("data:image/svg+xml")


def classify(url: str) -> str:
    """Kind of the asset, derived from the URL's extension or data URI."""
    if is_svg(url):
        return "svg"
    if VIDEO_PATTERN.search(url):
        return "video"
    if url.lower().startswith(("http://", "https://", "/", "data:")):
        return "image"
    return "other"


def is_iconish(url: str, alt: str = "") -> bool:
    return bool(ICON_PATTERN.search(url)) or bool(ICON_PATTERN.search(alt))


def extract_assets(nodes: list[RawNode], base_url: str, limit: int = 40) -> list[AssetSpec]:
    """Collect image, SVG and video references with their context."""
    assets: list[AssetSpec] = []
    seen: set[str] = set()

    for node in nodes:
        for url, alt, width, height, context in _candidates(node):
            resolved = _resolve(url, base_url)
            if not resolved or resolved in seen:
                continue
            # Inline data URIs are described by kind but not carried verbatim.
            reference = "" if resolved.startswith("data:") else resolved
            if reference and reference in seen:
                continue
            seen.add(reference or resolved)
            assets.append(
                AssetSpec(
                    source_url=reference or f"data:{classify(resolved)}",
                    alt=alt[:200],
                    kind=classify(resolved),  # type: ignore[arg-type]
                    width=width or None,
                    height=height or None,
                    media_type=_media_type(resolved),
                    context=context[:120],
                )
            )
            if len(assets) >= limit:
                return assets
    return assets


def _candidates(node: RawNode) -> list[tuple[str, str, int, int, str]]:
    results: list[tuple[str, str, int, int, str]] = []
    context = node.aria_label or node.attributes.class_[:80] or node.tag
    if node.image is not None and node.image.src:
        results.append((node.image.src, node.image.alt, node.image.natural_width, node.image.natural_height, context))
    if node.svg is not None and node.svg.outer_length:
        # Inline SVGs have no URL; the caller receives a kind-only descriptor.
        results.append((f"inline-svg:{node.selector[:60]}", node.svg.label or node.aria_label, 0, 0, context))
    background = node.styles.get("background-image", "")
    for url in re.findall(r"url\(['\"]?([^'\")]+)['\"]?\)", background or ""):
        results.append((url, "", 0, 0, f"background:{context}"))
    return results


def _resolve(url: str, base_url: str) -> str:
    if not url or url.startswith(("javascript:", "about:", "#")):
        return ""
    if url.startswith("data:"):
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not base_url:
        return url
    return urljoin(base_url, url)


def _media_type(url: str) -> str:
    match = DATA_URI_PATTERN.match(url)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    suffix = Path_suffix(url)
    return suffix.lstrip(".").lower() if suffix else ""


def Path_suffix(url: str) -> str:
    path = urlparse(url).path
    return path[path.rfind(".") :] if "." in path.rsplit("/", 1)[-1] else ""


def is_same_origin(url: str, base_url: str) -> bool:
    if not url or not base_url or url.startswith("data:"):
        return True
    return urlparse(url).netloc == urlparse(base_url).netloc
