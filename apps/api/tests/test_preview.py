"""Static preview serving: prerendered HTML, asset rewrite, traversal guard."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import main as api
from app import preview
from app.storage import project_dir


def _write_export(project_id: str, spec) -> Path:
    """Write a minimal static export for ``project_id`` and return its root."""
    api.save_manifest(
        api.ProjectManifest(project_id=project_id, url="https://example.com", title=spec.title)
    )
    out = project_dir(project_id) / "out"
    static = out / "_next" / "static"
    static.mkdir(parents=True, exist_ok=True)
    (static / "css").mkdir(parents=True, exist_ok=True)
    (static / "chunks").mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(
        "<!doctype html><html><body>"
        '<link rel="stylesheet" href="/_next/static/css/app.css">'
        '<script src="/_next/static/chunks/main.js"></script>'
        "</body></html>",
        encoding="utf-8",
    )
    (static / "css" / "app.css").write_text("body{color:red}", encoding="utf-8")
    (static / "chunks" / "main.js").write_text("console.log('hi')", encoding="utf-8")
    return out


@pytest.fixture()
def client():
    with TestClient(api.app) as c:
        yield c


def test_preview_url_format():
    assert preview.preview_url("abc123") == "/api/projects/abc123/preview/"


def test_preview_unavailable_returns_409(client, projects_dir, spec):
    pid = "nopreview001"
    manifest = api.ProjectManifest(project_id=pid, url="https://example.com", title=spec.title)
    api.save_manifest(manifest)
    r = client.get(f"/api/projects/{pid}/preview")
    assert r.status_code == 409
    assert "not been built" in r.json()["detail"]


def test_preview_serves_rewritten_html(client, projects_dir, spec):
    pid = "preview0001"
    _write_export(pid, spec)
    r = client.get(f"/api/projects/{pid}/preview/")
    assert r.status_code == 200
    assert r.headers["content-type"].split(";")[0] == "text/html"
    # Every root-absolute asset reference was rewritten to the preview prefix.
    refs = re.findall(r"/api/projects/preview0001/preview/_next/[a-zA-Z0-9/._-]+", r.text)
    assert refs == [
        "/api/projects/preview0001/preview/_next/static/css/app.css",
        "/api/projects/preview0001/preview/_next/static/chunks/main.js",
    ]
    # No stale root-absolute references remain (the rewritten prefix legitimately
    # contains the substring, so match only when it is not preceded by the prefix).
    assert not re.search(r"(?<!/api/projects/preview0001/preview)/_next/", r.text)


def test_preview_serves_assets(client, projects_dir, spec):
    pid = "preview0002"
    _write_export(pid, spec)
    r = client.get(f"/api/projects/{pid}/preview/_next/static/chunks/main.js")
    assert r.status_code == 200
    assert r.headers["content-type"].split(";")[0] == "application/javascript"
    assert r.content == b"console.log('hi')"

    r = client.get(f"/api/projects/{pid}/preview/_next/static/css/app.css")
    assert r.status_code == 200
    assert r.headers["content-type"].split(";")[0] == "text/css"
    assert r.content == b"body{color:red}"


def test_preview_unknown_asset_returns_404(client, projects_dir, spec):
    pid = "preview0003"
    _write_export(pid, spec)
    r = client.get(f"/api/projects/{pid}/preview/_next/static/missing.js")
    assert r.status_code == 404


def test_preview_path_traversal_is_blocked(client, projects_dir, spec):
    pid = "preview0004"
    _write_export(pid, spec)
    # ``..`` must not escape the project's export directory.
    r = client.get(f"/api/projects/{pid}/preview/../../etc/passwd")
    assert r.status_code in (400, 404)


def test_preview_missing_project_returns_404(client, projects_dir):
    r = client.get("/api/projects/doesnotexist/preview/")
    assert r.status_code == 404


def test_preview_url_set_on_ready(monkeypatch, projects_dir, spec, client):
    """A successful build sets ``preview_url`` on the manifest."""
    pid = "preview0005"
    _write_export(pid, spec)

    from app.models.schemas import AgentState, ValidationResult

    fake = ValidationResult(
        success=True,
        package_manager="pnpm",
        install_ok=True,
        build_ok=True,
        stage="build",
        stdout="next build",
    )
    monkeypatch.setattr(api, "BuildValidator", lambda: type("V", (), {"validate": staticmethod(lambda pid: fake)})())

    r = client.post(f"/api/projects/{pid}/validate")
    assert r.status_code == 200
    result = api.load_manifest(pid)
    assert result.state is AgentState.READY
    assert result.preview_url == preview.preview_url(pid)