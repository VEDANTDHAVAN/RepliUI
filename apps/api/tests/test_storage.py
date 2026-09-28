"""Persistence of analyses, plans and screenshots.

The path-traversal guard is the point of most of these: a project id must never
be able to read or write outside its own directory.
"""

from __future__ import annotations

import json

import pytest

from app import storage
from app.models.schemas import (
    AssetSpec,
    ColorSpec,
    GenerationPlan,
    NavigationSpec,
    SectionSpec,
    ThemeSpec,
    WebsiteSpec,
)


@pytest.fixture()
def analysis_project():
    return "testproj0001"


def _spec(url="https://example.com"):
    return WebsiteSpec(
        url=url,
        title="Example",
        meta_description="An example",
        navigation=[NavigationSpec(label="Docs", href="/docs")],
        sections=[SectionSpec(name="main", tag="main", heading="Hello", order=0)],
        assets=[AssetSpec(source_url=f"{url}/logo.svg", kind="svg")],
        theme=[ColorSpec(name="background", value="#ffffff", usage="background")],
        theme_tokens=ThemeSpec(primary="#0f172a", background="#ffffff", text="#0f172a"),
    )


def test_website_spec_round_trips_through_disk(analysis_project):
    spec = _spec()
    path = storage.save_website_spec(analysis_project, spec)

    assert path.name == "website-spec.json"
    assert path.parent == storage.analysis_dir(analysis_project)

    reloaded = storage.load_website_spec(analysis_project)
    assert reloaded.title == spec.title
    assert reloaded.sections[0].heading == "Hello"
    assert reloaded.assets[0].kind == "svg"


def test_persisted_spec_is_readable_json(analysis_project):
    path = storage.save_website_spec(analysis_project, _spec())
    payload = json.loads(path.read_text(encoding="utf-8"))
    # `url` is a Pydantic HttpUrl, so the bare host is normalised with a "/".
    assert payload["url"].rstrip("/") == "https://example.com"
    assert isinstance(payload["sections"], list)
    assert payload["theme_tokens"]["background"] == "#ffffff"


def test_generation_plan_round_trips_through_disk(analysis_project):
    plan = GenerationPlan(
        framework="next",
        project_structure=["app/", "components/"],
        section_order=[0, 1],
        source="fallback",
    )
    path = storage.save_generation_plan(analysis_project, plan)

    assert path.name == "generation-plan.json"
    reloaded = storage.load_generation_plan(analysis_project)
    assert reloaded.framework == "next"
    assert reloaded.project_structure == ["app/", "components/"]
    assert reloaded.section_order == [0, 1]


def test_spec_and_plan_live_in_the_same_project_directory(analysis_project):
    spec_path = storage.save_website_spec(analysis_project, _spec())
    plan_path = storage.save_generation_plan(analysis_project, GenerationPlan())
    assert spec_path.parent == plan_path.parent


def test_screenshots_are_isolated_per_project():
    first = storage.screenshot_path("projectaaaa", "desktop")
    second = storage.screenshot_path("projectbbbb", "desktop")
    assert first != second
    assert first.parent != second.parent
    assert first.name == "desktop.png"


def test_screenshot_labels_are_confined_to_the_project_directory():
    # A hostile label is sanitised rather than rejected, and must never resolve
    # outside the project's own screenshot directory.
    for label in ("../../escape", "..", "/etc/passwd", "a/b"):
        path = storage.screenshot_path("projectaaaa", label)
        assert path.parent == storage.screenshot_dir("projectaaaa").resolve()
        assert ".." not in path.name


@pytest.mark.parametrize("bad_id", ["..", ".", "a/b", "", "../secrets"])
def test_project_ids_cannot_escape_storage(bad_id):
    with pytest.raises(ValueError):
        storage.analysis_dir(bad_id)
    with pytest.raises(ValueError):
        storage.screenshot_dir(bad_id)


def test_writing_one_project_does_not_touch_another(analysis_project):
    other = "testproj0002"
    storage.save_website_spec(analysis_project, _spec("https://one.example"))
    storage.save_website_spec(other, _spec("https://two.example"))

    assert str(storage.load_website_spec(analysis_project).url).rstrip("/") == "https://one.example"
    assert str(storage.load_website_spec(other).url).rstrip("/") == "https://two.example"
