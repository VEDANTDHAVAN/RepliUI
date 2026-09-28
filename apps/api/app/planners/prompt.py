"""Compressed planner input.

The prompt is built from a *projection* of the WebsiteSpec, not from the spec's
JSON dump. This keeps the payload small and token-cheap, and guarantees raw HTML
never reaches the model. Everything here is deterministic; the only AI call in
the pipeline happens after this.
"""

from __future__ import annotations

import json
from typing import Any

from ..models.schemas import WebsiteSpec

# Per-section text budget. Sections are described, not transcribed.
SECTION_TEXT_CHARS = 180
# Cap on distinct values in list-shaped fields, to stop one huge page from
# dominating the prompt.
MAX_ITEMS = 8

SYSTEM_PROMPT = (
    "You are a senior frontend architect. You are given a structured, "
    "machine-extracted description of an existing website and must return a "
    "JSON object describing how to rebuild it in Next.js with React and "
    "TypeScript. Use only the supplied data. Never invent a section that is not "
    "present, and never reference assets that are not listed. Respond with JSON "
    "only, no prose and no code fences."
)

RESPONSE_CONTRACT = {
    "project_structure": ["app/layout.tsx", "app/page.tsx"],
    "pages": [{"path": "/", "title": "...", "role": "landing", "section_order": [0, 1], "notes": "..."}],
    "components": [
        {
            "name": "ComponentName",
            "kind": "section|component",
            "role": "what it renders",
            "source_section_indexes": [0],
            "props": {"propName": "type description"},
            "notes": "...",
        }
    ],
    "section_order": [0, 1, 2],
    "section_roles": {"0": "role of the section at index 0"},
    "reusable_components": ["ComponentName"],
    "theme": {"primary": "#hex", "background": "#hex", "text": "#hex", "radii": [8]},
    "typography": {"heading_family": "...", "body_family": "...", "scale": {"h1": 48, "body": 16}},
    "layout_strategy": "how the page is laid out",
    "responsive_strategy": "how the layout adapts",
    "navigation_behavior": "how the navigation behaves on small screens",
    "assets": [{"source_url": "https://...", "component": "Hero", "usage": "background", "alt": "..."}],
    "implementation_notes": ["short actionable notes"],
}


def build_prompt(spec: WebsiteSpec) -> str:
    """Render the planner prompt from the normalized spec only."""
    payload = compress_spec(spec)
    contract = json.dumps(RESPONSE_CONTRACT, separators=(",", ":"))
    return f"{SYSTEM_PROMPT}\n\nReturn exactly this shape (all keys optional):\n{contract}\n\n"
    f"WEBSITE-SPEC:\n{json.dumps(payload, separators=(',', ':'), ensure_ascii=False)}"


def compress_spec(spec: WebsiteSpec) -> dict[str, Any]:
    """Project a WebsiteSpec into the minimal planner input.

    Sections are reduced to their structural facts. Text is truncated to a
    short excerpt because the generator only needs to know what kind of content
    a section holds, not its verbatim copy.
    """
    tokens = spec.theme_tokens
    return {
        "site": {
            "title": spec.title[:200],
            "description": spec.meta_description[:300],
            "lang": spec.lang,
            "viewport": spec.viewport,
        },
        "theme": {
            "primary": tokens.primary,
            "secondary": tokens.secondary,
            "background": tokens.background,
            "surface": tokens.surface,
            "text": tokens.text,
            "muted_text": tokens.muted_text,
            "border": tokens.border,
            "accent": tokens.accent,
            "palette": [{"value": entry.value, "usage": entry.usage} for entry in spec.theme[:6]],
        },
        "typography": {
            "families": spec.typography.families[:3],
            "heading_sizes": spec.typography.heading_sizes,
            "body_size": spec.typography.body_size,
            "weights": spec.typography.weights[:3],
            "line_heights": spec.typography.line_heights[:2],
        },
        "layout": {
            "spacing": spec.spacing.model_dump(),
            "visual": spec.visual.model_dump(),
            "document_height": spec.document_height,
            "dom_node_count": spec.dom_node_count,
        },
        "navigation": [
            {"label": item.label[:60], "href": item.href[:200], "external": item.is_external}
            for item in spec.navigation[:MAX_ITEMS]
        ],
        "sections": [
            {
                "index": section.order,
                "type": section.section_type,
                "name": section.name[:80],
                "heading": (section.heading or "")[:120],
                "text": section.text[:SECTION_TEXT_CHARS],
                "components": section.child_components[:6],
                "layout": {
                    "display": section.layout.display,
                    "columns": section.layout.columns,
                    "gap": section.layout.gap,
                    "max_width": section.layout.max_width,
                },
                "background": section.background,
                "dimensions": {"w": section.width, "h": section.height, "top_ratio": section.top_ratio},
                "links": section.link_count,
                "assets": section.asset_count,
            }
            for section in spec.sections
        ],
        "components": [
            {
                "name": item.name,
                "kind": item.kind,
                "count": item.count,
                "role": item.role,
                "sample_text": [text[:60] for text in item.sample_text[:2]],
            }
            for item in spec.components[:MAX_ITEMS]
        ],
        "responsive": spec.responsive.model_dump() if spec.responsive else None,
        "assets": [
            {
                "source_url": item.source_url[:300],
                "kind": item.kind,
                "alt": item.alt[:100],
                "dimensions": {"w": item.width, "h": item.height},
                "section": item.section_index,
            }
            for item in spec.assets[:12]
        ],
        "forms": {"count": spec.forms, "fields": spec.form_fields[:10]},
        "content": {
            "headings": spec.headings[:10],
            "buttons": spec.buttons[:8],
            "paragraphs": [text[:140] for text in spec.paragraphs[:3]],
        },
        "screenshots": [
            {"device": shot.device, "width": shot.viewport_width, "height": shot.viewport_height}
            for shot in spec.screenshot_details
        ],
    }
