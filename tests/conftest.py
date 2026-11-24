import json

import pytest

from pipeline import run
from pipeline.config import PROFILES, load_profile
from pipeline.sources import load_sources
from pipeline.storage import LocalStorage

quiet = lambda *args, **kwargs: None


@pytest.fixture(scope="session")
def demo_dir(tmp_path_factory):
    """One full demo run (both profiles), shared by the tests that only read its output."""
    out = tmp_path_factory.mktemp("demo")
    run.demo(str(out), log=quiet)
    return out


@pytest.fixture(params=PROFILES)
def name(request):
    return request.param


@pytest.fixture
def profile(name):
    return load_profile(name)


@pytest.fixture
def sources(name):
    return load_sources(name)


@pytest.fixture
def store(tmp_path, name):
    """A fresh store with one pipeline run in it."""
    s = LocalStorage(tmp_path / name)
    run.run_profile(name, s, at="2026-09-30T09:00:00Z", log=quiet)
    return s


def read(demo_dir, name, key):
    return json.loads((demo_dir / name / key).read_text(encoding="utf-8"))
