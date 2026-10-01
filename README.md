# RepliUI

RepliUI is an MVP AI website reconstruction agent. It loads a public URL in Playwright at desktop and mobile widths, reduces the captured DOM and visual signals to a typed `WebsiteSpec`, plans an independent React/Next.js project, generates it, validates it, and accepts targeted natural-language edits.

## Run locally

1. Install Python dependencies from `apps/api/pyproject.toml` and ensure Playwright Chromium is installed. Validation also needs `pnpm` (or `npm`/`yarn`) on `PATH`.
2. Start the API: `cd apps/api; uvicorn app.main:app --reload --port 8000`.
3. Start the dashboard: `pnpm --dir apps/web dev`.
4. Open `http://localhost:3000` and enter a public `https://` URL.

AI calls use Vercel AI Gateway through its OpenAI-compatible Chat Completions endpoint. Configure `AI_GATEWAY_API_KEY`; `AI_GATEWAY_BASE_URL` and `AI_GATEWAY_MODEL` are optional. Deterministic extraction and generation keep the workflow runnable without credentials. `NEXT_PUBLIC_API_URL`, `GENERATED_PROJECTS_DIR`, `STORAGE_DIR`, `PLAYWRIGHT_HEADLESS`, `PACKAGE_MANAGER`, `VALIDATION_INSTALL_TIMEOUT`, and `VALIDATION_BUILD_TIMEOUT` are also supported.

## Workflow

URL → Playwright capture (1440×900 and 390×844) → deterministic extraction → normalized WebsiteSpec → GenerationPlan → reusable React project → install dependencies → build → (bounded self-repair if it fails) → targeted modification. Generated files never iframe or proxy the source site.

Extraction is pure Python over the captured payload, one module per concern, and raw HTML never reaches the model — the planner sees a compressed projection of the spec, so page content cannot smuggle instructions into the prompt.

Validation is a real build, not a smoke test. A project reaches `READY` only when its production build exits zero; otherwise it stops at the `install` or `build` stage with the package manager's own output. See [docs/architecture.md](docs/architecture.md).

A failed build starts a bounded self-repair: the loop parses the compiler output into diagnostics, asks the gateway for a patch, and rebuilds, at most three times. The model only proposes text — the backend applies it as validated data, refusing anything that escapes the project directory, touches a dotfile or secret-shaped file, or carries shell text. Every rebuild still goes through the validator, so repair never downgrades what `READY` means. See [docs/architecture.md](docs/architecture.md).

## Tests

```
cd apps/api
uv run pytest                 # 287 tests; the slow set is ~8 min of real install + build
uv run pytest -m "not slow"   # 279 tests, ~1 min, drops the install/build E2E
```

The suite generates a real project, installs it with a real package manager, and runs a real Next.js production build, so a green run means the lifecycle actually works. It needs `pnpm` on `PATH` and network access; tests that need it are marked `slow` and skip when no package manager is installed.

Note that `-m "not slow"` still includes the browser-backed analyzer suite, which is the other slow part. See [apps/api/README.md](apps/api/README.md) for the sub-second pure-Python subset.

See [docs/architecture.md](docs/architecture.md), [docs/agent.md](docs/agent.md), and [docs/demo.md](docs/demo.md).

## Limitations

The current MVP uses gateway-backed structured planning with a deterministic fallback, a deterministic generator, gateway-backed repair bounded to three attempts, and lightweight modification rules; managed preview process orchestration is the next extension point. Asset downloads are represented in analysis and can be added to the generator without changing the API contract. Validation installs dependencies from the public registry on every fresh project, which is slow and needs network access; a shared store or offline cache is the next optimization.
