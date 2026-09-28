"""Deterministic plan construction.

Used when no AI gateway is configured, and as the repair path when a model
response cannot be trusted. Everything is derived from the WebsiteSpec, so the
fallback is a real plan rather than a stub.
"""

from __future__ import annotations

from ..models.schemas import (
    GenerationPlan,
    PlannedAsset,
    PlannedComponent,
    PlannedPage,
    PlannedTheme,
    PlannedTypography,
)

# section_type -> component name. Naming convention only: the types themselves
# are inferred by the analyzer, never matched against a known website.
_COMPONENT_FOR_TYPE = {
    "navigation": "SiteHeader",
    "footer": "SiteFooter",
    "hero": "HeroSection",
    "card grid": "CardGrid",
    "feature grid": "FeatureGrid",
    "call to action": "CallToAction",
    "media": "MediaSection",
    "form": "ContactForm",
    "link list": "LinkList",
    "content": "ContentSection",
    "container": "ContentSection",
}


def build_fallback_plan(spec, source: str = "fallback", warnings: list[str] | None = None) -> GenerationPlan:
    """Build a complete plan from the spec alone, with no model involved."""
    warnings = list(warnings or [])
    section_order = [section.order for section in spec.sections]
    components: list[PlannedComponent] = []
    used: set[str] = set()

    for section in spec.sections:
        name = _component_for(section.section_type, section.order)
        if name in used:
            name = f"{name}{section.order}"
        used.add(name)
        if section.section_type not in _COMPONENT_FOR_TYPE:
            # Silently coercing an unrecognised band into `ContentSection` would
            # hide the miss from whoever reads the plan.
            warnings.append(
                f"Section {section.order} has unrecognised type "
                f"{section.section_type!r}; planned as {name}."
            )
        components.append(
            PlannedComponent(
                name=name,
                kind="component",
                role=section.heading or section.name or section.section_type,
                source_section_indexes=[section.order],
                props={
                    "heading": "string",
                    "text": "string",
                    "background": "string",
                },
                notes=section.component_hint or section.section_type,
            )
        )

    theme = PlannedTheme(
        primary=spec.theme_tokens.primary,
        secondary=spec.theme_tokens.secondary,
        background=spec.theme_tokens.background,
        surface=spec.theme_tokens.surface,
        text=spec.theme_tokens.text,
        muted_text=spec.theme_tokens.muted_text,
        border=spec.theme_tokens.border,
        accent=spec.theme_tokens.accent,
        radii=spec.visual.radii,
        shadows=spec.visual.shadows,
    )
    heading_family = spec.typography.families[0] if spec.typography.families else ""
    body_family = spec.typography.families[-1] if len(spec.typography.families) > 1 else heading_family
    typography = PlannedTypography(
        heading_family=heading_family,
        body_family=body_family,
        scale={**spec.typography.heading_sizes, **({"body": spec.typography.body_size} if spec.typography.body_size else {})},
        notes="Derived from computed styles on the analyzed page.",
    )

    navigation_behavior = (
        "Menu collapses behind a toggle on small screens."
        if spec.responsive and any("navigation collapses" in note for note in spec.responsive.notes)
        else "Menu remains fully expanded at all widths."
    )

    structure = ["app/layout.tsx", "app/page.tsx", "components/"]
    structure.extend(f"components/{component.name}.tsx" for component in components[:10])

    return GenerationPlan(
        project_structure=structure,
        pages=[
            PlannedPage(
                path="/",
                title=spec.title,
                role="landing",
                section_order=section_order,
                notes="Single page mirroring the analyzed page order.",
            )
        ],
        components=components,
        section_order=section_order,
        section_roles={str(section.order): section.section_type for section in spec.sections},
        reusable_components=[component.name for component in components],
        theme=theme,
        typography=typography,
        layout_strategy=_layout_strategy(spec),
        responsive_strategy=(
            "; ".join(spec.responsive.notes[:3]) if spec.responsive else "Single-column layout with fluid widths."
        ),
        navigation_behavior=navigation_behavior,
        assets=[
            PlannedAsset(
                source_url=asset.source_url,
                component=_component_for(_type_for_index(spec, asset.section_index), asset.section_index or 0),
                usage=asset.context or asset.kind,
                alt=asset.alt,
            )
            for asset in spec.assets
            if asset.source_url and not asset.source_url.startswith("data:")
        ][:20],
        implementation_notes=[
            f"Reproduce {len(spec.sections)} detected sections in the captured order.",
            "Assets reference the original URLs; download before shipping.",
            f"Detected {len(spec.assets)} assets and {len(spec.components)} repeated patterns.",
        ],
        source=source,  # type: ignore[arg-type]
        warnings=warnings,
    )


def _component_for(section_type: str, order: int) -> str:
    name = _COMPONENT_FOR_TYPE.get(section_type, "ContentSection")
    return name + ("" if order == 0 else str(order))


def _type_for_index(spec, index: int | None) -> str:
    for section in spec.sections:
        if section.order == index:
            return section.section_type
    return "content"


def _layout_strategy(spec) -> str:
    # A section without a captured layout is real: the analyzer could not read
    # one, so it must not take the whole plan down.
    columns = {
        section.layout.columns
        for section in spec.sections
        if section.layout and section.layout.columns
    }
    width = spec.visual.max_width
    widest = max(columns) if columns else 1
    parts = [f"Content constrained to a {width}px max width." if width else "Full-width content."]
    if widest > 1:
        parts.append(f"Repeating content uses up to {widest} columns.")
    else:
        parts.append("Sections stack in a single column.")
    return " ".join(parts)
