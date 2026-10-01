# Demo flow (5–10 minutes)

1. Start FastAPI and the Next.js dashboard.
2. Enter a public URL such as a documentation page or marketing site.
3. Show the progress panel moving through analysis, generation, dependency installation, and build. The first run installs from the npm registry, so allow time; a rebuild reuses the cached `node_modules`.
4. Show the generated project files under `generated/projects/{id}` to demonstrate it is real frontend code, not an iframe.
5. Use a mobile browser width to demonstrate the responsive dashboard and the generated CSS breakpoint.
6. Submit “Make the navbar sticky” or “Change the primary color to blue” and show the revalidation status.
7. To show self-repair, break a generated file — write `title.length` where `title` is optional in `components/Section.tsx` — and revalidate. The dashboard shows a `SELF-REPAIR` panel with the diagnostic, the proposed change, and the rebuild; the build then passes and the project returns to `READY`.
8. To show the limit is real, revalidate with `?run_repair=false`, or make a break the model cannot fix. After three attempts the project lands in `FAILED` with the original compiler output — repair never downgrades what `READY` means.
9. To show the patch is validated as data, ask for a change that would escape the project: a `../` path, a `.env` edit, or replacement text containing `child_process`. It is refused, the file is untouched, and the attempt is recorded.
