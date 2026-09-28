"""Shared RawNode builders for the deterministic extraction tests.

These construct the same payload shape the browser scripts return, so the
extraction modules can be tested without launching Chromium.
"""

from __future__ import annotations

from app.analyzers import ViewportReading
from app.analyzers.raw_models import (
    NodeAttributes,
    NodeImage,
    NodeRect,
    RawDocument,
    RawLayout,
    RawNode,
    RawViewport,
    RepeatedGroup,
)


def node(
    *,
    tag: str = "div",
    text: str = "",
    x: int = 0,
    y: int = 0,
    width: int = 1200,
    height: int = 200,
    depth: int = 1,
    visible: bool = True,
    selector: str = "",
    class_name: str = "",
    element_id: str = "",
    href: str = "",
    role: str = "",
    child_elements: int = 0,
    styles: dict[str, str] | None = None,
    image: dict | None = None,
    svg: dict | None = None,
    form: dict | None = None,
    node_id: str | None = None,
) -> RawNode:
    return RawNode(
        id=node_id,
        tag=tag,
        depth=depth,
        visible=visible,
        rect=NodeRect(x=x, y=y, width=width, height=height),
        styles=styles or {},
        text=text,
        aria_label="",
        role=role,
        href=href,
        child_elements=child_elements,
        selector=selector,
        attributes=NodeAttributes(class_=class_name, id=element_id),
        image=NodeImage(**image) if image else None,
        svg=svg,
        form=form,
    )


def reading(
    nodes: list[RawNode] | None = None,
    *,
    width: int = 1440,
    height: int = 900,
    is_mobile: bool = False,
    groups: list[RepeatedGroup] | None = None,
    document: RawDocument | None = None,
    truncated: bool = False,
    max_nodes: int = 0,
    document_height: int | None = None,
) -> ViewportReading:
    total = document_height if document_height is not None else height
    return ViewportReading(
        device="mobile" if is_mobile else "desktop",
        width=width,
        height=height,
        is_mobile=is_mobile,
        scale=1.0,
        document=document or RawDocument(title="Fixture", lang="en"),
        nodes=nodes or [],
        layout=RawLayout(groups=groups or [], document_height=total),
        truncated=truncated,
        document_height=total,
        max_nodes=max_nodes,
    )


def group(
    *,
    key: str = "div.card",
    count: int = 3,
    tag: str = "div",
    parent_tag: str = "div",
    parent_display: str = "grid",
    parent_columns: int = 3,
    height_spread: int = 0,
    average_height: int = 180,
    sample_text: list[str] | None = None,
    selector: str = "div.card",
) -> RepeatedGroup:
    return RepeatedGroup(
        key=key,
        count=count,
        tag=tag,
        parent_tag=parent_tag,
        parent_display=parent_display,
        parent_columns=parent_columns,
        height_spread=height_spread,
        average_height=average_height,
        sample_text=sample_text or [],
        selector=selector,
    )


def viewport(**kwargs) -> RawViewport:
    """A raw payload as returned by the browser script."""
    return RawViewport(**kwargs)
