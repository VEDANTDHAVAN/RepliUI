"""Parse build output into structured diagnostics."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


class BuildDiagnostic(BaseModel):
    """A normalized build failure."""

    stage: str
    command: str = ""
    exit_code: int | None = None
    message: str = ""
    file: str | None = None
    line: int | None = None
    column: int | None = None
    category: str = "UNKNOWN_BUILD_ERROR"
    raw_output: str = ""

    model_config = {"extra": "ignore"}


TYPESCRIPT_ERROR = "TYPESCRIPT_ERROR"
MODULE_NOT_FOUND = "MODULE_NOT_FOUND"
IMPORT_ERROR = "IMPORT_ERROR"
JSX_ERROR = "JSX_ERROR"
CONFIG_ERROR = "CONFIG_ERROR"
DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
UNKNOWN_BUILD_ERROR = "UNKNOWN_BUILD_ERROR"

_FILE_PATTERNS = [
    # "(components/Hero.tsx:12:5)" and "(12:5)"
    re.compile(r"\(([^():]+?):(\d+):(\d+)\)"),
    re.compile(r"\(([^():]+?):(\d+)\)"),
    # bare "components/Hero.tsx:12:5" at start of line, or "./app/page.tsx:12:5"
    re.compile(r"^\s*(\.{0,2}[\w./\\-]+\.tsx?):(\d+)(?::(\d+))?"),
    # "'@/components/Missing'" and '"./nope"' — module specifiers only.
    # Restricted to path-like text so `Type error: Property 'foo' does not
    # exist` is not mistaken for a file named `foo`.
    re.compile(r"['\"]([@.][\w./@-]*[/\\][\w./@-]+)['\"]"),
]

# A line that is *only* a location, e.g. "./app/page.tsx:12:5". Next.js prints
# the location on one line and the message on the next.
_LOCATION_ONLY = re.compile(r"^(\.{0,2}[\w./\\-]+):(\d+)(?::(\d+))?$")

# Progress banners and separators are not errors. They are skipped so the
# repair agent is not handed "> next build" as a failure to fix. If every line
# is noise, the fallback diagnostic is emitted instead, so a real failure is
# never dropped.
_NOISE = (
    re.compile(r"^\s*>"),
    re.compile(r"^\s*\$"),
    re.compile(r"^\s*[─━═-]{3,}\s*$"),
    # Next.js decorates progress with "   - " / " ✓ " / " ⚠ " prefixes.
    re.compile(r"^\s*[-–]\s+Creating an optimized production build"),
    re.compile(r"^\s*[-–]\s+Linting"),
    re.compile(r"^\s*npm (warn|notice|ERR!)\s*$", re.IGNORECASE),
    re.compile(r"^\s*✓\s*Compiled successfully", re.IGNORECASE),
    # Next.js progress output — status, not failure.
    re.compile(r"^\s*⚠\s"),
    re.compile(r"^\s*▲\s"),
    re.compile(r"^\s*(Attention|Info|Note|Warning):\s", re.IGNORECASE),
    re.compile(r"^\s*Creating an optimized production build"),
    re.compile(r"^\s*Linting and checking", re.IGNORECASE),
    re.compile(r"^\s*Collecting build traces", re.IGNORECASE),
    re.compile(r"^\s*Collecting page data", re.IGNORECASE),
    re.compile(r"^\s*Generating static pages", re.IGNORECASE),
    re.compile(r"^\s*Compiled successfully", re.IGNORECASE),
    re.compile(r"^\s*ELIFECYCLE\b"),
    re.compile(r"^\s*Failed to compile\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*You can learn more", re.IGNORECASE),
    re.compile(r"^\s*This information is used", re.IGNORECASE),
    re.compile(r"^\s*https?://\S+$"),
)

# tsc prints an ANSI-coloured code frame under the message. The location line
# above already carries the file and line, and the frame is mostly escape
# codes, so it is dropped instead of being sent on as a separate failure.
# Both the source line (" 1 | export function") and the blank continuation
# line (" 2 |") must match, hence the optional trailing content.
_CODE_FRAME = re.compile(r"^\s*\d*\s*\|")

# ESC[...m — the colour codes tsc wraps code frames in.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _is_location_only(line: str) -> bool:
    return bool(_LOCATION_ONLY.match(line.strip()))


def _is_noise(line: str) -> bool:
    return any(pattern.match(line) for pattern in _NOISE)


def _extract_file(message: str) -> tuple[str | None, int | None, int | None]:
    """Pull a file path and optional line/column out of a message.

    Returns ``(None, None, None)`` rather than a guess: a wrong file name is
    worse than no file, because it steers the agent at the wrong source.
    """
    for pat in _FILE_PATTERNS:
        m = pat.search(message)
        if m:
            groups = m.groups()
            if len(groups) == 3:
                return (
                    groups[0],
                    int(groups[1]) if groups[1] else None,
                    int(groups[2]) if groups[2] else None,
                )
            if len(groups) == 2:
                return groups[0], int(groups[1]) if groups[1] else None, None
            return groups[0], None, None
    return None, None, None


def categorize(message: str) -> str:
    """Classify a build error message into a repair category."""
    m = message.lower()
    if "cannot find module" in m or "module not found" in m or "failed to resolve" in m:
        return MODULE_NOT_FOUND
    # `Type error:` is the tsc banner Next.js prefixes to type failures.
    if (
        "type error" in m
        or "cannot find name" in m
        or "is not assignable" in m
        or "is not a function" in m
        or "does not exist on type" in m
        or "implicitly has an 'any' type" in m
        or "expected type" in m
    ):
        return TYPESCRIPT_ERROR
    if "expected" in m and ("tsx" in m or "jsx" in m):
        return JSX_ERROR
    if "jsx" in m and ("element" in m or "expression" in m or "tag" in m or "closing" in m):
        return JSX_ERROR
    # tsc phrases these as "No default export is a member of module" and
    # "Module ... has no default export" — neither contains the word "import".
    if "no default export" in m or "has no default" in m or "only default" in m:
        return IMPORT_ERROR
    if "import" in m and ("not found" in m or "cannot be named" in m or "no default" in m):
        return IMPORT_ERROR
    if "next.config" in m or "tsconfig" in m:
        return CONFIG_ERROR
    if "peer dep" in m or "unmet" in m or "dependency" in m or "npm" in m or "pnpm" in m:
        return DEPENDENCY_ERROR
    if "syntaxerror" in m or "unexpected token" in m:
        return TYPESCRIPT_ERROR
    return UNKNOWN_BUILD_ERROR


def parse_diagnostics(
    stage: str,
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int | None = None,
) -> list[BuildDiagnostic]:
    """Parse raw build output into a list of structured diagnostics."""
    # Strip colour first: without it a code frame is a wall of escape codes
    # the model cannot read and the file patterns cannot match.
    combined = _ANSI.sub("", (stdout or "") + "\n" + (stderr or "")).strip()
    diagnostics: list[BuildDiagnostic] = []
    # Keyed on the message, not the category: two errors in one file at
    # different lines are distinct diagnostics.
    seen: set[tuple[str, int | None, int | None, str]] = set()

    lines = combined.splitlines()
    skip_next = False
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        if _is_noise(line) or _CODE_FRAME.match(line):
            continue

        # Next.js prints the location on its own line and the message on the
        # next. Folding them yields one attributed diagnostic per error
        # instead of a location-only record plus an unattributed message; the
        # message line is then consumed so it is not emitted a second time.
        if _is_location_only(line):
            file, ln, col = _extract_file(line)
            nxt = lines[index + 1].strip() if index + 1 < len(lines) else ""
            if nxt and not _is_location_only(nxt):
                message, raw_output = nxt, line + "\n" + nxt
                skip_next = True
            else:
                message, raw_output = line, raw_line
        else:
            if skip_next:
                skip_next = False
                continue
            file, ln, col = _extract_file(line)
            message, raw_output = line, raw_line
        category = categorize(message)

        key = (file or "", ln, col, message)
        if key in seen:
            continue
        seen.add(key)
        diagnostics.append(
            BuildDiagnostic(
                stage=stage,
                command=command,
                exit_code=exit_code,
                message=message,
                file=file,
                line=ln,
                column=col,
                category=category,
                raw_output=raw_output,
            )
        )

    if not diagnostics:
        diagnostics.append(
            BuildDiagnostic(
                stage=stage,
                command=command,
                exit_code=exit_code,
                message=(combined or "Build failed")[:500],
                category=categorize(combined),
                raw_output=combined[:2000],
            )
        )
    return diagnostics



