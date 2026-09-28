# RepliUI API

FastAPI service behind the RepliUI dashboard. It analyzes a public URL, compresses the result into a typed `WebsiteSpec`, plans a Next.js project, generates it, and validates the build.

## Layout

| Path | Role |
| --- | --- |
| `app/main.py` | FastAPI app and routes. Module-level `analyze_site` / `generate_project` are the patch points the E2E tests stub. |
| `app/agents/pipeline.py` | Orchestration facade. Owns the analyze → plan → generate sequence and maps errors to user-facing messages. |
| `app/analyzers/` | Playwright capture and deterministic extraction. |
| `app/planners/` | `GenerationPlan` construction, prompt compression, and safe AI parsing. |
| `app/generators/` | Deterministic Next.js project emitter. |
| `app/validators/` | inspect → install → build lifecycle and package-manager detection. |
| `app/models/schemas.py` | Every cross-stage contract. |

## Analysis is two stages

**Capture** (`analyzers/scripts.py`, run in-page) marks elements, then walks the DOM collecting geometry, text, assets, forms, and a fixed allowlist of computed style properties (`STYLE_PROPERTIES`). It also detects repeated sibling groups and re-runs at 1440×900 and 390×844. Payloads are parsed into `raw_models.RawNode`.

**Extraction** is pure Python over those payloads, one module per concern: `colors`, `typography`, `sections`, `components`, `responsive`, `document`, `assets`. Each is a plain function over `list[RawNode]`, so all of it is unit-testable without a browser.

Layout is the exception: there is no `layout.py`. The in-page half is `LAYOUT_SCRIPT` in `scripts.py`, and the Python half is read out of the payload by `components.py` (grid tracks, repeated siblings) and `sections.py` (per-band `LayoutSpec`).

`WebsiteAnalyzer` is the orchestrator over those modules. It holds no extraction logic of its own.

## Raw HTML never reaches the model

The planner receives a compressed projection of the spec — theme, type scale, section roles, component inventory, responsive notes. No markup is included, so page content cannot smuggle instructions into the prompt.

One AI call is made per analysis. If the gateway is unconfigured, the response is unparseable, or the plan fails validation, the deterministic `build_fallback_plan` produces the same shape from the spec alone. Both paths are covered in `tests/test_planner.py`.

## Running

```bash
pip install -e . && playwright install chromium
uvicorn app.main:app --reload --port 8000
```

## Tests

```bash
pytest                 # 167 tests, ~7 min
pytest -m "not slow"   # 159 tests, ~1 min (drops the install/build E2E)
```

Two suites dominate the runtime. `tests/test_analyzer_integration.py` launches Chromium for every fixture and asserts on the extracted spec; `tests/test_pipeline_e2e.py` (marked `slow`) generates a project, installs it with a real package manager, and runs a real production build. For a sub-second check of the pure-Python stages:

```bash
pytest tests/test_extraction_structure.py tests/test_extraction_style.py \
       tests/test_website_spec.py tests/test_planner.py \
       tests/test_url_validation.py tests/test_storage.py
```
