"""The repair loop: diagnose, patch, revalidate, bounded by a retry cap.

Runs inside the existing validation lifecycle. It never bypasses install or
build, never executes shell commands, and never writes outside the project
directory. After three failed attempts the project is marked FAILED.
"""

from __future__ import annotations

import logging
from typing import Callable

from ..models.schemas import (
    AgentState,
    ProjectManifest,
    WebsiteSpec,
)
from ..storage import load_manifest, save_manifest
from ..validators.build import BuildValidator
from .agent import RepairAgent, MAX_ATTEMPTS, MAX_REPAIR_CALLS
from .diagnostics import BuildDiagnostic, parse_diagnostics
from .patch import apply_patch

logger = logging.getLogger(__name__)


def _stage_command(validation) -> str:
    """Reconstruct the command that ran, for the diagnostic record.

    The allowlist is the only source of executable argv, so this is a human
    readable label for the diagnostic — it is never executed.
    """
    manager = validation.package_manager or "npm"
    return "npm install" if validation.stage == "install" else f"{manager} run build"


class RepairLoop:
    """Drives bounded self-repair for a single project."""

    def __init__(
        self,
        agent: RepairAgent | None = None,
        validator: BuildValidator | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        max_repair_calls: int = MAX_REPAIR_CALLS,
    ) -> None:
        self.agent = agent or RepairAgent()
        self.validator = validator or BuildValidator()
        self.max_attempts = max_attempts
        self.max_repair_calls = max_repair_calls

    def run(
        self,
        project_id: str,
        manifest: ProjectManifest,
        initial_validation,
        spec: WebsiteSpec | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> tuple[ProjectManifest, int, int]:
        """Run the repair loop.

        ``initial_validation`` is the failed validation that triggered repair.
        Returns ``(manifest, attempts, repair_calls)``.
        """
        def notify(message: str) -> None:
            if message not in manifest.progress:
                manifest.progress.append(message)
            if on_progress:
                on_progress(message)

        attempts = 0
        repair_calls = 0
        validation = initial_validation

        while attempts < self.max_attempts:
            if validation.success:
                manifest.state = AgentState.READY
                manifest.validation = validation
                notify(f"✓ Build passed after {attempts} repair attempt(s)")
                save_manifest(manifest)
                return manifest, attempts, repair_calls

            attempts += 1
            manifest.state = AgentState.REPAIRING
            notify(f"↻ Repair attempt {attempts}/{self.max_attempts}")

            diagnostics = self._diagnostics(validation, attempts)
            notify(f"  ⚠ {len(diagnostics)} diagnostic(s); asking repair agent")

            if repair_calls >= self.max_repair_calls:
                notify("  ✗ Repair call budget exhausted")
                break

            repair_calls += 1
            plan = self.agent.build_plan(
                project_id, diagnostics, spec=spec, attempt=attempts
            )
            if plan.summary:
                notify(f"  · {plan.summary}")

            if not plan.changes:
                notify("  ✗ Repair agent returned no changes")
                break

            result = apply_patch(project_id, plan.changes)
            if not result.ok:
                for err in result.errors:
                    notify(f"  ✗ {err}")
                break

            notify(f"  ✓ Applied {len(result.applied)} change(s): {', '.join(result.applied)}")
            notify("  ↻ Rebuilding…")
            validation = self.validator.validate(project_id)
            manifest.validation = validation

        if validation.success:
            manifest.state = AgentState.READY
            notify("✓ Build passed on final validation")
        else:
            manifest.state = AgentState.FAILED
            notify(f"✗ Validation failed after {attempts} repair attempt(s)")

        save_manifest(manifest)
        return manifest, attempts, repair_calls

    def _diagnostics(self, validation, attempt: int) -> list[BuildDiagnostic]:
        """Extract structured diagnostics from a validation result.

        ``ValidationResult`` carries a single ``stdout``/``stderr`` pair for
        whichever stage actually failed, so the real stage is passed through
        instead of a hardcoded ``build`` — an install failure must not be
        reported as a build failure.
        """
        return parse_diagnostics(
            stage=validation.stage,
            command=_stage_command(validation),
            stdout=validation.stdout,
            stderr=validation.stderr,
            exit_code=None,
        )