from __future__ import annotations

import subprocess
import time

from ..models.schemas import ValidationError, ValidationResult
from ..storage import project_dir


class BuildValidator:
    def validate(self, project_id: str) -> ValidationResult:
        root = project_dir(project_id)
        started = time.perf_counter()
        if not (root / "package.json").exists():
            return ValidationResult(success=False, stage="inspect", errors=[ValidationError(message="Generated package.json is missing")])
        try:
            result = subprocess.run(["npm", "run", "build"], cwd=root, capture_output=True, text=True, timeout=120, shell=True)
            output = (result.stdout + "\n" + result.stderr).strip()
            errors = [] if result.returncode == 0 else [ValidationError(message=line.strip()) for line in output.splitlines() if "error" in line.lower()][-10:]
            return ValidationResult(success=result.returncode == 0, stage="build", errors=errors or ([ValidationError(message="Build command failed")] if result.returncode else []), stdout=result.stdout[-5000:], stderr=result.stderr[-5000:], duration_ms=int((time.perf_counter()-started)*1000))
        except subprocess.TimeoutExpired:
            return ValidationResult(success=False, stage="build", errors=[ValidationError(message="Build timed out after 120 seconds")], duration_ms=120000)
        except OSError as exc:
            return ValidationResult(success=False, stage="build", errors=[ValidationError(message=f"Unable to run npm: {exc}")])
