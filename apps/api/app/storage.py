from __future__ import annotations

import json
import os
from pathlib import Path

from .models.schemas import ProjectManifest

ROOT = Path(__file__).resolve().parents[3]
PROJECTS_DIR = Path(os.getenv("GENERATED_PROJECTS_DIR", ROOT / "generated" / "projects"))
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", ROOT / "storage"))
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


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
