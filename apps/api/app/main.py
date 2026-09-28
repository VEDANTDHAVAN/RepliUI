from __future__ import annotations
import asyncio, logging, re, uuid
from datetime import datetime, timezone
from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from .agents import AnalysisPipeline, UserFacingError, to_user_message
from .analyzers import WebsiteAnalyzer
from .analyzers.urls import InvalidURLError, validate_url
from .planners import Planner
from .generators import ProjectGenerator
from .models.schemas import AgentState, GenerationRequest, ModificationRequest, ProjectManifest, ValidationError, ValidationResult
from .storage import list_manifests, load_manifest, save_manifest, project_dir
from .validators import BuildValidator
from .validators import package_manager as pm
from .preview import preview_available, preview_url

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="RepliUI API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_methods=["*"], allow_headers=["*"])

def get_project(project_id: str) -> ProjectManifest:
    try: return load_manifest(project_id)
    except (FileNotFoundError, ValueError): raise HTTPException(404, "Project not found")

def update(m: ProjectManifest, state: AgentState | None = None, message: str | None = None, error: str | None = None):
    if state: m.state = state
    if message: m.progress.append(message)
    m.error, m.updated_at = error, datetime.now(timezone.utc)
    save_manifest(m)

def pipeline(project_id: str):
    m = load_manifest(project_id)
    # Resolved at call time so tests can inject a browserless analyzer / keyless planner.
    analysis = AnalysisPipeline(analyzer=WebsiteAnalyzer(), planner=Planner())
    try:
        update(m, AgentState.ANALYZING, "Analyzing website...")
        m.spec = asyncio.run(analysis.analyze(m.url, project_id))
        m.plan = analysis.plan(project_id, m.spec)
        update(m, AgentState.ANALYZED, "✓ Website loaded · DOM, computed styles, assets, and both viewports captured")
        update(m, AgentState.PLANNING, f"✓ Plan ready ({m.plan.source} · {len(m.plan.components)} components)")
        update(m, AgentState.GENERATING, "Generating independent frontend...")
        ProjectGenerator().generate(project_id, m.spec)
        update(m, AgentState.GENERATED, "✓ Project structure and component files created")
        validator = BuildValidator()
        root, inspect_failure = validator.inspect(project_id)
        if inspect_failure is not None or root is None:
            m.validation = inspect_failure
            update(m, AgentState.FAILED, "Validation failed at inspect stage", "Generated project is missing required files")
            return
        manager = pm.detect(root)
        update(m, AgentState.VALIDATING, f"Installing dependencies with {manager}...")
        install = validator.install(root, manager)
        if not install.ok:
            m.validation = ValidationResult(success=False, stage="install", package_manager=manager, install=install, errors=install.errors or [ValidationError(message="Dependency installation failed")], stdout=install.stdout, stderr=install.stderr, duration_ms=install.duration_ms)
            update(m, AgentState.FAILED, "✗ Dependency installation failed; build not attempted", f"`{install.command or manager}` could not install the generated project's dependencies")
            return
        reused = "reusing existing node_modules" if install.reused_node_modules else "dependencies installed"
        update(m, AgentState.VALIDATING, f"✓ {reused} · building with {manager}")
        m.validation = validator.build(root, manager)
        m.validation.install = install
        if m.validation.success:
            # The build emits a static export; point the dashboard's sandboxed
            # iframe at it. Absent export means the build was incomplete.
            m.preview_url = preview_url(m.project_id) if preview_available(m.project_id) else None
            update(m, AgentState.READY, "✓ Build validated · Ready for preview and modification")
        else:
            update(m, AgentState.FAILED, "Build failed; inspect diagnostics", "Generated project needs repair")
    except UserFacingError as exc:
        logging.info("pipeline stopped: %s", exc)
        update(m, AgentState.FAILED, "Pipeline failed", str(exc))
    except Exception:
        logging.exception("pipeline failed")
        update(m, AgentState.FAILED, "Pipeline failed", "Could not complete the reconstruction. Check the URL and try again.")

@app.get("/api/health")
@app.get("/health")
async def health(): return {"status":"ok", "service":"repliui-api"}

@app.post("/api/projects", response_model=ProjectManifest, status_code=202)
async def create_project(request: GenerationRequest, background_tasks: BackgroundTasks):
    try:
        normalized = validate_url(request.url)
    except InvalidURLError as exc:
        raise HTTPException(422, str(exc))
    m = ProjectManifest(project_id=uuid.uuid4().hex[:12], url=normalized); save_manifest(m); background_tasks.add_task(pipeline, m.project_id); return m

@app.get("/api/projects", response_model=list[ProjectManifest])
async def projects(): return list_manifests()

@app.get("/api/projects/{project_id}", response_model=ProjectManifest)
async def project(project_id: str): return get_project(project_id)

@app.get("/api/projects/{project_id}/status", response_model=ProjectManifest)
async def status(project_id: str): return get_project(project_id)

@app.post("/api/projects/{project_id}/analyze", response_model=ProjectManifest)
async def analyze_project(project_id: str):
    """Run the Playwright analyzer for an existing project and persist the spec."""
    m = get_project(project_id)
    analysis = AnalysisPipeline()
    update(m, AgentState.ANALYZING, "Analyzing website...")
    try:
        m.spec = await analysis.analyze(m.url, project_id)
    except UserFacingError as exc:
        update(m, AgentState.FAILED, "Analysis failed", str(exc))
        return m
    update(m, AgentState.ANALYZED, "✓ Website loaded · DOM, computed styles, assets, and both viewports captured")
    return m

@app.post("/api/projects/{project_id}/plan", response_model=ProjectManifest)
async def plan_project(project_id: str):
    """Produce a GenerationPlan from the stored WebsiteSpec."""
    m = get_project(project_id)
    if not m.spec: raise HTTPException(409, "Analyze the website before planning")
    analysis = AnalysisPipeline()
    update(m, AgentState.PLANNING, "Planning reusable React components...")
    try:
        m.plan = analysis.plan(project_id, m.spec)
    except UserFacingError as exc:
        update(m, AgentState.FAILED, "Planning failed", str(exc))
        return m
    update(m, AgentState.PLANNING, f"✓ Plan ready ({m.plan.source} · {len(m.plan.components)} components)")
    return m

@app.get("/api/projects/{project_id}/analysis")
async def analysis(project_id: str):
    m = get_project(project_id)
    if not m.spec: raise HTTPException(404, "Analysis is not ready")
    return m.spec

@app.get("/api/projects/{project_id}/plan")
async def plan(project_id: str):
    m = get_project(project_id)
    if not m.plan: raise HTTPException(404, "Generation plan is not ready")
    return m.plan

@app.get("/api/projects/{project_id}/preview")
async def preview(project_id: str):
    """Serve the project's static export as a sandboxed preview.

    The dashboard embeds the returned URL in an ``<iframe>`` with a sandbox
    attribute. Asset paths inside the prerendered HTML are rewritten to this
    prefix so the browser can resolve ``/_next/static/...``.
    """
    get_project(project_id)
    if not preview_available(project_id):
        raise HTTPException(409, "Project has not been built; run validation first")
    return {"url": preview_url(project_id), "prefix": "/api/projects"}


@app.get("/api/projects/{project_id}/preview/{asset_path:path}")
async def preview_asset(project_id: str, asset_path: str):
    """Serve a single preview asset (the prerendered page or a chunk)."""
    from .preview import PreviewError, serve_preview

    get_project(project_id)
    try:
        body, content_type = serve_preview(project_id, asset_path)
    except FileNotFoundError:
        raise HTTPException(404, "Preview asset not found")
    except ValueError:
        raise HTTPException(400, "Invalid preview path")
    except PreviewError:
        raise HTTPException(409, "Project has not been built; run validation first")
    return Response(content=body, media_type=content_type)


@app.get("/api/projects/{project_id}/screenshots/{label}")
async def project_screenshot(project_id: str, label: str):
    """Serve a stored screenshot. Paths are resolved from the project id only."""
    from .storage import screenshot_path
    try:
        path = screenshot_path(project_id, label)
    except ValueError:
        raise HTTPException(400, "Invalid screenshot label")
    if not path.is_file(): raise HTTPException(404, "Screenshot not found")
    return FileResponse(path, media_type="image/png")

@app.post("/api/projects/{project_id}/validate", response_model=ProjectManifest)
async def validate(project_id: str):
    m = get_project(project_id)
    update(m, AgentState.VALIDATING, "Installing dependencies and building...")
    m.validation = BuildValidator().validate(project_id)
    if m.validation.success:
        m.preview_url = preview_url(m.project_id) if preview_available(m.project_id) else None
        update(m, AgentState.READY, "✓ Build validated")
    else:
        update(m, AgentState.FAILED, f"Validation failed at {m.validation.stage} stage")
    return m

@app.post("/api/projects/{project_id}/modify", response_model=ProjectManifest)
async def modify(project_id: str, request: ModificationRequest, background_tasks: BackgroundTasks):
    m = get_project(project_id); update(m, AgentState.MODIFYING, "Applying targeted modification..."); background_tasks.add_task(modify_project, project_id, request.instruction); return m

def modify_project(project_id: str, instruction: str):
    m = load_manifest(project_id); root = project_dir(project_id); css = root / "app" / "styles.css"; lower = instruction.lower()
    if "blue" in lower or "primary color" in lower:
        css.write_text(re.sub(r"--accent:[^;]+;", "--accent:#2563eb;", css.read_text(encoding="utf-8")), encoding="utf-8")
    if "sticky" in lower and "nav" in lower: css.write_text(css.read_text(encoding="utf-8") + "\nnav{position:sticky;top:0;background:var(--paper);z-index:5}\n", encoding="utf-8")
    m.modifications.append(instruction); m.validation = BuildValidator().validate(project_id); update(m, AgentState.READY if m.validation.success else AgentState.FAILED, "✓ Modification validated")
