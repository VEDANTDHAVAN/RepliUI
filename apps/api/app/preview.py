"""Serve a generated project's static build output as a sandboxed preview.

The generator emits a Next.js app. ``next build`` with ``output: 'export'``
writes a fully static bundle under ``out/``: an ``index.html`` and every asset
under ``_next/static/``. The HTML references those assets as root-absolute
paths (``/_next/static/...``), so they are rewritten at serve time to the
preview prefix. Serving is read-only, scoped to one project, and never touches
the filesystem outside that project's export directory.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from .storage import export_dir, resolve_preview_file

__all__ = [
    "preview_url",
    "preview_available",
    "serve_preview",
    "PreviewError",
]

# The prefix the frontend embeds in its sandboxed iframe. Asset paths inside
# the prerendered HTML are rewritten from ``/_next/`` to this prefix.
PREVIEW_PREFIX = "/api/projects"


class PreviewError(Exception):
    """Raised when a project cannot be served as a static preview."""


def preview_url(project_id: str) -> str:
    """The URL the dashboard embeds in its sandboxed iframe."""
    return f"{PREVIEW_PREFIX}/{project_id}/preview/"


def preview_available(project_id: str) -> bool:
    """True when the project's static export is present and complete."""
    return (export_dir(project_id) / "index.html").is_file()


def _content_type(relpath: str) -> str:
    name = relpath or "index.html"
    ctype, _ = mimetypes.guess_type(name)
    if ctype:
        return ctype
    if name.endswith(".js"):
        return "application/javascript"
    if name.endswith(".css"):
        return "text/css"
    if name.endswith(".html"):
        return "text/html"
    return "application/octet-stream"


def serve_preview(project_id: str, relpath: str) -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for a preview asset.

    ``relpath`` is the part of the URL after ``/preview/``. ``index.html`` is
    served when the path is empty, and every ``/_next/`` reference inside it is
    rewritten to the preview prefix so the browser can resolve assets.
    """
    path = resolve_preview_file(project_id, relpath)
    if path.suffix == ".html":
        body = _rewrite_html(project_id, path)
    else:
        body = path.read_bytes()
    return body, _content_type(relpath)


def _rewrite_html(project_id: str, path: Path) -> bytes:
    """Rewrite root-absolute ``/_next/`` references to the preview prefix."""
    prefix = f"{PREVIEW_PREFIX}/{project_id}/preview/_next/".encode("ascii")
    return path.read_bytes().replace(b"/_next/", prefix)