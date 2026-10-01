"""Self-repair for generated projects.

After a build failure the repair loop diagnoses the failure, asks the AI
gateway for a targeted patch, applies only safe changes inside the generated
project, and re-validates. At most three attempts are made; persistent
failure is reported as ``FAILED``. The repair agent never executes shell
commands and never writes outside ``generated/projects/{project_id}``.
"""

from .diagnostics import BuildDiagnostic, categorize, parse_diagnostics
from .patch import apply_patch, validate_patch
from .agent import RepairAgent, RepairPlan, RepairChange

__all__ = [
    "BuildDiagnostic",
    "categorize",
    "parse_diagnostics",
    "apply_patch",
    "validate_patch",
    "RepairAgent",
    "RepairPlan",
    "RepairChange",
]