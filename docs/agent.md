# Agent pipeline

`WebsiteAnalyzer` uses Playwright and BeautifulSoup to collect title, metadata, headings, copy, navigation, forms, images, colors, sections, desktop/mobile screenshots, and responsive hints. `WebsiteSpec` is the compact, strongly typed boundary used by later stages. `AIGatewayProvider` uses the OpenAI-compatible AI Gateway endpoint with `AI_GATEWAY_API_KEY`; no provider key is hardcoded. `Planner` sends only the normalized spec and falls back deterministically when the gateway is unavailable.

The orchestrator states are `QUEUED`, `ANALYZING`, `ANALYZED`, `PLANNING`, `GENERATING`, `GENERATED`, `VALIDATING`, `READY`, `MODIFYING`, and `FAILED`. The generator creates reusable React output. The validator runs the inspect → install → build lifecycle with a timeout and returns structured diagnostics. The modifier edits only files within the generated project and revalidates.

## Validation is not bypassed

`READY` is reached only when `pnpm build` exits zero. There is no skip path: a project whose dependencies fail to install stops at `stage=install` with the installer's own stdout and stderr, and a project whose build fails stops at `stage=build`. Both land in `FAILED` with the stage recorded in the manifest, and the dashboard shows the stage and the failing command.

The build is never attempted on top of an incomplete install. This ordering is enforced in `BuildValidator.validate` and covered by tests, because a build run against missing `node_modules` reports the misleading `'next' is not recognized` rather than the real cause.

## Diagnostics

`ValidationResult` carries the full build output plus `package_manager` and an `install` block (`ok`, `command`, `reused_node_modules`, `stdout`, `stderr`, `errors`). `tests/test_build_validator.py` and `tests/test_pipeline_e2e.py` cover the generated-project → install → build path with a real package manager; `tests/test_package_manager.py` covers detection and the allowlist.
