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


class SpacingSpec(BaseModel):
    """Representative spacing scale in px, derived from computed padding/gap."""

    xs: int | None = None
    sm: int | None = None
    md: int | None = None
    lg: int | None = None
    xl: int | None = None
    section_gap: int | None = None
    unit: int | None = None


class VisualSpec(BaseModel):
    """Representative radii, borders and shadows."""

    radii: list[int] = Field(default_factory=list)
    border_widths: list[int] = Field(default_factory=list)
    shadows: list[str] = Field(default_factory=list)
    max_width: int | None = None


class LayoutSpec(BaseModel):
    display: str = "block"
    columns: int = 1
    gap: int | None = None
    padding: tuple[int, int, int, int] = (0, 0, 0, 0)
    max_width: int | None = None
    align_items: str = "stretch"
    justify_content: str = "start"


class TypographySpec(BaseModel):
    families: list[str] = Field(default_factory=list)
    sizes: list[str] = Field(default_factory=list)
    weights: list[str] = Field(default_factory=list)
    heading_sizes: dict[str, int] = Field(default_factory=dict)
    body_size: int | None = None
    line_heights: list[str] = Field(default_factory=list)
    letter_spacings: list[str] = Field(default_factory=list)


class ThemeSpec(BaseModel):
    """Named design tokens. `colors` remains the source of truth; these are
    resolved role assignments derived from observed frequency."""

    primary: str | None = None
    secondary: str | None = None
    background: str | None = None
    surface: str | None = None
    text: str | None = None
    muted_text: str | None = None
    border: str | None = None
    accent: str | None = None


class NavigationSpec(BaseModel):
    label: str
    href: str = "#"
    is_external: bool = False
    aria_label: str = ""
    is_active: bool = False


class AssetSpec(BaseModel):
    source_url: str
    local_path: str | None = None
    alt: str = ""
    kind: Literal["image", "svg", "video", "other"] = "image"
    width: int | None = None
    height: int | None = None
    media_type: str = ""
    context: str = ""
    # Section index the asset was observed in, for generator-side placement.
    section_index: int | None = None


class ComponentSpec(BaseModel):
    name: str
    kind: str
    count: int = 1
    role: str = ""
    sample_text: list[str] = Field(default_factory=list)
    selectors: list[str] = Field(default_factory=list)
    section_indexes: list[int] = Field(default_factory=list)


class SectionSpec(BaseModel):
    name: str
    tag: str = "section"
    heading: str | None = None
    text: str = ""
    image_urls: list[str] = Field(default_factory=list)
    component_hint: str = "content"
    order: int = 0
    # Deterministic classification derived from observed structure, never a
    # hardcoded website template: hero, navigation, feature grid, cards, cta,
    # media, form, pricing table, quote, faq, content, footer, unknown.
    section_type: str = "content"
    child_components: list[str] = Field(default_factory=list)
    layout: LayoutSpec = Field(default_factory=LayoutSpec)
    background: str = ""
    text_color: str = ""
    spacing: SpacingSpec = Field(default_factory=SpacingSpec)
    visual: VisualSpec = Field(default_factory=VisualSpec)
    width: int | None = None
    height: int | None = None
    top: int | None = None
    top_ratio: float = 0.0
    link_count: int = 0
    asset_count: int = 0
    confidence: float = 0.0


class ResponsiveSpec(BaseModel):
    breakpoint: str
    notes: list[str] = Field(default_factory=list)
    width: int = 0
    height: int = 0
    is_mobile: bool = False
    navigation_items: int = 0
    visible_sections: int = 0
    max_columns: int = 0
    heading_size: int | None = None
    body_size: int | None = None
    content_width: int | None = None
    hidden_component_kinds: list[str] = Field(default_factory=list)
    shown_component_kinds: list[str] = Field(default_factory=list)


class ScreenshotSpec(BaseModel):
    path: str
    label: str
    width: int
    height: int
    viewport_width: int
    viewport_height: int
    device: str = "desktop"
    full_page: bool = False
    bytes: int = 0
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ViewportSpec(BaseModel):
    width: int = 1440
    height: int = 900
    device: str = "desktop"
    device_scale_factor: float = 1.0
    is_mobile: bool = False


class WebsiteSpec(BaseModel):
    url: HttpUrl
    final_url: str = ""
    title: str = "Untitled website"
    meta_description: str = ""
    lang: str = ""
    viewport: ViewportSpec = Field(default_factory=ViewportSpec)
    theme: list[ColorSpec] = Field(default_factory=list)
    theme_tokens: ThemeSpec = Field(default_factory=ThemeSpec)
    typography: TypographySpec = Field(default_factory=TypographySpec)
    navigation: list[NavigationSpec] = Field(default_factory=list)
    sections: list[SectionSpec] = Field(default_factory=list)
    assets: list[AssetSpec] = Field(default_factory=list)
    components: list[ComponentSpec] = Field(default_factory=list)
    responsive_rules: list[ResponsiveSpec] = Field(default_factory=list)
    responsive: ResponsiveSpec | None = None
    screenshots: list[str] = Field(default_factory=list)
    screenshot_details: list[ScreenshotSpec] = Field(default_factory=list)
    headings: list[str] = Field(default_factory=list)
    paragraphs: list[str] = Field(default_factory=list)
    buttons: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    forms: int = 0
    form_fields: list[str] = Field(default_factory=list)
    links_count: int = 0
    dom_node_count: int = 0
    document_height: int = 0
    spacing: SpacingSpec = Field(default_factory=SpacingSpec)
    visual: VisualSpec = Field(default_factory=VisualSpec)
    raw_metadata: dict[str, str] = Field(default_factory=dict)
    # Set when extraction was partial so downstream stages know to treat the
    # spec as a lower-confidence input rather than a complete capture.
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    analysis_duration_ms: int = 0


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
    plan: GenerationPlan | None = None
    validation: ValidationResult | None = None
    modifications: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GenerationResult(BaseModel):
    project_id: str
    state: AgentState
    preview_url: str | None = None
    validation: ValidationResult | None = None


# ---------------------------------------------------------------------------
# Generation plan (AI planner output)
# ---------------------------------------------------------------------------


class PlannedComponent(BaseModel):
    name: str
    kind: str = "component"
    role: str = ""
    source_section_indexes: list[int] = Field(default_factory=list)
    props: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


class PlannedPage(BaseModel):
    path: str = "/"
    title: str = ""
    role: str = "landing"
    section_order: list[int] = Field(default_factory=list)
    notes: str = ""


class PlannedAsset(BaseModel):
    source_url: str
    component: str = ""
    usage: str = ""
    alt: str = ""


class PlannedTheme(BaseModel):
    primary: str | None = None
    secondary: str | None = None
    background: str | None = None
    surface: str | None = None
    text: str | None = None
    muted_text: str | None = None
    border: str | None = None
    accent: str | None = None
    radii: list[int] = Field(default_factory=list)
    shadows: list[str] = Field(default_factory=list)


class PlannedTypography(BaseModel):
    heading_family: str = ""
    body_family: str = ""
    scale: dict[str, int] = Field(default_factory=dict)
    notes: str = ""


class GenerationPlan(BaseModel):
    """Structured output of the AI planner, consumed by a future code generator.

    Every field is optional-with-default so a partially usable model response
    still validates; the planner records what was missing rather than failing.
    """

    project_structure: list[str] = Field(default_factory=list)
    pages: list[PlannedPage] = Field(default_factory=list)
    components: list[PlannedComponent] = Field(default_factory=list)
    section_order: list[int] = Field(default_factory=list)
    section_roles: dict[str, str] = Field(default_factory=dict)
    reusable_components: list[str] = Field(default_factory=list)
    theme: PlannedTheme = Field(default_factory=PlannedTheme)
    typography: PlannedTypography = Field(default_factory=PlannedTypography)
    layout_strategy: str = ""
    responsive_strategy: str = ""
    navigation_behavior: str = ""
    assets: list[PlannedAsset] = Field(default_factory=list)
    implementation_notes: list[str] = Field(default_factory=list)
    framework: str = "next"
    source: Literal["ai", "fallback", "manual"] = "fallback"
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int = 0
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
