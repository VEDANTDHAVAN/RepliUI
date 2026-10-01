# Submission audit

Audited 2026-09-30 against the assignment brief and the actual repository execution paths.

| Requirement | Source | Status | Evidence | Missing work |
|---|---|---|---|---|
| Next.js dashboard | Assignment §18 | IMPLEMENTED | `apps/web/src/app/page.tsx` and `globals.css` | Browser smoke test requires local services |
| FastAPI API and project persistence | §14, §24 | IMPLEMENTED | `app/main.py`, `app/storage.py`, JSON manifests | Background tasks are in-process |
| Playwright desktop/mobile analysis | §4, §19 | IMPLEMENTED | `app/analyzers/__init__.py`, `scripts.py`, analyzer integration tests | Requires Chromium installed |
| Deterministic DOM/style/section extraction | §4, §20 | IMPLEMENTED | `analyzers/{colors,typography,sections,components,responsive}.py` and unit tests | No vision model comparison |
| Typed WebsiteSpec | §5 | IMPLEMENTED | `models/schemas.py`, persistence tests | — |
| AI Gateway planner | §6–7, §22 | IMPLEMENTED | `planners/planner.py`, `ai/gateway.py`, fallback/parser tests | Live gateway requires `AI_GATEWAY_API_KEY` |
| Independent generated Next.js project | §8 | IMPLEMENTED | `generators/project.py`, generator tests | Generator currently emits a compact component set |
| Local asset localization | §9 | PARTIAL | Best-effort downloader in `ProjectGenerator`; failures fall back to source-free layout | Generated markup only uses localized assets when a component maps them |
| Inspect → install → build validation | §11–12 | IMPLEMENTED | `validators/build.py`, package manager tests, slow pipeline test | Registry/network required for real install |
| Bounded self-repair | §12 | IMPLEMENTED | `repair/{agent,loop,patch,diagnostics}.py`, repair tests | Repair is gateway-dependent; fallback reports no patch |
| Static local preview | §13 | IMPLEMENTED | `preview.py`, preview API/tests, exported Next build | Process-backed dev server lifecycle is intentionally replaced by static export |
| Natural-language modification | §16–17 | IMPLEMENTED | `modifiers/agent.py`, safe patch application, rebuild in `main.py` | Deterministic fallback supports common edits; unsupported edits fail safely |
| Security boundaries | §10, §17, §30 | IMPLEMENTED | path confinement, forbidden files, command allowlist, `shell=False`, timeouts | SSRF controls are limited to URL validation and browser isolation |
| Tests and mocked AI | §25 | IMPLEMENTED | 19 backend test modules; planner/repair tests avoid live gateway | Frontend has no automated test runner |
| Documentation | §26 | IMPLEMENTED | README plus architecture, agent, validation, demo, evaluation, checklist | Evaluation evidence is environment-dependent |
| Three-site evaluation | §18 | PARTIAL | `docs/evaluation.md` provides controlled protocol and evidence template | No live three-site run in this restricted environment |
