from __future__ import annotations

import json
import re
from pathlib import Path

from ..models.schemas import WebsiteSpec
from ..storage import project_dir

NEXT_VERSION = "14.2.5"
REACT_VERSION = "18.3.1"
# Pinned to match apps/web so the dashboard and generated apps share one toolchain.
PACKAGE_MANAGER = "pnpm@10.15.1"


class ProjectGenerator:
    def generate(self, project_id: str, spec: WebsiteSpec) -> Path:
        root = project_dir(project_id)
        (root / "app").mkdir(parents=True, exist_ok=True)
        (root / "components").mkdir(exist_ok=True)
        (root / "public").mkdir(exist_ok=True)
        (root / "package.json").write_text(json.dumps(self._package_json(project_id, spec), indent=2) + "\n", encoding="utf-8")
        (root / "tsconfig.json").write_text(json.dumps(self._tsconfig(), indent=2) + "\n", encoding="utf-8")
        (root / "next-env.d.ts").write_text("/// <reference types=\"next\" />\n/// <reference types=\"next/image-types/global\" />\n", encoding="utf-8")
        (root / ".gitignore").write_text("node_modules/\n.next/\nout/\n*.tsbuildinfo\nnext-env.d.ts\n", encoding="utf-8")
        (root / "next.config.mjs").write_text("/** @type {import('next').NextConfig} */\nconst nextConfig = {};\nexport default nextConfig;\n", encoding="utf-8")
        (root / "app/layout.tsx").write_text("import './styles.css';\nexport default function Layout({children}:{children:React.ReactNode}) { return <html lang='en'><body>{children}</body></html> }\n", encoding="utf-8")
        (root / "app/styles.css").write_text(self._css(spec), encoding="utf-8")
        (root / "components/Section.tsx").write_text("export function Section({title, text, image}:{title?:string;text?:string;image?:string}) { return <section className='section'><div><p className='eyebrow'>DISCOVER MORE</p>{title && <h2>{title}</h2>}<p>{text}</p><a className='button' href='#'>Explore →</a></div>{image && <img src={image} alt='' />}</section> }\n", encoding="utf-8")
        (root / "app/page.tsx").write_text(self._page(spec), encoding="utf-8")
        (root / "spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        return root

    def _package_json(self, project_id: str, spec: WebsiteSpec) -> dict:
        name = "generated-" + (re.sub(r"[^a-z0-9]+", "-", project_id.lower()).strip("-") or "app")
        return {
            "name": name,
            "version": "0.1.0",
            "private": True,
            "description": f"Reconstructed from {str(spec.url)}",
            "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
            "dependencies": {"next": NEXT_VERSION, "react": REACT_VERSION, "react-dom": REACT_VERSION},
            # next build type-checks .tsx sources; without these it aborts with
            # 'The "id" argument must be of type string. Received undefined'.
            "devDependencies": {
                "@types/node": "^20",
                "@types/react": "^18",
                "@types/react-dom": "^18",
                "typescript": "^5",
            },
            "packageManager": PACKAGE_MANAGER,
        }

    def _tsconfig(self) -> dict:
        return {
            "compilerOptions": {
                "target": "ES2020",
                "lib": ["dom", "dom.iterable", "esnext"],
                "allowJs": True,
                "skipLibCheck": True,
                "strict": True,
                "noEmit": True,
                "esModuleInterop": True,
                "module": "esnext",
                "moduleResolution": "bundler",
                "resolveJsonModule": True,
                "isolatedModules": True,
                "jsx": "preserve",
                "incremental": True,
                "plugins": [{"name": "next"}],
            },
            "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
            "exclude": ["node_modules"],
        }

    def _page(self, spec: WebsiteSpec) -> str:
        nav = "".join(f"<a href='{n.href}'>{n.label}</a>" for n in spec.navigation[:6]) or "<a href='#'>Explore</a>"
        sections = "".join(f"<Section title={{{json.dumps(s.heading or s.name.title())}}} text={{{json.dumps(s.text)}}} />" for s in spec.sections[:8])
        hero = spec.headings[0] if spec.headings else spec.title
        intro = spec.paragraphs[0] if spec.paragraphs else spec.meta_description or "A thoughtful digital experience, reconstructed from the visual language of the source site."
        return "import { Section } from '../components/Section';\n\nexport default function Page() { return <main><nav><strong>{" + json.dumps(spec.title[:32]) + "}</strong><div>" + nav + "</div></nav><header className='hero'><p className='eyebrow'>REPLIUI RECONSTRUCTION</p><h1>" + hero.replace("'", "&#39;") + "</h1><p>" + intro.replace("'", "&#39;") + "</p><a className='button' href='#content'>Start exploring →</a></header><div id='content'>" + sections + "</div><footer><strong>" + spec.title[:32].replace("'", "&#39;") + "</strong><span>Independently generated frontend</span></footer></main> }\n"

    def _css(self, spec: WebsiteSpec) -> str:
        accent = spec.theme[0].value if spec.theme else "#d97757"
        return f"*{{box-sizing:border-box}}:root{{--accent:{accent};--ink:#17231f;--muted:#61706a;--paper:#f5f7f1}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,Arial,sans-serif}}main{{max-width:1180px;margin:auto;padding:0 28px}}nav{{height:82px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #dfe5dc}}nav div{{display:flex;gap:24px}}a{{color:inherit;text-decoration:none}}.hero{{padding:112px 0 130px;max-width:900px}}.eyebrow{{font-size:11px;letter-spacing:.16em;color:var(--accent);font-weight:700}}h1{{font-size:clamp(3.4rem,8vw,7.8rem);line-height:.94;letter-spacing:-.07em;margin:20px 0 30px;max-width:900px}}h2{{font-size:clamp(2rem,4vw,4.5rem);line-height:1;letter-spacing:-.05em;margin:10px 0 22px}}p{{font-size:18px;line-height:1.65;color:var(--muted);max-width:620px}}.button{{display:inline-flex;padding:14px 20px;background:var(--ink);color:white;border-radius:999px;margin-top:18px;font-weight:700}}.section{{border-top:1px solid #dfe5dc;padding:76px 0;display:grid;grid-template-columns:1fr 1fr;gap:40px;min-height:260px}}.section img{{width:100%;border-radius:18px;object-fit:cover}}footer{{padding:50px 0;display:flex;justify-content:space-between;color:var(--muted);border-top:1px solid #dfe5dc}}@media(max-width:700px){{main{{padding:0 18px}}nav div{{display:none}}.hero{{padding:80px 0}}.section{{grid-template-columns:1fr;padding:54px 0}}footer{{display:block}}footer span{{display:block;margin-top:12px}}}}"
