from __future__ import annotations

import json
import os
from pathlib import Path

from typing import TYPE_CHECKING

from .models.schemas import ProjectManifest

if TYPE_CHECKING:  # pragma: no cover
    from .models.schemas import GenerationPlan, WebsiteSpec

ROOT = Path(__file__).resolve().parents[3]
PROJECTS_DIR = Path(os.getenv("GENERATED_PROJECTS_DIR", ROOT / "generated" / "projects"))
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", ROOT / "storage"))
ANALYSES_DIR = STORAGE_DIR / "analyses"
SCREENSHOTS_DIR = STORAGE_DIR / "screenshots"
for _directory in (PROJECTS_DIR, STORAGE_DIR, ANALYSES_DIR, SCREENSHOTS_DIR):
    _directory.mkdir(parents=True, exist_ok=True)


def project_dir(project_id: str) -> Path:
    if not project_id or Path(project_id).name != project_id or project_id in {".", ".."}:
        raise ValueError("Invalid project id")
    path = (PROJECTS_DIR / project_id).resolve()
    if PROJECTS_DIR.resolve() not in path.parents:
        raise ValueError("Project path escapes storage")
    return path


def manifest_path(project_id: str) -> Path:
    return project_dir(project_id) / "manifest.json"


def save_manifest(manifest: ProjectManifest) -> None:
    directory = project_dir(manifest.project_id)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path(manifest.project_id).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


def load_manifest(project_id: str) -> ProjectManifest:
    return ProjectManifest.model_validate_json(manifest_path(project_id).read_text(encoding="utf-8"))


def list_manifests() -> list[ProjectManifest]:
    result: list[ProjectManifest] = []
    for path in PROJECTS_DIR.glob("*/manifest.json"):
        try:
            result.append(ProjectManifest.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return sorted(result, key=lambda item: item.updated_at, reverse=True)


def _scoped_child(base: Path, project_id: str) -> Path:
    """Resolve ``base/project_id`` and refuse anything that escapes ``base``."""
    if not project_id or Path(project_id).name != project_id or project_id in {".", ".."}:
        raise ValueError("Invalid project id")
    path = (base / project_id).resolve()
    if base.resolve() not in path.parents:
        raise ValueError("Path escapes storage")
    return path


def analysis_dir(project_id: str) -> Path:
    path = _scoped_child(ANALYSES_DIR, project_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def website_spec_path(project_id: str) -> Path:
    return analysis_dir(project_id) / "website-spec.json"


def generation_plan_path(project_id: str) -> Path:
    return analysis_dir(project_id) / "generation-plan.json"


def save_website_spec(project_id: str, spec: "WebsiteSpec") -> Path:
    path = website_spec_path(project_id)
    path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_website_spec(project_id: str) -> "WebsiteSpec":
    from .models.schemas import WebsiteSpec

    return WebsiteSpec.model_validate_json(website_spec_path(project_id).read_text(encoding="utf-8"))


def save_generation_plan(project_id: str, plan: "GenerationPlan") -> Path:
    path = generation_plan_path(project_id)
    path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_generation_plan(project_id: str) -> "GenerationPlan":
    from .models.schemas import GenerationPlan

    return GenerationPlan.model_validate_json(generation_plan_path(project_id).read_text(encoding="utf-8"))


def screenshot_dir(project_id: str) -> Path:
    """Per-project screenshot directory; one project can never overwrite another's."""
    path = _scoped_child(SCREENSHOTS_DIR, project_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_dir(project_id: str) -> Path:
    """Directory holding the project's static build output, if it exists."""
    return project_dir(project_id) / "out"


def resolve_preview_file(project_id: str, relpath: str) -> Path:
    """Resolve a preview asset path inside the project's static export.

    The path is treated as a sequence of components, so ``../`` cannot escape
    the export directory. A missing file raises ``FileNotFoundError``.
    """
    base = export_dir(project_id)
    if not relpath:
        relpath = "index.html"
    candidate = (base / relpath).resolve()
    if base.resolve() not in candidate.parents and candidate != base.resolve():
        raise ValueError("Preview path escapes the project directory")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def has_preview(project_id: str) -> bool:
    """True when the project's static export is present and complete."""
    return (export_dir(project_id) / "index.html").is_file()


def screenshot_path(project_id: str, label: str) -> Path:
    safe = "".join(ch for ch in label if ch.isalnum() or ch in {"-", "_"})[:40] or "shot"
    path = (screenshot_dir(project_id) / f"{safe}.png").resolve()
    if screenshot_dir(project_id).resolve() not in path.parents:
        raise ValueError("Invalid screenshot label")
    return path
