from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from ..models.schemas import (AssetSpec, ColorSpec, ComponentSpec, NavigationSpec,
                              ResponsiveSpec, SectionSpec, TypographySpec, WebsiteSpec)
from ..storage import STORAGE_DIR


class WebsiteAnalyzer:
    def __init__(self, timeout_ms: int = 30000):
        self.timeout_ms = timeout_ms

    def analyze(self, url: str, project_id: str) -> WebsiteSpec:
        screenshot_dir = STORAGE_DIR / "screenshots" / project_id
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(700)
            page.screenshot(path=str(screenshot_dir / "desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(screenshot_dir / "mobile.png"), full_page=True)
            html, title = page.content(), page.title()
            description = page.locator('meta[name="description"]').get_attribute("content") or ""
            browser.close()
        soup = BeautifulSoup(html, "html.parser")
        clean = lambda node: " ".join(node.get_text(" ", strip=True).split())
        headings = [clean(n) for n in soup.select("h1,h2,h3") if clean(n)][:20]
        paragraphs = [clean(n) for n in soup.select("p") if clean(n)][:20]
        host = urlparse(url).netloc
        navigation = []
        for a in soup.select("nav a, header a")[:20]:
            label = clean(a)
            if label:
                href = urljoin(url, a.get("href", "#"))
                navigation.append(NavigationSpec(label=label[:80], href=href, is_external=urlparse(href).netloc not in {"", host}))
        buttons = [clean(n) for n in soup.select("button, [role=button], a.button") if clean(n)][:20]
        assets = []
        for image in soup.select("img[src], source[srcset]")[:30]:
            source = image.get("src") or image.get("srcset", "").split(",")[0].strip().split(" ")[0]
            if source:
                assets.append(AssetSpec(source_url=urljoin(url, source), alt=image.get("alt", "")))
        sections = []
        for index, node in enumerate(soup.select("main > section, body > section, main > div")[:12]):
            sections.append(SectionSpec(name=(node.get("id") or f"section-{index + 1}"), tag=node.name,
                                        heading=next((h for h in headings if h in clean(node)), None), text=clean(node)[:400]))
        if not sections:
            sections = [SectionSpec(name="main-content", tag="main", heading=headings[0] if headings else title, text=" ".join(paragraphs)[:400])]
        colors = self._colors(html)
        return WebsiteSpec(url=url, title=title or host, meta_description=description, theme=colors,
            typography=TypographySpec(families=["Inter", "Arial"], sizes=["16px", "clamp(2rem, 6vw, 5rem)"]), navigation=navigation,
            sections=sections, assets=assets, components=[ComponentSpec(name="Navigation", kind="navigation"), ComponentSpec(name="ContentSection", kind="section", count=len(sections))],
            responsive_rules=[ResponsiveSpec(breakpoint="768px", notes=["Collapse navigation", "Stack multi-column sections"])],
            screenshots=[str(screenshot_dir / "desktop.png"), str(screenshot_dir / "mobile.png")], headings=headings, paragraphs=paragraphs, buttons=buttons,
            forms=len(soup.select("form")), raw_metadata={"origin": host})

    def _colors(self, html: str) -> list[ColorSpec]:
        values = re.findall(r"#[0-9a-fA-F]{3,8}|rgb\([^)]*\)", html)
        counts = {value.lower(): values.count(value) for value in set(values)}
        return [ColorSpec(name="detected", value=value, usage="source style") for value, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]]
