"""Typed payloads returned by the in-page extraction scripts.

Keeping these separate from the normalized `models/schemas` means the raw
browser output is validated at the boundary, and the rest of the pipeline works
with a known, strongly typed shape.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(value: str) -> str:
    """`child_elements` -> `childElements`.

    The in-page scripts emit JavaScript-style camelCase, so every raw payload
    field carries a camelCase alias. Without this, `childElements` and friends
    silently fall back to their defaults and the detectors see an empty page.
    Explicit aliases (e.g. `class_` -> `class`) take precedence over the
    generator, and `populate_by_name` keeps snake_case input working for tests.
    """
    head, *rest = value.split("_")
    return head + "".join(word.title() for word in rest)


RAW_CONFIG = ConfigDict(populate_by_name=True, alias_generator=_to_camel)


class NodeRect(BaseModel):
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    model_config = RAW_CONFIG


class NodeImage(BaseModel):
    src: str = ""
    alt: str = ""
    natural_width: int = 0
    natural_height: int = 0

    model_config = RAW_CONFIG


class NodeSvg(BaseModel):
    outer_length: int = 0
    view_box: str = ""
    label: str = ""

    model_config = RAW_CONFIG


class NodeForm(BaseModel):
    action: str = ""
    method: str = "get"
    fields: list[str] = Field(default_factory=list)

    model_config = RAW_CONFIG


class NodeAttributes(BaseModel):
    class_: str = Field(default="", alias="class")
    id: str = ""

    model_config = RAW_CONFIG


class RawNode(BaseModel):
    id: str | None = None
    tag: str = ""
    depth: int = 0
    visible: bool = False
    rect: NodeRect = Field(default_factory=NodeRect)
    styles: dict[str, str] = Field(default_factory=dict)
    text: str = ""
    aria_label: str = ""
    role: str = ""
    href: str = ""
    child_elements: int = 0
    selector: str = ""
    attributes: NodeAttributes = Field(default_factory=NodeAttributes)
    image: NodeImage | None = None
    svg: NodeSvg | None = None
    form: NodeForm | None = None

    model_config = RAW_CONFIG


class RawHeading(BaseModel):
    level: int = 1
    text: str = ""

    model_config = RAW_CONFIG


class RawLink(BaseModel):
    href: str = ""
    text: str = ""

    model_config = RAW_CONFIG


class RepeatedGroup(BaseModel):
    key: str = ""
    count: int = 0
    tag: str = ""
    parent_tag: str = ""
    parent_display: str = ""
    parent_columns: int = 0
    height_spread: int = 0
    average_height: int = 0
    sample_text: list[str] = Field(default_factory=list)
    selector: str = ""

    model_config = RAW_CONFIG


class RawDocument(BaseModel):
    title: str = ""
    lang: str = ""
    meta: dict[str, str] = Field(default_factory=dict)
    headings: list[RawHeading] = Field(default_factory=list)
    paragraphs: list[str] = Field(default_factory=list)
    buttons: list[str] = Field(default_factory=list)
    links: list[RawLink] = Field(default_factory=list)
    node_count: int = 0
    inline_svg_count: int = 0
    form_count: int = 0

    model_config = RAW_CONFIG


class RawLayout(BaseModel):
    groups: list[RepeatedGroup] = Field(default_factory=list)
    document_height: int = 0

    model_config = RAW_CONFIG


class RawExtraction(BaseModel):
    nodes: list[RawNode] = Field(default_factory=list)
    truncated: bool = False
    scroll_height: int = 0

    model_config = RAW_CONFIG


class RawViewport(BaseModel):
    device: str = "desktop"
    width: int = 1440
    height: int = 900
    is_mobile: bool = False
    scale: float = 1.0
    nodes: list[RawNode] = Field(default_factory=list)
    document: RawDocument = Field(default_factory=RawDocument)
    layout: RawLayout = Field(default_factory=RawLayout)
    truncated: bool = False
    document_height: int = 0

    model_config = RAW_CONFIG


class ViewportReading(BaseModel):
    """A full observation of the page at one viewport."""

    device: str
    width: int
    height: int
    is_mobile: bool
    scale: float
    document: RawDocument
    nodes: list[RawNode]
    layout: RawLayout
    truncated: bool
    document_height: int
    max_nodes: int = 0
