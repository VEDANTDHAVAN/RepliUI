# Architecture

The Next.js dashboard submits a URL to FastAPI. A background task creates a project manifest, runs `WebsiteAnalyzer`, persists screenshots and the typed `WebsiteSpec`, sends the compact spec to the gateway-backed planner when configured, generates independent component files, and then runs the **inspect → install → build** validation lifecycle. Project status is persisted as JSON and polled by the dashboard.

The storage boundary is `generated/projects/{project_id}`. Path validation prevents project IDs from escaping that directory. The generated application contains `app/page.tsx`, `app/styles.css`, `components/Section.tsx`, `tsconfig.json`, `next-env.d.ts`, and its own package manifest.

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
