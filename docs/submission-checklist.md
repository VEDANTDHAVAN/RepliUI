# Submission checklist

| Requirement | Implemented | Tested | Evidence |
|---|---:|---:|---|
| URL validation and project creation | Yes | Yes | `test_url_validation.py`, `main.py` |
| Playwright analysis at desktop/mobile sizes | Yes | Yes | `test_analyzer_integration.py` |
| Typed persisted WebsiteSpec | Yes | Yes | `models/schemas.py`, `test_website_spec.py`, `test_storage.py` |
| AI Gateway planner with fallback | Yes | Yes | `planners/`, `test_planner.py`; live key not required |
| Independent Next.js generation | Yes | Yes | `test_generator.py` |
| Inspect/install/build validation | Yes | Yes | `test_build_validator.py`, `test_pipeline_e2e.py` marked slow |
| Three-attempt self-repair | Yes | Yes | `tests/test_repair_*.py` |
| Local preview | Yes | Yes | `test_preview.py` |
| Safe targeted modification | Yes | Yes | `modifiers/`, repair patch tests |
| Command/path/secret protections | Yes | Yes | `test_package_manager.py`, `test_storage.py`, `test_repair_patch.py` |
| Responsive dashboard and polling | Yes | Manual | `apps/web/src/app/page.tsx`, `globals.css` |
| Three-website evidence | Partial | Not in restricted run | `docs/evaluation.md` |
| Frontend automated tests | Partial | No test runner configured | Manual/browser verification required |
