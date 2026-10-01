# Validation and repair

Generated projects follow the enforced lifecycle:

```text
inspect → install → build → READY
                    ↘ failure → diagnostics → repair (≤3) → revalidate
```

`BuildValidator` checks required project files, selects an allowlisted package manager, installs dependencies with timeouts, persists an install fingerprint, and only then runs the build. It uses absolute executable resolution, `shell=False`, fixed argv, captured output limits, and no website-derived commands.

The repair agent receives structured diagnostics and a bounded set of relevant source files. It returns exact-match text patches. `repair.patch` rejects absolute/traversal paths, secret files, oversized edits, ambiguous anchors, and command-shaped content. Every applied patch goes back through inspect/install/build before the project can become `READY`.

The preview is a read-only static export served from the generated project's `out/` directory. Its path resolver prevents traversal and rewrites Next asset URLs into the project-scoped API route.
