# Agent pipeline

`WebsiteAnalyzer` drives Playwright to capture title, metadata, headings, copy, navigation, forms, images, colors, sections, desktop/mobile screenshots, and responsive hints, at 1440×900 and 390×844. The page is walked in-browser against a fixed style allowlist; BeautifulSoup is not involved. `WebsiteSpec` is the compact, strongly typed boundary used by later stages. `AIGatewayProvider` uses the OpenAI-compatible AI Gateway endpoint with `AI_GATEWAY_API_KEY`; no provider key is hardcoded. `Planner` sends only the normalized spec and falls back deterministically when the gateway is unavailable.

The orchestrator states are `QUEUED`, `ANALYZING`, `ANALYZED`, `PLANNING`, `GENERATING`, `GENERATED`, `VALIDATING`, `REPAIRING`, `READY`, `MODIFYING`, and `FAILED`. The generator creates reusable React output. The validator runs the inspect → install → build lifecycle with a timeout and returns structured diagnostics. The modifier edits only files within the generated project and revalidates.

## The agent is a coordinator, not an analyzer

`app/agents/pipeline.py` is the orchestration facade. It sequences the stages, owns the typed error mapping, and decides what a user sees. It holds no extraction or planning logic.

The analyzer is split the same way: `analyzers/scripts.py` captures, and one small Python module per concern — `colors`, `typography`, `sections`, `components`, `responsive`, `document`, `assets` — interprets the payload. Each of those is a plain function over `list[RawNode]`, which is why the extraction layer is tested without a browser and why the browser only runs in `tests/test_analyzer_integration.py`.

There is no `layout.py`. Layout is the one concern with no Python module of its own: the in-page half is `LAYOUT_SCRIPT` in `scripts.py`, and the Python half is read out of the payload by `components.py` (grid tracks, repeated siblings) and `sections.py` (`LayoutSpec` per band).

The planner follows the same rule. `planners/plan_builder.py` builds a `GenerationPlan` from the spec alone; `planners/prompt.py` compresses the spec for the model; `planners/parsing.py` extracts JSON and reports what was missing. The AI response refines a plan the code can already produce — it never supplies the only copy of one.

## Validation is not bypassed

`READY` is reached only when `pnpm build` exits zero. There is no skip path: a project whose dependencies fail to install stops at `stage=install` with the installer's own stdout and stderr, and a project whose build fails stops at `stage=build`. Both land in `FAILED` with the stage recorded in the manifest, and the dashboard shows the stage and the failing command.

The build is never attempted on top of an incomplete install. This ordering is enforced in `BuildValidator.validate` and covered by tests, because a build run against missing `node_modules` reports the misleading `'next' is not recognized` rather than the real cause.

## Self-repair

A failed build does not end the run. `RepairLoop` (`app/repair/loop.py`) takes the `ValidationResult`, asks `RepairAgent` for a patch, applies it, and rebuilds — at most three times. The loop owns the budget, the state transitions, and the rebuild; the agent only proposes text. The agent never runs a command, so nothing it returns can widen what executes.

The loop is reached from `main.validate_project` in the same `POST /api/projects/{id}/validate` request that performs the build. If the build passes there is no repair and no model call. `?run_repair=false` restores the old fail-fast behaviour for the demo. A project that reaches `READY` via repair is given a `preview_url` on the way out, on the same condition as a project that built first time — otherwise a repaired project would report `READY` with nothing for the dashboard to embed.

Each attempt is one model call, one validated patch, and one rebuild. A green build ends the loop immediately. Exhausting three attempts lands in `FAILED` with the last `ValidationResult` attached — repair never masks the original compiler output.

`app/repair/diagnostics.py` turns build output into `BuildDiagnostic` records with a file, line, category, and message. It strips ANSI colour, drops tsc code frames, and filters Next.js progress and telemetry banners, because a real `next build` failure emits roughly sixteen lines for one type error and the model should only see the one that matters. The same file is what turns `pnpm install` failures into `DEPENDENCY_ERROR` and module-resolution failures into `MODULE_NOT_FOUND`.

The agent is given the diagnostics plus only the files they point at — a failing file, anything it imports, and `package.json` — capped at eight files and 256 KiB. `.env` and other secret-shaped files are never read into a prompt, and the prompt carries a small project tree for orientation when the diagnostics are too sparse to locate the failure.

`app/repair/patch.py` is the security boundary. Every change is a structured Pydantic object: a project-relative file, an `original` string, a `replacement`, and a reason. A change is refused if the path escapes the project, targets a dotfile, matches a known-sensitive name, or carries shell and subprocess-shaped text. `original` must occur exactly once in the file, so a patch cannot silently edit the wrong one of several identical blocks. Validation happens before any write, and a refused change aborts the whole patch — a plan is applied whole or not at all.

A malformed or non-JSON model response yields an empty change set, a recorded reason, and no file write; it consumes one attempt and the loop moves on.

## Diagnostics

`ValidationResult` carries the full build output plus `package_manager` and an `install` block (`ok`, `command`, `reused_node_modules`, `stdout`, `stderr`, `errors`). `tests/test_build_validator.py` and `tests/test_pipeline_e2e.py` cover the generated-project → install → build path with a real package manager; `tests/test_package_manager.py` covers detection and the allowlist.

Planning diagnostics are the same shape: `planners/parsing.py` diffs the model's response against the expected fields and reports the gap, so a partially-correct plan is visible instead of silently lossy.

## Test budget

`pytest` is 287 tests. Two suites dominate the time: `tests/test_analyzer_integration.py` launches Chromium for every fixture, and `tests/test_pipeline_e2e.py` generates a project, installs it, and runs a real production build. The slow set takes roughly eight minutes on its own and needs a real package manager on `PATH`.

`pytest -m "not slow"` deselects the 8 marked install/build tests and leaves 279 in about a minute — the unmarked browser analyzer suite is still in that set. For a sub-second check of the pure-Python stages, run the extraction and planner modules directly:

```bash
pytest tests/test_extraction_structure.py tests/test_extraction_style.py \
       tests/test_website_spec.py tests/test_planner.py \
       tests/test_url_validation.py tests/test_storage.py   # ~2s
```

The repair loop is covered by four fast modules and needs no API key, because the gateway is faked at the `AIGatewayProvider` boundary:

```bash
pytest tests/test_repair_diagnostics.py tests/test_repair_patch.py \
       tests/test_repair_agent.py tests/test_repair_loop.py \
       tests/test_repair_integration.py                      # ~8s
```

`_manual_repair.py` is not a pytest module. It generates a project, injects a real TypeScript error, and drives the loop with a scripted gateway against a real `next build`, so the parser and the patch are exercised on genuine compiler output rather than a fixture. It needs a package manager and takes about a minute:

```bash
python _manual_repair.py
```

Run the full set before changing extraction or planning.
