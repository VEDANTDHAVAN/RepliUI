from __future__ import annotations

import json
from pydantic import BaseModel, Field

from ..models.schemas import WebsiteSpec
from .gateway import AIGatewayProvider, LLMProvider


class ImplementationPlan(BaseModel):
    page_structure: list[str] = Field(default_factory=list)
    reusable_components: list[str] = Field(default_factory=list)
    layout_strategy: str = "Responsive semantic sections"
    responsive_strategy: str = "Stack content below 768px"
    color_system: list[str] = Field(default_factory=list)
    typography: list[str] = Field(default_factory=list)
    asset_mapping: list[str] = Field(default_factory=list)
    interactions: list[str] = Field(default_factory=list)
    implementation_notes: list[str] = Field(default_factory=list)


class Planner:
    def __init__(self, provider: LLMProvider | None = None):
        self.provider = provider or AIGatewayProvider.from_environment()

    def create(self, spec: WebsiteSpec) -> ImplementationPlan:
        fallback = ImplementationPlan(
            page_structure=[section.name for section in spec.sections],
            reusable_components=[component.name for component in spec.components],
            color_system=[color.value for color in spec.theme],
            typography=spec.typography.families + spec.typography.sizes,
            asset_mapping=[asset.source_url for asset in spec.assets],
            implementation_notes=["Use semantic HTML", "Keep generated code independent from the source URL"],
        )
        if not isinstance(self.provider, AIGatewayProvider) or not self.provider.configured:
            return fallback
        prompt = json.dumps(spec.model_dump(), separators=(",", ":"))
        try:
            raw = self.provider.complete(system="Return only valid JSON matching the implementation plan schema.", user=prompt, operation="planning")
            return ImplementationPlan.model_validate_json(raw)
        except Exception:
            return fallback
