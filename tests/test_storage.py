import importlib.util

import pytest

from pipeline import run
from pipeline.storage import GCSStorage, LocalStorage, StorageUnavailable, open_store

from conftest import quiet


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name = bucket, name

    def upload_from_string(self, data, content_type=None):
        self.bucket.objects[self.name] = (data, content_type)

    def download_as_text(self):
        return self.bucket.objects[self.name][0]

    def exists(self):
        return self.name in self.bucket.objects

    def delete(self):
        del self.bucket.objects[self.name]


class FakeBucket:
    def __init__(self):
        self.objects = {}

    def blob(self, name):
        return FakeBlob(self, name)


class FakeGCSClient:
    """In-memory stand-in for google.cloud.storage.Client with the few calls the backend uses."""

    def __init__(self):
        self.buckets = {}

    def bucket(self, name):
        return self.buckets.setdefault(name, FakeBucket())

    def list_blobs(self, bucket_name, prefix=""):
        bucket = self.bucket(bucket_name)
        return [FakeBlob(bucket, n) for n in sorted(bucket.objects) if n.startswith(prefix)]


def roundtrip(store):
    store.write_text("a/b.txt", "hello")
    store.write_json("data.json", {"ids": ["x", "y"], "n": 1})
    store.append_line("log.jsonl", '{"n": 1}')
    store.append_line("log.jsonl", '{"n": 2}')
    assert store.read_text("a/b.txt") == "hello" and store.read_json("data.json") == {"ids": ["x", "y"], "n": 1}
    assert store.read_text("log.jsonl") == '{"n": 1}\n{"n": 2}\n'
    assert store.exists("a/b.txt") and not store.exists("missing.txt")
    assert store.list() == ["a/b.txt", "data.json", "log.jsonl"] and store.list("a/") == ["a/b.txt"]
    store.delete("a/b.txt")
    assert not store.exists("a/b.txt")
    store.clear()
    assert store.list() == []


def test_local_backend(tmp_path):
    roundtrip(LocalStorage(tmp_path / "store"))
    assert isinstance(open_store(str(tmp_path), "b2c"), LocalStorage)


def test_gcs_backend_with_fake_client():
    client = FakeGCSClient()
    store = open_store("gs://my-bucket/some/prefix", "b2c", client=client)
    assert isinstance(store, GCSStorage)
    store.write_text("gallery.html", "<p>hi</p>", "text/html")
    assert client.buckets["my-bucket"].objects == {"some/prefix/b2c/gallery.html": ("<p>hi</p>", "text/html")}
    store.clear()
    roundtrip(store)
    roundtrip(GCSStorage("gs://bucket-only", client=client))
    with pytest.raises(ValueError):
        GCSStorage("s3://nope", client=client)


def test_whole_pipeline_runs_on_the_gcs_backend():
    client = FakeGCSClient()
    store = open_store("gs://my-bucket/runs", "b2b", client=client)
    run.run_profile("b2b", store, at="2026-09-30T09:00:00Z", log=quiet)
    keys = store.list()
    assert {"sources.json", "audience.json", "briefs.json", "variants.json", "gallery.html", "memory.jsonl"} <= set(keys)
    assert any(k.startswith("creatives/") and k.endswith(".svg") for k in keys)
    assert all(name.startswith("runs/b2b/") for name in client.buckets["my-bucket"].objects)


def test_gcs_without_the_package_gives_a_clear_error():
    try:
        installed = importlib.util.find_spec("google.cloud.storage") is not None
    except ModuleNotFoundError:
        installed = False
    if installed:
        pytest.skip("google-cloud-storage is installed")
    with pytest.raises(StorageUnavailable, match="uv sync --extra gcs"):
        GCSStorage("gs://bucket/prefix")
