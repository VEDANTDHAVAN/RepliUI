from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from subprocess import SubprocessError, TimeoutExpired

from ..models.schemas import InstallResult, ValidationError, ValidationResult
from ..storage import project_dir
from . import package_manager as pm

INSTALL_TIMEOUT = int(os.getenv("VALIDATION_INSTALL_TIMEOUT", "600"))
BUILD_TIMEOUT = int(os.getenv("VALIDATION_BUILD_TIMEOUT", "300"))
STAGE_INSPECT = "inspect"
STAGE_INSTALL = "install"
STAGE_BUILD = "build"

_MAX_CAPTURE = 20000
_ERROR_TAIL = 10


class BuildValidator:
    """Validates a generated project as install -> build.

    ``node_modules`` is produced by the install stage, never expected to be part of
    the generated output. An existing, complete ``node_modules`` is reused so
    rebuilding the same project stays fast.
    """

    def __init__(self, prefer: str | None = None, install_timeout: int | None = None, build_timeout: int | None = None) -> None:
        self.prefer = prefer or os.getenv("PACKAGE_MANAGER") or None
        self.install_timeout = install_timeout or INSTALL_TIMEOUT
        self.build_timeout = build_timeout or BUILD_TIMEOUT

    # -- stages ---------------------------------------------------------

    def inspect(self, project_id: str) -> tuple[Path | None, ValidationResult | None]:
        root = project_dir(project_id)
        if not (root / "package.json").exists():
            return None, ValidationResult(
                success=False,
                stage=STAGE_INSPECT,
                errors=[ValidationError(message="Generated package.json is missing")],
            )
        return root, None

    def install(self, root: Path, manager: str | None = None) -> InstallResult:
        """Install dependencies, reusing an existing node_modules when usable."""
        started = time.perf_counter()
        manager = manager or pm.detect(root, self.prefer)
        try:
            pm.select(manager)
        except pm.CommandNotAllowed as exc:
            return InstallResult(
                ok=False,
                package_manager=manager,
                errors=[ValidationError(message=str(exc))],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        if _is_install_current(root):
            return InstallResult(
                ok=True,
                package_manager=manager,
                skipped=True,
                reused_node_modules=True,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        try:
            command = pm.install_command(manager)
        except pm.CommandNotAllowed as exc:
            return InstallResult(
                ok=False,
                package_manager=manager,
                errors=[ValidationError(message=str(exc))],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        try:
            completed = pm.run(command, root, self.install_timeout)
        except TimeoutExpired:
            return InstallResult(
                ok=False,
                command=command.display(),
                package_manager=manager,
                stderr=f"Dependency installation timed out after {self.install_timeout} seconds",
                errors=[ValidationError(message=f"Dependency installation timed out after {self.install_timeout} seconds")],
                duration_ms=self.install_timeout * 1000,
            )
        except (OSError, SubprocessError) as exc:
            return InstallResult(
                ok=False,
                command=command.display(),
                package_manager=manager,
                errors=[ValidationError(message=f"Unable to run {command.display()}: {exc}")],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        ok = completed.returncode == 0 and _has_usable_node_modules(root)
        if ok:
            _write_fingerprint(root)
        errors: list[ValidationError] = []
        if not ok:
            errors = _extract_errors(completed, f"{command.display()} failed with exit code {completed.returncode}")
            if completed.returncode == 0 and not errors:
                errors = [ValidationError(message="Dependency installation reported success but produced no node_modules directory")]
        return InstallResult(
            ok=ok,
            command=command.display(),
            package_manager=manager,
            stdout=completed.stdout[-_MAX_CAPTURE:],
            stderr=completed.stderr[-_MAX_CAPTURE:],
            errors=errors,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    def build(self, root: Path, manager: str) -> ValidationResult:
        started = time.perf_counter()
        try:
            command = pm.build_command(manager)
        except pm.CommandNotAllowed as exc:
            return ValidationResult(
                success=False,
                stage=STAGE_BUILD,
                package_manager=manager,
                errors=[ValidationError(message=str(exc))],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        try:
            completed = pm.run(command, root, self.build_timeout)
        except TimeoutExpired:
            return ValidationResult(
                success=False,
                stage=STAGE_BUILD,
                package_manager=manager,
                errors=[ValidationError(message=f"Build timed out after {self.build_timeout} seconds")],
                duration_ms=self.build_timeout * 1000,
            )
        except (OSError, SubprocessError) as exc:
            return ValidationResult(
                success=False,
                stage=STAGE_BUILD,
                package_manager=manager,
                errors=[ValidationError(message=f"Unable to run {command.display()}: {exc}")],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        errors = [] if completed.returncode == 0 else _extract_errors(completed, "Build command failed")
        return ValidationResult(
            success=completed.returncode == 0,
            stage=STAGE_BUILD,
            package_manager=manager,
            errors=errors,
            stdout=completed.stdout[-_MAX_CAPTURE:],
            stderr=completed.stderr[-_MAX_CAPTURE:],
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    # -- orchestration --------------------------------------------------

    def validate(self, project_id: str) -> ValidationResult:
        started = time.perf_counter()
        root, failure = self.inspect(project_id)
        if failure is not None:
            return failure

        assert root is not None
        manager = pm.detect(root, self.prefer)
        install = self.install(root, manager)
        if not install.ok:
            # The build is only meaningful once dependencies are actually present.
            return ValidationResult(
                success=False,
                stage=STAGE_INSTALL,
                package_manager=manager,
                install=install,
                errors=install.errors
                or [ValidationError(message="Dependency installation failed")],
                stdout=install.stdout,
                stderr=install.stderr,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        result = self.build(root, manager)
        result.install = install
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result


def _has_usable_node_modules(root: Path) -> bool:
    """A node_modules directory alone is not proof of a complete install."""
    modules = root / "node_modules"
    if not modules.is_dir():
        return False
    return any(modules.iterdir())


def _fingerprint(root: Path) -> str:
    """Hash of the dependency-declaring fields of package.json.

    Reuse is keyed to this rather than to node_modules merely existing, so a
    regenerated project that adds or changes a dependency reinstalls instead of
    silently building against stale modules.
    """
    try:
        data = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    relevant = {
        "dependencies": data.get("dependencies", {}),
        "devDependencies": data.get("devDependencies", {}),
        "packageManager": data.get("packageManager"),
    }
    return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode("utf-8")).hexdigest()


def _fingerprint_path(root: Path) -> Path:
    return root / "node_modules" / ".repliui-install.json"


def _write_fingerprint(root: Path) -> None:
    try:
        _fingerprint_path(root).write_text(
            json.dumps({"fingerprint": _fingerprint(root), "package_manager": pm.selected()}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _is_install_current(root: Path) -> bool:
    """True when node_modules exists and matches the current package.json."""
    if not _has_usable_node_modules(root):
        return False
    try:
        recorded = json.loads(_fingerprint_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return recorded.get("fingerprint") == _fingerprint(root)


def _extract_errors(completed, fallback: str) -> list[ValidationError]:
    output = f"{completed.stdout}\n{completed.stderr}"
    matches = [line.strip() for line in output.splitlines() if "error" in line.lower()]
    tail = matches[-_ERROR_TAIL:] or [
        line.strip() for line in output.splitlines() if line.strip()
    ][-_ERROR_TAIL:]
    return [ValidationError(message=line) for line in tail] or [ValidationError(message=fallback)]
