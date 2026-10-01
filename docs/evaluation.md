# Evaluation protocol

The repository contains deterministic analyzer, planner, generator, validator, repair, preview, storage, and security tests. A full live evaluation should be run with network access, Chromium, and a configured package manager.

Use three structurally different public pages (marketing/SaaS, editorial/content, and product/catalog) or assignment-approved fixtures. For each project record:

1. URL and project ID.
2. Desktop/mobile screenshot paths and extracted section/component counts.
3. Planner source (`ai` or `fallback`) and token/latency fields.
4. Generated files and package manager.
5. Install/build result and preview URL.
6. One targeted modification and rebuild result.
7. Repair attempts, if any, and visual observations.

The controlled integration path is preferable for CI: serve a local fixture, run the API pipeline with a stub analyzer/planner, and use the real generated-project validator where the package manager is available. No evaluation domain is hardcoded into application logic.

Known evaluation limitations: live site access and package installation are environment-dependent; the MVP uses deterministic geometry/style extraction rather than a paid vision model; asset localization is best-effort.
