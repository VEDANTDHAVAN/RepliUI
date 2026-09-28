# Agent pipeline

`WebsiteAnalyzer` drives Playwright to capture title, metadata, headings, copy, navigation, forms, images, colors, sections, desktop/mobile screenshots, and responsive hints, at 1440×900 and 390×844. The page is walked in-browser against a fixed style allowlist; BeautifulSoup is not involved. `WebsiteSpec` is the compact, strongly typed boundary used by later stages. `AIGatewayProvider` uses the OpenAI-compatible AI Gateway endpoint with `AI_GATEWAY_API_KEY`; no provider key is hardcoded. `Planner` sends only the normalized spec and falls back deterministically when the gateway is unavailable.

The orchestrator states are `QUEUED`, `ANALYZING`, `ANALYZED`, `PLANNING`, `GENERATING`, `GENERATED`, `VALIDATING`, `READY`, `MODIFYING`, and `FAILED`. The generator creates reusable React output. The validator runs the inspect → install → build lifecycle with a timeout and returns structured diagnostics. The modifier edits only files within the generated project and revalidates.

## The agent is a coordinator, not an analyzer

`app/agents/pipeline.py` is the orchestration facade. It sequences the stages, owns the typed error mapping, and decides what a user sees. It holds no extraction or planning logic.

The analyzer is split the same way: `analyzers/scripts.py` captures, and one small Python module per concern — `colors`, `typography`, `sections`, `components`, `responsive`, `document`, `assets` — interprets the payload. Each of those is a plain function over `list[RawNode]`, which is why the extraction layer is tested without a browser and why the browser only runs in `tests/test_analyzer_integration.py`.

There is no `layout.py`. Layout is the one concern with no Python module of its own: the in-page half is `LAYOUT_SCRIPT` in `scripts.py`, and the Python half is read out of the payload by `components.py` (grid tracks, repeated siblings) and `sections.py` (`LayoutSpec` per band).

The planner follows the same rule. `planners/plan_builder.py` builds a `GenerationPlan` from the spec alone; `planners/prompt.py` compresses the spec for the model; `planners/parsing.py` extracts JSON and reports what was missing. The AI response refines a plan the code can already produce — it never supplies the only copy of one.

## Validation is not bypassed

`READY` is reached only when `pnpm build` exits zero. There is no skip path: a project whose dependencies fail to install stops at `stage=install` with the installer's own stdout and stderr, and a project whose build fails stops at `stage=build`. Both land in `FAILED` with the stage recorded in the manifest, and the dashboard shows the stage and the failing command.

The build is never attempted on top of an incomplete install. This ordering is enforced in `BuildValidator.validate` and covered by tests, because a build run against missing `node_modules` reports the misleading `'next' is not recognized` rather than the real cause.

## Diagnostics

`ValidationResult` carries the full build output plus `package_manager` and an `install` block (`ok`, `command`, `reused_node_modules`, `stdout`, `stderr`, `errors`). `tests/test_build_validator.py` and `tests/test_pipeline_e2e.py` cover the generated-project → install → build path with a real package manager; `tests/test_package_manager.py` covers detection and the allowlist.

Planning diagnostics are the same shape: `planners/parsing.py` diffs the model's response against the expected fields and reports the gap, so a partially-correct plan is visible instead of silently lossy.

## Test budget

`pytest` is 167 tests in roughly 7 minutes. Two suites dominate that time: `tests/test_analyzer_integration.py` launches Chromium for every fixture (~60s), and `tests/test_pipeline_e2e.py` generates a project, installs it, and runs a real production build.

`pytest -m "not slow"` deselects the 8 marked install/build tests and leaves 159 in about a minute — the unmarked browser analyzer suite is still in that set. For a sub-second check of the pure-Python stages, run the extraction and planner modules directly:

```bash
pytest tests/test_extraction_structure.py tests/test_extraction_style.py \
       tests/test_website_spec.py tests/test_planner.py \
       tests/test_url_validation.py tests/test_storage.py   # ~2s
```

Run the full set before changing extraction or planning.
