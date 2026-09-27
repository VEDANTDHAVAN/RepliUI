"""The generator must emit a self-contained, installable Next.js project."""

from __future__ import annotations

import json

from app.generators import ProjectGenerator


class TestGeneratedProject:
    def test_generates_required_files(self, projects_dir, spec):
        root = ProjectGenerator().generate("genfiles0001", spec)
        for name in ("package.json", "tsconfig.json", "next.config.mjs", "app/layout.tsx", "app/page.tsx", "app/styles.css", "components/Section.tsx", "next-env.d.ts", ".gitignore"):
            assert (root / name).is_file(), f"missing {name}"

    def test_package_json_declares_typed_next_app(self, projects_dir, spec):
        root = ProjectGenerator().generate("genfiles0002", spec)
        manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
        assert manifest["scripts"]["build"] == "next build"
        assert manifest["scripts"]["dev"] == "next dev"
        assert {"next", "react", "react-dom"} <= set(manifest["dependencies"])
        assert manifest["name"].startswith("generated-")

    def test_typescript_dev_dependencies_present(self, projects_dir, spec):
        """next build type-checks .tsx; without these it crashes."""
        root = ProjectGenerator().generate("genfiles0003", spec)
        manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
        assert {"typescript", "@types/react", "@types/react-dom"} <= set(manifest["devDependencies"])

    def test_declares_package_manager(self, projects_dir, spec):
        root = ProjectGenerator().generate("genfiles0004", spec)
        manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
        assert manifest["packageManager"].startswith("pnpm@")

    def test_tsconfig_covers_generated_tsx(self, projects_dir, spec):
        root = ProjectGenerator().generate("genfiles0005", spec)
        tsconfig = json.loads((root / "tsconfig.json").read_text(encoding="utf-8"))
        assert tsconfig["compilerOptions"]["jsx"] == "preserve"
        assert "**/*.tsx" in tsconfig["include"]
        assert "node_modules" in tsconfig["exclude"]

    def test_generator_never_writes_node_modules(self, projects_dir, spec):
        root = ProjectGenerator().generate("genfiles0006", spec)
        assert not (root / "node_modules").exists()
