"""Package manager detection and the allowlist of commands the validator may run.

Two invariants are enforced here:

1. Only the commands in ``ALLOWED_COMMANDS`` can ever reach ``subprocess``. Callers
   receive a pre-built argv list, and the argv is re-validated against the
   allowlist immediately before execution, so a mutated or future
   caller-supplied value still cannot widen the surface.
2. ``pnpm install`` runs with ``--ignore-workspace``. Generated projects live under
   ``generated/projects/{id}``, which sits *inside* the RepliUI pnpm workspace.
   Without the flag, pnpm walks up, finds the repository ``pnpm-workspace.yaml``,
   reports "Scope: all 2 workspace projects", and installs nothing for the
   generated project -- so no ``node_modules`` appears and the build then fails
   with ``'next' is not recognized``.
3. ``pnpm install`` also runs with ``--no-frozen-lockfile``. Validation sets ``CI``
   to keep the manager non-interactive, which makes pnpm default to
   ``--frozen-lockfile``; a regenerated project's lockfile is legitimately stale
   relative to the freshly written ``package.json``, so the default would fail the
   install with ``ERR_PNPM_OUTDATED_LOCKFILE``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# name -> (install argv suffix, build argv)
_ALLOWED_COMMANDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "pnpm": (("install", "--ignore-workspace", "--no-frozen-lockfile"), ("build",)),
    "npm": (("install",), ("run", "build")),
    "yarn": (("install",), ("build",)),
}

# Lockfiles, most specific first. A lockfile is a stronger signal than a
# globally installed binary.
_LOCKFILES: tuple[tuple[str, str], ...] = (
    ("pnpm-lock.yaml", "pnpm"),
    ("pnpm-workspace.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("package-lock.json", "npm"),
)

PREFERRED_PACKAGE_MANAGER = "pnpm"

# Set by the validator and read back by the caller so progress and diagnostics
# can name the manager that actually ran.
_SELECTED: str | None = None


class CommandNotAllowed(ValueError):
    """Raised when a command is not present in the allowlist."""


def allowed_commands() -> tuple[str, ...]:
    return tuple(_ALLOWED_COMMANDS)


def _resolve_executable(name: str) -> str | None:
    """Absolute path to the manager binary, or None when it is not installed.

    An absolute path is required: ``pnpm`` on Windows is frequently a ``.CMD``
    shim, and a bare name launched without a shell cannot be found.
    """
    return shutil.which(name)


def detect(project_root: Path, prefer: str | None = None) -> str:
    """Pick the package manager for a generated project.

    Precedence: explicit ``prefer`` > lockfile in the project > ``packageManager``
    field in package.json > a globally available manager > ``PREFERRED_PACKAGE_MANAGER``.
    """
    candidates: list[str] = []
    if prefer:
        candidates.append(prefer)
    for filename, manager in _LOCKFILES:
        if (project_root / filename).exists():
            candidates.append(manager)
    declared = _declared_manager(project_root)
    if declared:
        candidates.append(declared)
    for manager in _ALLOWED_COMMANDS:
        if _resolve_executable(manager):
            candidates.append(manager)
    candidates.append(PREFERRED_PACKAGE_MANAGER)

    for manager in candidates:
        if manager in _ALLOWED_COMMANDS and _resolve_executable(manager):
            return manager
    return PREFERRED_PACKAGE_MANAGER


def _declared_manager(project_root: Path) -> str | None:
    import json

    package_json = project_root / "package.json"
    if not package_json.exists():
        return None
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    declared = data.get("packageManager") if isinstance(data, dict) else None
    if not isinstance(declared, str):
        return None
    name = declared.split("@", 1)[0].strip().lower()
    return name if name in _ALLOWED_COMMANDS else None


def select(manager: str) -> str:
    """Validate ``manager`` against the allowlist and remember it."""
    global _SELECTED
    if manager not in _ALLOWED_COMMANDS:
        raise CommandNotAllowed(
            f"Package manager {manager!r} is not allowlisted; allowed: {', '.join(allowed_commands())}"
        )
    _SELECTED = manager
    return manager


def selected() -> str | None:
    return _SELECTED


@dataclass(frozen=True)
class Command:
    manager: str
    argv: tuple[str, ...]
    executable: str

    def display(self) -> str:
        return " ".join(self.argv)


def install_command(manager: str) -> Command:
    return _build_command(manager, index=0)


def build_command(manager: str) -> Command:
    return _build_command(manager, index=1)


def _build_command(manager: str, index: int) -> Command:
    if manager not in _ALLOWED_COMMANDS:
        raise CommandNotAllowed(
            f"Package manager {manager!r} is not allowlisted; allowed: {', '.join(allowed_commands())}"
        )
    suffix = _ALLOWED_COMMANDS[manager][index]
    argv = (manager, *suffix)
    assert_allowed(manager, argv)
    executable = _resolve_executable(manager)
    if executable is None:
        raise CommandNotAllowed(
            f"Package manager {manager!r} is not installed or not on PATH; install it or set PACKAGE_MANAGER"
        )
    return Command(manager=manager, argv=argv, executable=executable)


def assert_allowed(manager: str, argv: tuple[str, ...] | list[str]) -> None:
    """Raise unless ``argv`` is exactly one of the allowlisted commands."""
    argv = tuple(argv)
    for allowed_manager, commands in _ALLOWED_COMMANDS.items():
        if manager == allowed_manager and argv in {(allowed_manager, *cmd) for cmd in commands}:
            return
    raise CommandNotAllowed(f"Command {' '.join(argv)!r} is not allowlisted")


def run(command: Command, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    """Execute an allowlisted command, re-checking the allowlist at the last moment."""
    assert_allowed(command.manager, command.argv)
    env = dict(os.environ)
    # Non-interactive so a manager never blocks waiting on a prompt.
    env.setdefault("CI", "1")
    return subprocess.run(
        [command.executable, *command.argv[1:]],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
        env=env,
    )
