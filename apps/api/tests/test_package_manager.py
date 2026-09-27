"""Unit tests for package manager detection and the command allowlist."""

from __future__ import annotations

import json

import pytest

from app.validators import package_manager as pm


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


class TestAllowlist:
    def test_only_known_managers_are_allowed(self):
        assert set(pm.allowed_commands()) == {"pnpm", "npm", "yarn"}

    @pytest.mark.parametrize(
        "argv",
        [
            ("pnpm", "exec", "sh"),
            ("pnpm", "dlx", "evil"),
            ("npm", "run", "dev"),
            ("pnpm", "install", "extra-arg"),
            ("npx", "anything"),
        ],
    )
    def test_non_allowlisted_argv_is_rejected(self, argv):
        with pytest.raises(pm.CommandNotAllowed):
            pm.assert_allowed(argv[0], argv)

    def test_allowlisted_argv_passes(self):
        pm.assert_allowed("pnpm", ("pnpm", "build"))
        pm.assert_allowed("npm", ("npm", "install"))

    def test_building_command_for_unknown_manager_raises(self):
        with pytest.raises(pm.CommandNotAllowed):
            pm.build_command("bun")

    def test_select_rejects_unknown_manager(self):
        with pytest.raises(pm.CommandNotAllowed):
            pm.select("bun")


class TestDetection:
    def test_prefers_declared_package_manager(self, tmp_path):
        _write(tmp_path / "package.json", {"packageManager": "pnpm@10.15.1"})
        assert pm.detect(tmp_path) == "pnpm"

    def test_lockfile_overrides_package_json_field(self, tmp_path):
        _write(tmp_path / "package.json", {"packageManager": "npm@10"})
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        assert pm.detect(tmp_path) == "pnpm"

    def test_explicit_preference_wins(self, tmp_path):
        _write(tmp_path / "package.json", {"packageManager": "npm@10"})
        (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
        assert pm.detect(tmp_path, prefer="pnpm") == "pnpm"

    def test_uninstalled_preference_is_skipped(self, tmp_path):
        """A preference for a manager that is not on PATH falls through rather
        than being selected, so validation never launches a missing binary."""
        import shutil

        absent = next((m for m in pm.allowed_commands() if shutil.which(m) is None), None)
        if absent is None:
            pytest.skip("every allowlisted manager is installed")
        _write(tmp_path / "package.json", {"packageManager": absent})
        detected = pm.detect(tmp_path, prefer=absent)
        assert detected != absent
        assert shutil.which(detected) is not None

    def test_falls_back_to_preferred_manager(self, tmp_path):
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        assert pm.detect(tmp_path) in pm.allowed_commands()

    def test_ignores_unparsable_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text("{not json", encoding="utf-8")
        assert pm.detect(tmp_path) in pm.allowed_commands()


class TestCommandConstruction:
    def test_pnpm_install_ignores_the_parent_workspace(self, tmp_path):
        """Regression: the generated project lives inside the RepliUI pnpm
        workspace, so a bare `pnpm install` installs the root workspace instead
        and leaves the generated project without node_modules."""
        command = pm.install_command("pnpm")
        assert "--ignore-workspace" in command.argv

    def test_pnpm_install_does_not_require_a_fresh_lockfile(self):
        """Validation sets CI=1, which makes pnpm default to --frozen-lockfile;
        a regenerated project's stale lockfile must not fail the install."""
        assert "--no-frozen-lockfile" in pm.install_command("pnpm").argv

    def test_pnpm_build_has_no_extra_flags(self):
        assert pm.build_command("pnpm").argv == ("pnpm", "build")

    def test_commands_carry_a_resolved_executable(self):
        command = pm.build_command("pnpm")
        assert command.executable
        assert command.display() == "pnpm build"
