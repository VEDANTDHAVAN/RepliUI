from starlette.testclient import TestClient
from app import main as api
from app.storage import project_dir

pid = "preview0001"
api.save_manifest(api.ProjectManifest(project_id=pid, url="https://example.com", title="T"))
out = project_dir(pid) / "out"
static = out / "_next" / "static"
static.mkdir(parents=True, exist_ok=True)
(static / "css").mkdir(parents=True, exist_ok=True)
(static / "chunks").mkdir(parents=True, exist_ok=True)
(out / "index.html").write_text(
    '<link rel="stylesheet" href="/_next/static/css/app.css">'
    '<script src="/_next/static/chunks/main.js"></script>',
    encoding="utf-8",
)
with TestClient(api.app) as c:
    r = c.get(f"/api/projects/{pid}/preview/")
    print("status", r.status_code, "ct", r.headers.get("content-type"), "len", len(r.content))
    print("text repr:", repr(r.text[:300]))
    print("content repr:", repr(r.content[:300]))
    import re
    print("refs in content:", re.findall(rb"/api/projects/preview0001/preview/_next/[a-zA-Z0-9/._-]+", r.content))
    print("/_next/ in content:", b"/_next/" in r.content)