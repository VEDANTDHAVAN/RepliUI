# Architecture

The Next.js dashboard submits a URL to FastAPI. A background task creates a project manifest, runs `WebsiteAnalyzer`, persists screenshots and the typed `WebsiteSpec`, sends the compact spec to the gateway-backed planner when configured, generates independent component files, and then runs the **inspect → install → build** validation lifecycle. Project status is persisted as JSON and polled by the dashboard.

The storage boundary is `generated/projects/{project_id}`. Path validation prevents project IDs from escaping that directory. The generated application contains `app/page.tsx`, `app/styles.css`, `components/Section.tsx`, `tsconfig.json`, `next-env.d.ts`, and its own package manifest.

## Analysis is capture, then extract

`WebsiteAnalyzer` delegates to two stages with a typed boundary between them.

**Capture** runs in the browser. `analyzers/scripts.py` marks elements for correlation, walks the DOM, and collects geometry, text, assets, forms, and a fixed allowlist of computed style properties (`STYLE_PROPERTIES`). Repeated sibling groups are detected in-page, and the whole pass runs at both 1440×900 and 390×844 so responsive behaviour is observed rather than guessed. The payload is parsed into `raw_models.RawNode`.

**Extraction** is pure Python over those payloads, one module per concern — `colors`, `typography`, `sections`, `components`, `responsive`, `document`, `assets`. Each is a plain function over `list[RawNode]`, so the entire extraction layer is testable without a browser.

Layout has no Python module of its own. `LAYOUT_SCRIPT` in `scripts.py` detects grid and flex geometry in-page, and the result is read back out of the payload by `components.py` (grid tracks, repeated siblings) and `sections.py` (per-band `LayoutSpec`).

This split is the reason the analyzer is a small orchestrator: it sequences the modules and holds no extraction logic of its own.

## Section detection is geometric, and that has a sharp edge

Bands are found by rectangle, not by DOM ancestry. A full-width band with children becomes a candidate, and its contained nodes come from a purely geometric test against its rectangle.

The bottom and right bounds are **exclusive**. Section bands tile the page and share their edges, so an inclusive `y <= bottom` lets each band swallow the top row of the section stacked directly below it — the card grid would appear to contain the signup form that follows it.

Selector prefixes cannot be used to settle this. The browser script caps a node's path at four segments (`pathOf`), which truncates the *top* of any deep node's selector, so a child's path stops being a prefix of its parent's. Truncation happens at the top; the missing part is exactly the part that would disambiguate.

## Raw HTML never reaches the model

The planner receives a compressed projection of the spec: theme tokens, type scale, section roles, component inventory, responsive notes. No markup is included, so page content cannot smuggle instructions into the prompt. The one AI call is made per analysis, and `build_fallback_plan` produces the same plan shape from the spec alone whenever the gateway is unconfigured, the response is unparseable, or the plan fails validation.

## Generated projects are installable by construction

The generator emits a complete, self-contained Next.js 14 + React 18 + TypeScript project. `typescript` and `@types/*` are `devDependencies` because `next build` type-checks `.tsx` sources; without them the build aborts with `The "id" argument must be of type string. Received undefined`.

## Validation lifecycle

`BuildValidator` has three stages and refuses to skip ahead:

| Stage | What it does | Failure result |
| --- | --- | --- |
| `inspect` | Requires a generated `package.json` | `stage=inspect` |
| `install` | Runs the detected package manager's install command | `stage=install`, `install` diagnostics |
| `build` | Runs the build command, only after a successful install | `stage=build` |

`node_modules` is produced by the install stage — it is never part of the generated output and is never expected from the generator.

## Package manager selection

`validators/package_manager.py` picks a manager in this order: explicit `PACKAGE_MANAGER` preference → lockfile in the project → `packageManager` field in the generated `package.json` → a globally available manager → `pnpm`. A preference naming a manager that is not on `PATH` is skipped rather than selected, so validation never launches a missing binary.

`pnpm install` runs with `--ignore-workspace` and `--no-frozen-lockfile`. Both are required and neither is optional polish:

- `--ignore-workspace` — generated projects live *inside* the RepliUI pnpm workspace. Without it, pnpm walks up, finds the repository `pnpm-workspace.yaml`, reports `Scope: all 2 workspace projects`, and installs nothing for the generated project. No `node_modules` appears and the build fails with `'next' is not recognized`.
- `--no-frozen-lockfile` — validation sets `CI=1` to keep the manager non-interactive, which makes pnpm default to `--frozen-lockfile`. A regenerated project's lockfile is legitimately stale relative to the freshly written `package.json`, so the default fails with `ERR_PNPM_OUTDATED_LOCKFILE`.

## Command allowlist

`package_manager._ALLOWED_COMMANDS` is the only source of executable argv. Callers receive a pre-built `Command`, and `assert_allowed` re-validates the argv immediately before `subprocess` — so no argument, including a mutated or future caller-supplied one, can widen what runs. Commands are executed with `shell=False` against a resolved absolute executable path. Nothing derived from the analyzed website ever reaches a shell.

## Install reuse

Reuse is keyed to a fingerprint of `dependencies`, `devDependencies` and `packageManager` from `package.json`, recorded in `node_modules/.repliui-install.json` after a successful install. Rebuilding an unchanged project reuses `node_modules`; changing any dependency triggers a reinstall. Mere existence of `node_modules` is not treated as a valid install.
