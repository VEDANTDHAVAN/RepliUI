from __future__ import annotations
import logging, re, uuid
from datetime import datetime, timezone
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .analyzers import WebsiteAnalyzer
from .ai import Planner
from .generators import ProjectGenerator
from .models.schemas import AgentState, GenerationRequest, ModificationRequest, ProjectManifest
from .storage import list_manifests, load_manifest, save_manifest, project_dir
from .validators import BuildValidator

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
    try:
        update(m, AgentState.ANALYZING, "Analyzing website...")
        m.spec = WebsiteAnalyzer().analyze(m.url, project_id)
        update(m, AgentState.ANALYZED, "✓ Website loaded · DOM, responsive layout, and assets extracted")
        update(m, AgentState.PLANNING, "Planning reusable React components...")
        plan = Planner().create(m.spec)
        update(m, AgentState.GENERATING, "Generating independent frontend...")
        ProjectGenerator().generate(project_id, m.spec)
        update(m, AgentState.GENERATED, "✓ Project structure and component files created")
        update(m, AgentState.VALIDATING, "Validating generated application...")
        m.validation = BuildValidator().validate(project_id)
        if m.validation.success: update(m, AgentState.READY, "✓ Build validated · Ready for preview and modification")
        else: update(m, AgentState.FAILED, "Build failed; inspect diagnostics", "Generated project needs repair")
    except Exception:
        logging.exception("pipeline failed")
        update(m, AgentState.FAILED, "Pipeline failed", "Could not complete the reconstruction. Check the URL and try again.")

@app.get("/api/health")
@app.get("/health")
async def health(): return {"status":"ok", "service":"repliui-api"}

@app.post("/api/projects", response_model=ProjectManifest, status_code=202)
async def create_project(request: GenerationRequest, background_tasks: BackgroundTasks):
    m = ProjectManifest(project_id=uuid.uuid4().hex[:12], url=request.url); save_manifest(m); background_tasks.add_task(pipeline, m.project_id); return m

@app.get("/api/projects", response_model=list[ProjectManifest])
async def projects(): return list_manifests()

@app.get("/api/projects/{project_id}", response_model=ProjectManifest)
async def project(project_id: str): return get_project(project_id)

@app.get("/api/projects/{project_id}/status", response_model=ProjectManifest)
async def status(project_id: str): return get_project(project_id)

@app.get("/api/projects/{project_id}/analysis")
async def analysis(project_id: str):
    m = get_project(project_id)
    if not m.spec: raise HTTPException(404, "Analysis is not ready")
    return m.spec

@app.post("/api/projects/{project_id}/validate", response_model=ProjectManifest)
async def validate(project_id: str):
    m = get_project(project_id); m.validation = BuildValidator().validate(project_id); update(m, AgentState.READY if m.validation.success else AgentState.FAILED); return m

@app.post("/api/projects/{project_id}/modify", response_model=ProjectManifest)
async def modify(project_id: str, request: ModificationRequest, background_tasks: BackgroundTasks):
    m = get_project(project_id); update(m, AgentState.MODIFYING, "Applying targeted modification..."); background_tasks.add_task(modify_project, project_id, request.instruction); return m

def modify_project(project_id: str, instruction: str):
    m = load_manifest(project_id); root = project_dir(project_id); css = root / "app" / "styles.css"; lower = instruction.lower()
    if "blue" in lower or "primary color" in lower:
        css.write_text(re.sub(r"--accent:[^;]+;", "--accent:#2563eb;", css.read_text(encoding="utf-8")), encoding="utf-8")
    if "sticky" in lower and "nav" in lower: css.write_text(css.read_text(encoding="utf-8") + "\nnav{position:sticky;top:0;background:var(--paper);z-index:5}\n", encoding="utf-8")
    m.modifications.append(instruction); m.validation = BuildValidator().validate(project_id); update(m, AgentState.READY if m.validation.success else AgentState.FAILED, "✓ Modification validated")
