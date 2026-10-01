"""Safe, targeted patching of generated project files.

A repair patch is a structured edit: an exact file path, the original content
the change is meant to replace, and the replacement content. Patches are
validated against the project's directory before anything is written, and a
patch that cannot be located or that would escape the project is rejected.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from ..storage import project_dir

MAX_PATCH_SIZE = 64 * 1024  # 64 KiB per patch
MAX_FILE_SIZE = 256 * 1024  # 256 KiB per source file

# The repair agent may change generated source so a build can succeed. These
# are the files that would instead let it reach outside the sandbox, so they
# are refused outright rather than merely discouraged in the prompt.
# ``package.json`` is allowed but only as a whole-file replace that the
# validator re-checks; scripts are never executed on the repair path.
FORBIDDEN_FILES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        ".env.test",
    }
)
FORBIDDEN_SUFFIXES = (".env",)

# Config files are legitimate repair targets (a bad ``next.config`` is a real
# build failure), so they are allowed — but a repair that tries to smuggle a
# shell command or a widened script into one is rejected.
_COMMAND_MARKERS = re.compile(
    r"(\brm\s+-rf\b|\bcurl\b|\bwget\b|\|\s*(ba)?sh\b|;\s*(rm|curl|wget)\b"
    r"|\bchild_process\b|\bexecSync\b|\bspawnSync\b|\beval\s*\(|`[^`]*\$\()",
    re.IGNORECASE,
)


def _is_forbidden(relpath: str) -> bool:
    """True if the path is a secret file the repair agent may never touch."""
    name = relpath.replace("\\", "/").rsplit("/", 1)[-1]
    if name in FORBIDDEN_FILES:
        return True
    return any(name.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES)


class RepairChange(BaseModel):
    """A single targeted edit proposed by the repair agent."""

    file: str
    action: str = "replace"
    original: str = ""
    replacement: str = ""
    reason: str = ""

    model_config = {"extra": "ignore"}


class PatchResult(BaseModel):
    """Outcome of applying one or more changes."""

    ok: bool
    applied: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _resolve(project_id: str, relpath: str) -> Path:
    """Resolve a patch target inside the project directory.

    Raises ``ValueError`` if the path escapes the project or is absolute.
    """
    if not relpath or relpath.startswith(("/", "\\")):
        raise ValueError(f"absolute path not allowed: {relpath!r}")
    base = project_dir(project_id).resolve()
    candidate = (base / relpath).resolve()
    if base not in candidate.parents and candidate != base:
        raise ValueError(f"path escapes project directory: {relpath!r}")
    return candidate


def validate_patch(project_id: str, change: RepairChange) -> str | None:
    """Return an error message if the change cannot be safely applied."""
    if not change.file:
        return "patch is missing a file path"
    if _is_forbidden(change.file):
        return f"refusing to modify environment/secrets file: {change.file}"
    if change.action not in ("replace", "append", "delete"):
        return f"unsupported patch action: {change.action!r}"
    if len(change.original) > MAX_PATCH_SIZE or len(change.replacement) > MAX_PATCH_SIZE:
        return "patch content exceeds the size limit"
    # A repair is a source edit. Command-shaped content means the model is
    # trying to use the patch channel as an execution channel.
    if _COMMAND_MARKERS.search(change.replacement or ""):
        return f"refusing command-shaped patch content for {change.file}"
    try:
        target = _resolve(project_id, change.file)
    except ValueError as exc:
        return str(exc)
    if not target.is_file():
        return f"file does not exist: {change.file}"
    if target.stat().st_size > MAX_FILE_SIZE:
        return f"file too large: {change.file}"
    if change.original and change.original not in target.read_text(encoding="utf-8", errors="replace"):
        return f"original content not found in {change.file}"
    return None


def apply_patch(project_id: str, changes: list[RepairChange]) -> PatchResult:
    """Apply a list of validated changes. Returns a structured result."""
    result = PatchResult(ok=True)
    for change in changes:
        error = validate_patch(project_id, change)
        if error:
            result.rejected.append(change.file)
            result.errors.append(f"{change.file}: {error}")
            result.ok = False
            continue
        target = _resolve(project_id, change.file)
        original_text = target.read_text(encoding="utf-8", errors="replace")

        if change.action == "append":
            new_text = original_text + change.replacement
        else:
            occurrences = original_text.count(change.original) if change.original else 0
            if occurrences == 0:
                result.rejected.append(change.file)
                result.errors.append(
                    f"{change.file}: original text was not found; patch not applied"
                )
                result.ok = False
                continue
            if occurrences > 1:
                # An ambiguous anchor would let the model rewrite the wrong
                # occurrence. Refuse rather than guess.
                result.rejected.append(change.file)
                result.errors.append(
                    f"{change.file}: original text matches {occurrences} locations; "
                    "repair patch must be unique"
                )
                result.ok = False
                continue
            if change.action == "delete":
                new_text = original_text.replace(change.original, "")
            else:
                new_text = original_text.replace(change.original, change.replacement, 1)

        target.write_text(new_text, encoding="utf-8")
        result.applied.append(change.file)
    return result


def select_relevant_files(
    diagnostics: list,
    project_root: Path,
    max_files: int = 8,
) -> list[str]:
    """Pick the files most likely to need repair.

    Ordered by how strongly the evidence implicates each file:

    1. the file named in the diagnostic
    2. the config file a category implicates (``package.json`` for
       dependency errors, ``next.config.*``/``tsconfig.json`` for config)
    3. files that import the diagnosed file, since a changed export breaks
       its callers just as often as the file itself
    4. remaining sources, only if nothing better was found

    The result is capped at ``max_files`` so the model never receives the
    whole project.
    """
    from .diagnostics import BuildDiagnostic, CONFIG_ERROR, DEPENDENCY_ERROR

    root = project_root.resolve()
    candidates: list[str] = []
    seen: set[str] = set()
    categories: set[str] = set()

    def add(rel: str) -> bool:
        """Add a project-relative path if it is a real file inside the root."""
        if rel in seen or len(candidates) >= max_files:
            return False
        # Secrets must never reach the model, not even as read-only context.
        if _is_forbidden(rel):
            return False
        target = (root / rel).resolve()
        if target != root and root not in target.parents:
            return False
        if not target.is_file():
            return False
        seen.add(rel)
        candidates.append(rel)
        return True

    for diag in diagnostics:
        if not isinstance(diag, BuildDiagnostic):
            continue
        categories.add(diag.category)
        if diag.file:
            add(diag.file.replace("\\", "/").lstrip("/"))

    # Category-implicated config: a missing dependency cannot be fixed in a
    # component, and a config error cannot be fixed in a stylesheet.
    if DEPENDENCY_ERROR in categories:
        add("package.json")
    if CONFIG_ERROR in categories:
        for name in ("next.config.js", "next.config.mjs", "next.config.ts", "tsconfig.json"):
            add(name)

    # Callers of a diagnosed file. A renamed or removed export breaks the
    # importer, and the diagnostic points at the callee.
    for rel in list(candidates):
        if len(candidates) >= max_files:
            break
        for path in _source_files(root):
            other = path.relative_to(root).as_posix()
            if other in seen:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _imports(text, rel):
                add(other)
                break

    # Nothing was implicated. The spec calls for a small file *tree* plus the
    # build output, not a dump of every source file: reading unrelated files
    # both wastes tokens and hands the model code it has no reason to see.
    # Only entry points are added, so a fix that touches an unrelated
    # component is not encouraged.
    if not candidates:
        for name in ("app/page.tsx", "app/layout.tsx"):
            add(name)

    return candidates[:max_files]


def project_file_tree(project_root: Path, max_entries: int = 40) -> str:
    """A small listing of the project, for when no file was identified."""
    skip = {"node_modules", ".next", ".git", "out"}
    entries: list[str] = []
    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(project_root)
        if any(part in skip for part in rel.parts):
            continue
        if _is_forbidden(rel.as_posix()):
            continue
        entries.append(rel.as_posix())
        if len(entries) >= max_entries:
            break
    return "\n".join(entries) if entries else "(empty project)"


def _imports(text: str, relpath: str) -> bool:
    """True if ``text`` imports the module at ``relpath``.

    Matches the form written in the file as well as the ``@/`` alias the
    generated projects use for the project root, so a caller is found whether
    it writes ``"./components/Hero"`` or ``"@/components/Hero"``.
    """
    # `relpath` is already project-relative, e.g. "components/Hero.tsx". The
    # generated projects import via the "@/" root alias and omit the
    # extension, so "components/Hero" is the form that actually appears.
    without_ext = relpath.rsplit(".", 1)[0] if "." in relpath.rsplit("/", 1)[-1] else relpath
    stem = relpath.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    specs = {relpath, without_ext, stem}
    for spec in specs:
        for quote in ('"', "'"):
            for literal in _spec_forms(spec):
                if f"from {quote}{literal}{quote}" in text:
                    return True
                if f"import({quote}{literal}{quote})" in text:
                    return True
                if f"require({quote}{literal}{quote})" in text:
                    return True
    return False


def _spec_forms(spec: str) -> set[str]:
    """The ways a module specifier for ``spec`` can appear in an import."""
    forms = {spec, f"@/{spec}", f"./{spec}"}
    if spec.startswith("./"):
        # "@/./components/Hero" is not a thing; drop the "./" before aliasing.
        forms.add("@/" + spec[2:])
    return forms


def _source_files(root: Path) -> list[Path]:
    """Generated source files, skipping dependency and build directories."""
    skip = {"node_modules", ".next", ".git", "out"}
    found = [
        path
        for path in root.rglob("*.tsx")
        if not any(part in skip for part in path.relative_to(root).parts)
    ]
    return sorted(found)


def read_context(project_id: str, relpaths: list[str]) -> dict[str, str]:
    """Read the current text of each relevant file for the repair prompt."""
    base = project_dir(project_id)
    context: dict[str, str] = {}
    for rel in relpaths:
        try:
            target = _resolve(project_id, rel)
        except ValueError:
            continue
        if target.is_file() and target.stat().st_size <= MAX_FILE_SIZE:
            context[rel] = target.read_text(encoding="utf-8", errors="replace")
    return context