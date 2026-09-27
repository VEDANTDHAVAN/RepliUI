"""End-to-end pipeline test: analyze -> plan -> generate -> install -> build.

Exercises the real `pipeline` function against a real generated project and a
real package manager, so `READY` is only reached when the production build
actually succeeded.
"""

from __future__ import annotations

import shutil

import pytest

from app import main as api
from app.models.schemas import AgentState, GenerationRequest, ProjectManifest
from app.storage import load_manifest, save_manifest
from app.validators import BuildValidator


class _StubAnalyzer:
    """Deterministic analyzer: no network, no browser."""

    def __init__(self, spec_factory) -> None:
        self._spec_factory = spec_factory

    def analyze(self, url: str, project_id: str):
        return self._spec_factory()


class _StubPlanner:
    def create(self, spec):
        return {"layout": "single-column"}


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("pnpm") is None, reason="pnpm is not installed")
def test_pipeline_reaches_ready_only_after_a_real_build(monkeypatch, projects_dir, spec):
    monkeypatch.setattr(api, "WebsiteAnalyzer", lambda: _StubAnalyzer(lambda: spec))
    monkeypatch.setattr(api, "Planner", _StubPlanner)
    monkeypatch.setattr(api, "BuildValidator", lambda: BuildValidator(prefer="pnpm"))

    project_id = "pipee2e0001"
    manifest = ProjectManifest(project_id=project_id, url="https://example.com", title=spec.title)
    save_manifest(manifest)

    api.pipeline(project_id)

    result = load_manifest(project_id)
    assert result.state is AgentState.READY, f"pipeline did not reach READY: {result.progress}\n{result.error}\n{result.validation}"
    assert result.validation is not None
    assert result.validation.success is True
    assert result.validation.package_manager == "pnpm"
    assert result.validation.install is not None and result.validation.install.ok is True
    assert result.validation.stage == "build"
    # A READY project must have genuinely produced a build artifact.
    assert (projects_dir / project_id / ".next").is_dir()
    assert "next build" in result.validation.stdout


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("pnpm") is None, reason="pnpm is not installed")
def test_pipeline_fails_when_the_build_fails(monkeypatch, projects_dir, spec):
    """A broken build must never be reported as READY.

    The project is installed for real first, then a broken module is added to the
    generated source and the pipeline is re-run, so the failure comes from a
    genuine `pnpm build` rather than a stubbed stage. The broken file is one the
    generator does not own, so regeneration does not overwrite it.
    """
    from app.generators import ProjectGenerator

    project_id = "pipee2e0002"
    root = ProjectGenerator().generate(project_id, spec)

    # A real, successful install so the later build reuses it.
    warmup = BuildValidator(prefer="pnpm").install(root, "pnpm")
    assert warmup.ok is True, f"{warmup.stdout}\n{warmup.stderr}\n{warmup.errors}"

    (root / "app" / "broken.tsx").write_text(
        "export const broken: number = 'definitely not a number';\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api, "WebsiteAnalyzer", lambda: _StubAnalyzer(lambda: spec))
    monkeypatch.setattr(api, "Planner", _StubPlanner)
    monkeypatch.setattr(api, "BuildValidator", lambda: BuildValidator(prefer="pnpm"))
    save_manifest(ProjectManifest(project_id=project_id, url="https://example.com", title=spec.title))

    api.pipeline(project_id)

    result = load_manifest(project_id)
    assert result.state is AgentState.FAILED
    assert result.validation is not None
    assert result.validation.success is False
    assert result.validation.stage == "build"
