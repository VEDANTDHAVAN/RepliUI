# Agent pipeline

`WebsiteAnalyzer` uses Playwright and BeautifulSoup to collect title, metadata, headings, copy, navigation, forms, images, colors, sections, desktop/mobile screenshots, and responsive hints. `WebsiteSpec` is the compact, strongly typed boundary used by later stages. `AIGatewayProvider` uses the OpenAI-compatible AI Gateway endpoint with `AI_GATEWAY_API_KEY`; no provider key is hardcoded. `Planner` sends only the normalized spec and falls back deterministically when the gateway is unavailable.

The orchestrator states are `QUEUED`, `ANALYZING`, `ANALYZED`, `PLANNING`, `GENERATING`, `GENERATED`, `VALIDATING`, `READY`, `MODIFYING`, and `FAILED`. The generator creates reusable React output. The validator runs with a 120-second timeout and returns structured diagnostics. The modifier edits only files within the generated project and revalidates.
