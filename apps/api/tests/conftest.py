"""Pytest bootstrap.

``app.storage`` reads ``GENERATED_PROJECTS_DIR`` at import time, so the temp
directory has to be in place before any application module is imported.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# Must precede the first `app.*` import.
_TMP = Path(tempfile.mkdtemp(prefix="repliui-tests-"))
os.environ.setdefault("GENERATED_PROJECTS_DIR", str(_TMP / "projects"))
os.environ.setdefault("STORAGE_DIR", str(_TMP / "storage"))


@pytest.fixture()
def projects_dir() -> Path:
    from app import storage

    storage.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    return storage.PROJECTS_DIR


@pytest.fixture()
def spec():
    from app.models.schemas import NavigationSpec, SectionSpec, WebsiteSpec

    return WebsiteSpec(
        url="https://example.com",
        title="Example Domain",
        meta_description="An example site",
        headings=["Example Domain", "This domain is for use"],
        paragraphs=["This domain is for use in examples."],
        navigation=[NavigationSpec(label="More information", href="#")],
        sections=[SectionSpec(name="content", tag="main", heading="Details", text="Body copy.")],
    )
