"""Unit tests for build diagnostic parsing and categorization."""

from __future__ import annotations

from app.repair.diagnostics import (
    CONFIG_ERROR,
    DEPENDENCY_ERROR,
    IMPORT_ERROR,
    JSX_ERROR,
    MODULE_NOT_FOUND,
    TYPESCRIPT_ERROR,
    UNKNOWN_BUILD_ERROR,
    BuildDiagnostic,
    categorize,
    parse_diagnostics,
)


def _parse(text: str) -> list[BuildDiagnostic]:
    return parse_diagnostics("build", "npm run build", text, "")


# --- extraction ---------------------------------------------------------


def test_extracts_nextjs_header_location_and_message():
    out = "./app/page.tsx:12:5\nType error: Property 'foo' does not exist on type 'Props'.\n"
    (diag,) = _parse(out)
    assert diag.file == "./app/page.tsx"
    assert diag.line == 12
    assert diag.column == 5
    assert diag.category == TYPESCRIPT_ERROR
    # The location line is folded in, not emitted as a separate diagnostic.
    assert "Property 'foo'" in diag.message


def test_extracts_inline_tsc_error_location():
    out = "app/page.tsx:10:5: error TS2322: Type 'string' is not assignable to type 'number'."
    (diag,) = _parse(out)
    assert diag.file == "app/page.tsx"
    assert diag.line == 10
    assert diag.category == TYPESCRIPT_ERROR


def test_extracts_parenthesised_location():
    (diag,) = _parse("(components/Hero.tsx:20:1) Something went wrong")
    assert diag.file == "components/Hero.tsx"
    assert diag.line == 20
    assert diag.column == 1


def test_bracket_ordinal_is_not_mistaken_for_a_file():
    # A code frame line like "12 |  const x" must not produce file="12".
    (diag,) = _parse("Type error: Property 'foo' does not exist on type 'Props'.")
    assert diag.file is None
    assert diag.category == TYPESCRIPT_ERROR


def test_quoted_property_name_is_not_mistaken_for_a_file():
    # Regression: a bare quoted-token pattern reported file="foo".
    (diag,) = _parse("Type error: Property 'foo' does not exist on type 'Props'.")
    assert diag.file is None


def test_extracts_module_specifier_as_file():
    (diag,) = _parse("Error: Cannot find module '@/components/Missing'")
    assert diag.file == "@/components/Missing"
    assert diag.category == MODULE_NOT_FOUND


def test_extracts_double_quoted_specifier():
    (diag,) = _parse('Error: Failed to resolve import "./nope" from "./app/page.tsx"')
    assert diag.file == "./nope"
    assert diag.category == MODULE_NOT_FOUND


def test_distinct_errors_in_one_file_are_separate_diagnostics():
    out = (
        "./app/page.tsx:1:1\nType error: Property 'a' does not exist on type 'Props'.\n"
        "./app/page.tsx:9:1\nType error: Type 'string' is not assignable to type 'number'.\n"
    )
    diags = _parse(out)
    assert len(diags) == 2
    assert {d.line for d in diags} == {1, 9}


# --- categorization -----------------------------------------------------


def test_categorize_module_not_found():
    assert categorize("Cannot find module 'x'") == MODULE_NOT_FOUND
    assert categorize("Module not found: Error: Can't resolve './a'") == MODULE_NOT_FOUND
    assert categorize("Failed to resolve import './a'") == MODULE_NOT_FOUND


def test_categorize_typescript():
    assert categorize("Type error: foo") == TYPESCRIPT_ERROR
    assert categorize("Cannot find name 'render'") == TYPESCRIPT_ERROR
    assert categorize("Type 'A' is not assignable to type 'B'") == TYPESCRIPT_ERROR


def test_categorize_jsx():
    assert categorize("Expected corresponding JSX closing tag") == JSX_ERROR
    assert categorize("Expected ';', '}' or < to JSX contents") == JSX_ERROR


def test_categorize_import():
    assert categorize("No default export is a member of module 'X'") == IMPORT_ERROR


def test_categorize_config_and_dependency():
    assert categorize("Invalid next.config.js options") == CONFIG_ERROR
    assert categorize("tsconfig.json is malformed") == CONFIG_ERROR
    assert categorize("unmet peer dependency react@18") == DEPENDENCY_ERROR


def test_categorize_unknown_falls_back():
    assert categorize("something entirely unexpected") == UNKNOWN_BUILD_ERROR


# --- noise filtering and fallback --------------------------------------


def test_build_banner_is_not_a_diagnostic():
    out = "> next build\n\n\u2714 Compiled successfully\n"
    (diag,) = _parse(out)
    # Everything was noise, so the fallback keeps the failure visible.
    assert diag.message
    assert "> next build" not in diag.message


def test_noise_does_not_swallow_real_errors():
    out = "> next build\nType error: Property 'a' does not exist on type 'P'.\n"
    diags = _parse(out)
    assert len(diags) == 1
    assert diags[0].category == TYPESCRIPT_ERROR


def test_empty_output_still_yields_one_diagnostic():
    (diag,) = parse_diagnostics("build", "npm run build", "", "")
    assert diag.category == UNKNOWN_BUILD_ERROR
    assert diag.message == "Build failed"


def test_raw_output_is_preserved():
    out = "./app/page.tsx:1:1\nType error: bad\n"
    (diag,) = _parse(out)
    assert "./app/page.tsx:1:1" in diag.raw_output
    assert "Type error: bad" in diag.raw_output


def test_stage_and_command_are_recorded():
    (diag,) = parse_diagnostics("install", "pnpm install", "", "boom")
    assert diag.stage == "install"
    assert diag.command == "pnpm install"


def test_install_stage_is_not_reported_as_build():
    (diag,) = parse_diagnostics("install", "pnpm install", "", "ERR_PNPM_OUTDATED_LOCKFILE")
    assert diag.stage == "install"


# --- real next build output -------------------------------------------

# Captured verbatim from `next build` on a generated project whose
# components/Section.tsx dereferenced an optional prop. The frame lines carry
# ANSI colour codes; without stripping them the model is handed escape
# sequences and the file patterns cannot match.
REAL_BUILD_OUTPUT = (
    "  ▲ Next.js 14.2.0\n"
    "\n"
    "   - Creating an optimized production build ...\n"
    " ⚠ No build cache found. Please configure build caching for faster rebuilds.\n"
    "Failed to compile.\n"
    "\n"
    "./components/Section.tsx:1:174\n"
    "Type error: 'title' is possibly 'undefined'.\n"
    "\x1b[0m\x1b[31m\x1b[1m>\x1b[22m\x1b[39m\x1b[90m 1 |\x1b[39m "
    "\x1b[36mexport\x1b[39m function Section({title}: {title?: string}) { ... }\x1b[0m\n"
    "\x1b[0m \x1b[90m   |\x1b[39m      \x1b[31m\x1b[1m^\x1b[22m\x1b[0m\n"
    "\x1b[0m \x1b[90m 2 |\x1b[39m\n"
    "\n"
    "Attention: Next.js now collects completely anonymous telemetry.\n"
    "https://nextjs.org/telemetry\n"
)


def test_real_build_output_yields_only_the_real_error():
    diags = parse_diagnostics("build", "pnpm run build", "", REAL_BUILD_OUTPUT)
    assert len(diags) == 1
    assert diags[0].category == TYPESCRIPT_ERROR
    assert diags[0].file == "./components/Section.tsx"
    assert diags[0].line == 1
    assert "possibly 'undefined'" in diags[0].message


def test_ansi_codes_are_stripped_from_messages():
    diags = parse_diagnostics("build", "", "", REAL_BUILD_OUTPUT)
    assert all("\x1b" not in d.message for d in diags)
    assert all("\x1b" not in d.raw_output for d in diags)


def test_code_frames_are_not_separate_diagnostics():
    diags = parse_diagnostics("build", "", "", REAL_BUILD_OUTPUT)
    assert not any("|" in d.message for d in diags)


def test_telemetry_notices_are_not_diagnostics():
    diags = parse_diagnostics("build", "", "", REAL_BUILD_OUTPUT)
    assert not any("telemetry" in d.message.lower() for d in diags)
    assert not any("build cache" in d.message.lower() for d in diags)
