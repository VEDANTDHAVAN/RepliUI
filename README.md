# RepliUI

RepliUI is an MVP AI website reconstruction agent. It loads a public URL in Playwright, compresses the DOM and visual signals into a typed `WebsiteSpec`, generates an independent React/Next.js project, validates it, and accepts targeted natural-language edits.

## Run locally

1. Install Python dependencies from `apps/api/pyproject.toml` and ensure Playwright Chromium is installed.
2. Start the API: `cd apps/api; uvicorn app.main:app --reload --port 8000`.
3. Start the dashboard: `pnpm --dir apps/web dev`.
4. Open `http://localhost:3000` and enter a public `https://` URL.

AI calls use Vercel AI Gateway through its OpenAI-compatible Chat Completions endpoint. Configure `AI_GATEWAY_API_KEY`; `AI_GATEWAY_BASE_URL` and `AI_GATEWAY_MODEL` are optional. Deterministic extraction and generation keep the workflow runnable without credentials. `NEXT_PUBLIC_API_URL`, `GENERATED_PROJECTS_DIR`, `STORAGE_DIR`, and `PLAYWRIGHT_HEADLESS` are also supported.

## Workflow

URL → Playwright analysis → normalized WebsiteSpec → reusable React project → bounded build validation → targeted modification. Generated files never iframe or proxy the source site.

See [docs/architecture.md](docs/architecture.md), [docs/agent.md](docs/agent.md), and [docs/demo.md](docs/demo.md).

## Limitations

The current MVP uses gateway-backed structured planning with a deterministic fallback, a deterministic generator, and lightweight modification rules; provider-backed repair and managed preview process orchestration are the next extension points. Asset downloads are represented in analysis and can be added to the generator without changing the API contract.
