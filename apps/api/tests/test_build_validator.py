"""Validator lifecycle: inspect -> install -> build.

The marked tests perform a real network install and a real Next.js production
build; they are the regression coverage for this lifecycle. To skip just those:

    pytest -m "not slow"
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app.generators import ProjectGenerator
from app.models.schemas import InstallResult
from app.storage import project_dir
from app.validators import BuildValidator
from app.validators import package_manager as pm

HAS_PNPM = shutil.which("pnpm") is not None
requires_pnpm = pytest.mark.skipif(not HAS_PNPM, reason="pnpm is not installed")


class _Completed:
    """Stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestInspect:
    def test_missing_package_json_fails_at_inspect(self, projects_dir):
        result = BuildValidator().validate("doesnotexist")
        assert result.success is False
        assert result.stage == "inspect"
        assert "package.json" in result.errors[0].message
        assert result.install is None

    def test_generated_project_passes_inspect(self, projects_dir, spec):
        root = ProjectGenerator().generate("inspect0001", spec)
        found, failure = BuildValidator().inspect("inspect0001")
        assert failure is None
        assert found == root


class TestInstallFailures:
    def test_unresolvable_dependency_fails_install_not_build(self, projects_dir):
        root = project_dir("brokeninstall")
        root.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps({"scripts": {"build": "next build"}, "dependencies": {"this-package-does-not-exist-replui": "9.9.9"}}),
            encoding="utf-8",
        )
        result = BuildValidator().validate("brokeninstall")
        assert result.success is False
        assert result.stage == "install", "build must not be attempted before a successful install"
        assert result.install is not None and result.install.ok is False
        assert result.install.errors
        assert result.package_manager in pm.allowed_commands()

    def test_install_timeout_is_reported(self, projects_dir):
        root = project_dir("timeout00001")
        root.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text("{}", encoding="utf-8")
        validator = BuildValidator(install_timeout=1, build_timeout=30)
        result = validator.install(root, "pnpm")
        assert result.ok is False
        assert result.errors

    def test_build_is_not_run_when_install_fails(self, projects_dir, monkeypatch):
        root = project_dir("buildguard01")
        root.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps({"scripts": {"build": "next build"}, "dependencies": {"nope-not-a-real-pkg-replui": "1.0.0"}}),
            encoding="utf-8",
        )
        validator = BuildValidator()
        calls: list[str] = []

        def _boom(*_args, **_kwargs):
            calls.append("build")
            raise AssertionError("build must not run after an install failure")

        monkeypatch.setattr(validator, "build", _boom)

        result = validator.validate("buildguard01")

        assert result.success is False
        assert result.stage == "install"
        assert calls == [], "build must not run after an install failure"

    def test_unknown_manager_is_rejected_not_executed(self, projects_dir):
        root = project_dir("badmgr0001")
        root.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text("{}", encoding="utf-8")
        install = BuildValidator().install(root, "bun")
        assert install.ok is False
        assert "allowlisted" in install.errors[0].message


@requires_pnpm
@pytest.mark.slow
class TestInstallAndBuild:
    def test_generated_project_installs_and_builds(self, projects_dir, spec):
        """The headline path: generated project -> install -> build."""
        root = ProjectGenerator().generate("e2e00000001", spec)
        assert not (root / "node_modules").exists(), "generator must not ship node_modules"

        result = BuildValidator(prefer="pnpm").validate("e2e00000001")

        assert result.install is not None, "install diagnostics must be recorded"
        assert result.install.package_manager == "pnpm"
        assert result.stage in {"install", "build"}
        assert result.success is True, f"build failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}\nerrors: {result.errors}"
        assert (root / "node_modules" / "next").is_dir(), "install must produce node_modules for the generated project"
        assert (root / ".next").is_dir(), "next build must emit .next"

    def test_second_validation_reuses_node_modules(self, projects_dir, spec):
        root = ProjectGenerator().generate("reuse00000001", spec)
        validator = BuildValidator(prefer="pnpm")
        first = validator.validate("reuse00000001")
        assert first.success is True, first.errors
        assert first.install is not None and first.install.skipped is False

        (root / "node_modules" / ".installed-marker").write_text("x")
        second = validator.validate("reuse00000001")

        assert second.success is True, second.errors
        assert second.install is not None
        assert second.install.skipped is True
        assert second.install.reused_node_modules is True
        assert second.install.duration_ms < first.install.duration_ms
        assert (root / "node_modules" / ".installed-marker").read_text() == "x", "reuse must not reinstall"

    def test_install_is_isolated_from_the_parent_workspace(self, projects_dir, spec):
        """Regression for the original failure.

        Generated projects sit inside the RepliUI pnpm workspace. A bare
        `pnpm install` there resolves the *root* workspace ("Scope: all 2
        workspace projects"), installs nothing for the project, and the
        subsequent build dies with "'next' is not recognized".
        """
        root = ProjectGenerator().generate("workspace001", spec)
        install = BuildValidator(prefer="pnpm").install(root, "pnpm")

        assert install.ok is True, f"{install.stdout}\n{install.stderr}\n{install.errors}"
        assert (root / "node_modules" / "next").is_dir(), "install must not be swallowed by the parent workspace"

    def test_changed_dependencies_force_a_reinstall(self, projects_dir):
        """A node_modules that predates the current package.json must not be reused."""
        root = project_dir("stalenm0001")
        root.mkdir(parents=True, exist_ok=True)
        (root / "node_modules").mkdir(exist_ok=True)
        (root / "node_modules" / "leftover").write_text("x", encoding="utf-8")
        (root / "package.json").write_text(
            json.dumps({"scripts": {"build": "next build"}, "dependencies": {"next": "14.2.5"}}),
            encoding="utf-8",
        )
        validator = BuildValidator(prefer="pnpm")
        first = validator.install(root, "pnpm")
        assert first.ok is True
        assert first.skipped is False
        assert first.reused_node_modules is False

        second = validator.install(root, "pnpm")
        assert second.ok is True
        assert second.skipped is True, "an unchanged manifest must reuse the install"

    def test_dependency_change_invalidates_the_reuse_cache(self, projects_dir, monkeypatch):
        root = project_dir("stalenm0002")
        root.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps({"scripts": {"build": "next build"}, "dependencies": {"next": "14.2.5"}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(pm, "run", lambda *_a, **_k: _Completed(0, "", ""))
        assert BuildValidator().install(root, "pnpm").skipped is False

        manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
        manifest["devDependencies"] = {"typescript": "^5"}
        (root / "package.json").write_text(json.dumps(manifest), encoding="utf-8")

        after = BuildValidator().install(root, "pnpm")
        assert after.skipped is False, "a changed dependency must trigger a reinstall"

    def test_install_failure_surfaces_manager_output(self, projects_dir):
        root = project_dir("outputcap01")
        root.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps({"scripts": {"build": "next build"}, "dependencies": {"nope-not-a-real-pkg-replui": "1.0.0"}}),
            encoding="utf-8",
        )
        install = BuildValidator().install(root, "pnpm")
        assert install.ok is False
        assert install.stdout or install.stderr, "install output must be captured"
        assert install.command == "pnpm install --ignore-workspace --no-frozen-lockfile"
