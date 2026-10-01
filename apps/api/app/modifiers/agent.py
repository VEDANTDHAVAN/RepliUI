from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from ..ai.gateway import AIGatewayProvider
from ..repair.patch import RepairChange
from ..storage import project_dir


class ModificationPlan(BaseModel):
    summary: str = ""
    target_files: list[str] = Field(default_factory=list)
    changes: list[RepairChange] = Field(default_factory=list)


class ModificationAgent:
    """Create a small, validated edit plan without regenerating a project."""

    def __init__(self, gateway: AIGatewayProvider | None = None):
        self.gateway = gateway or AIGatewayProvider.from_environment()

    def build_plan(self, project_id: str, instruction: str) -> ModificationPlan:
        root = project_dir(project_id)
        page = root / "app" / "page.tsx"
        css = root / "app" / "styles.css"
        files = {"app/page.tsx": page.read_text(encoding="utf-8"), "app/styles.css": css.read_text(encoding="utf-8")}
        if self.gateway.configured:
            try:
                response = self.gateway.complete(
                    system="Return only JSON with summary, target_files, and changes. Changes must use exact replace/append/delete edits inside the generated project. Never include secrets or commands.",
                    user=json.dumps({"instruction": instruction, "files": files}, separators=(",", ":")),
                    operation="modification",
                )
                return ModificationPlan.model_validate_json(self._json(response))
            except Exception:
                pass
        return self._fallback(instruction, files)

    def _fallback(self, instruction: str, files: dict[str, str]) -> ModificationPlan:
        lower = instruction.lower()
        changes: list[RepairChange] = []
        targets: list[str] = []
        if "sticky" in lower and "nav" in lower:
            targets.append("app/styles.css")
            changes.append(RepairChange(file="app/styles.css", action="append", replacement="\nnav{position:sticky;top:0;background:var(--paper);z-index:5}\n", reason="Make the navigation remain visible while scrolling."))
        if "blue" in lower or "primary color" in lower:
            match = re.search(r"--accent:[^;]+;", files["app/styles.css"])
            if match:
                targets.append("app/styles.css")
                changes.append(RepairChange(file="app/styles.css", original=match.group(0), replacement="--accent:#2563eb;", reason="Set the primary accent token to blue."))
        if "taller" in lower and "hero" in lower:
            targets.append("app/styles.css")
            changes.append(RepairChange(file="app/styles.css", action="append", replacement="\n.hero{min-height:70vh}\n", reason="Increase hero vertical space."))
        if "testimonial" in lower and ("add" in lower or "include" in lower):
            anchor = "</div><footer>"
            if anchor in files["app/page.tsx"]:
                targets.append("app/page.tsx")
                changes.append(RepairChange(file="app/page.tsx", original=anchor, replacement="<section className='section testimonials'><div><p className='eyebrow'>TESTIMONIALS</p><h2>What people are saying</h2><p>Thoughtful work starts with a clear point of view.</p></div></section></div><footer>", reason="Add a reusable testimonial section before the footer."))
        summary = "Prepared targeted changes." if changes else "No safe targeted edit matched this instruction."
        return ModificationPlan(summary=summary, target_files=list(dict.fromkeys(targets)), changes=changes)

    @staticmethod
    def _json(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        start, end = text.find("{"), text.rfind("}")
        return text[start:end + 1] if start >= 0 and end > start else text
