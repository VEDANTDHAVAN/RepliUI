from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, HttpUrl, field_validator


class AgentState(str, Enum):
    QUEUED = "QUEUED"
    ANALYZING = "ANALYZING"
    ANALYZED = "ANALYZED"
    PLANNING = "PLANNING"
    GENERATING = "GENERATING"
    GENERATED = "GENERATED"
    VALIDATING = "VALIDATING"
    REPAIRING = "REPAIRING"
    READY = "READY"
    MODIFYING = "MODIFYING"
    FAILED = "FAILED"


class ColorSpec(BaseModel):
    name: str
    value: str
    usage: str = ""


class TypographySpec(BaseModel):
    families: list[str] = Field(default_factory=list)
    sizes: list[str] = Field(default_factory=list)
    weights: list[str] = Field(default_factory=list)


class NavigationSpec(BaseModel):
    label: str
    href: str = "#"
    is_external: bool = False


class AssetSpec(BaseModel):
    source_url: str
    local_path: str | None = None
    alt: str = ""
    kind: Literal["image", "svg", "other"] = "image"
    width: int | None = None
    height: int | None = None


class ComponentSpec(BaseModel):
    name: str
    kind: str
    count: int = 1


class SectionSpec(BaseModel):
    name: str
    tag: str = "section"
    heading: str | None = None
    text: str = ""
    image_urls: list[str] = Field(default_factory=list)
    component_hint: str = "content"


class ResponsiveSpec(BaseModel):
    breakpoint: str
    notes: list[str] = Field(default_factory=list)


class WebsiteSpec(BaseModel):
    url: HttpUrl
    title: str = "Untitled website"
    meta_description: str = ""
    viewport: dict[str, int] = Field(default_factory=lambda: {"width": 1440, "height": 900})
    theme: list[ColorSpec] = Field(default_factory=list)
    typography: TypographySpec = Field(default_factory=TypographySpec)
    navigation: list[NavigationSpec] = Field(default_factory=list)
    sections: list[SectionSpec] = Field(default_factory=list)
    assets: list[AssetSpec] = Field(default_factory=list)
    components: list[ComponentSpec] = Field(default_factory=list)
    responsive_rules: list[ResponsiveSpec] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)
    headings: list[str] = Field(default_factory=list)
    paragraphs: list[str] = Field(default_factory=list)
    buttons: list[str] = Field(default_factory=list)
    forms: int = 0
    raw_metadata: dict[str, str] = Field(default_factory=dict)


class GenerationRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Enter a complete public http(s) URL")
        return value


class ModificationRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=1000)


class ValidationError(BaseModel):
    file: str | None = None
    message: str


class InstallResult(BaseModel):
    """Outcome of the dependency installation stage."""

    ok: bool
    command: str = ""
    package_manager: str | None = None
    # True when node_modules was already present and reused instead of reinstalling.
    skipped: bool = False
    reused_node_modules: bool = False
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    errors: list[ValidationError] = Field(default_factory=list)


class ValidationResult(BaseModel):
    success: bool
    stage: str
    errors: list[ValidationError] = Field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    package_manager: str | None = None
    install: InstallResult | None = None


class ProjectManifest(BaseModel):
    project_id: str
    url: str
    title: str = "Untitled website"
    state: AgentState = AgentState.QUEUED
    progress: list[str] = Field(default_factory=list)
    error: str | None = None
    preview_url: str | None = None
    spec: WebsiteSpec | None = None
    validation: ValidationResult | None = None
    modifications: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GenerationResult(BaseModel):
    project_id: str
    state: AgentState
    preview_url: str | None = None
    validation: ValidationResult | None = None
