"""Offline tests for structured, targeted natural-language modifications."""

from __future__ import annotations

from app.modifiers import ModificationAgent
from app.repair.patch import apply_patch


def test_fallback_modifier_targets_sticky_nav(projects_dir):
    project_id = "modifier0001"
    root = projects_dir / project_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "app").mkdir(exist_ok=True)
    (root / "app" / "styles.css").write_text("--accent:#d47b56;", encoding="utf-8")
    (root / "app" / "page.tsx").write_text("<div></div>", encoding="utf-8")
    plan = ModificationAgent(gateway=type("NoGateway", (), {"configured": False})()).build_plan(project_id, "Make the navbar sticky")
    assert plan.changes[0].file == "app/styles.css"
    result = apply_patch(project_id, plan.changes)
    assert result.ok
    assert "position:sticky" in (root / "app" / "styles.css").read_text(encoding="utf-8")


def test_fallback_modifier_rejects_unknown_instruction(projects_dir):
    project_id = "modifier0002"
    root = projects_dir / project_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "app").mkdir(exist_ok=True)
    (root / "app" / "styles.css").write_text("--accent:#d47b56;", encoding="utf-8")
    (root / "app" / "page.tsx").write_text("<div></div>", encoding="utf-8")
    plan = ModificationAgent(gateway=type("NoGateway", (), {"configured": False})()).build_plan(project_id, "Run a shell command")
    assert plan.changes == []
