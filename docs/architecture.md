# Architecture

The Next.js dashboard submits a URL to FastAPI. A background task creates a project manifest, runs `WebsiteAnalyzer`, persists screenshots and the typed `WebsiteSpec`, sends the compact spec to the gateway-backed planner when configured, generates independent component files, and runs an allowlisted `npm run build` with a timeout. Project status is persisted as JSON and polled by the dashboard.

The storage boundary is `generated/projects/{project_id}`. Path validation prevents project IDs from escaping that directory. The generated application contains `app/page.tsx`, `app/styles.css`, `components/Section.tsx`, and its own package manifest.
