"""Storage interface with a local-folder backend and a Google Cloud Storage backend."""
from __future__ import annotations

import json
from pathlib import Path

from .config import dumps


class StorageUnavailable(RuntimeError):
    pass


class Storage:
    """Keys are relative paths like 'briefs.json' or 'creatives/x.svg'."""

    def write_text(self, key: str, text: str, content_type: str = "text/plain") -> None:
        raise NotImplementedError

    def read_text(self, key: str) -> str:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def list(self, prefix: str = "") -> list[str]:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    # Helpers built on the five methods above.
    def write_json(self, key: str, obj) -> None:
        self.write_text(key, dumps(obj), "application/json")

    def read_json(self, key: str):
        return json.loads(self.read_text(key))

    def append_line(self, key: str, line: str) -> None:
        current = self.read_text(key) if self.exists(key) else ""
        self.write_text(key, current + line + "\n", "application/x-ndjson")

    def clear(self) -> None:
        for key in self.list():
            self.delete(key)


class LocalStorage(Storage):
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def write_text(self, key, text, content_type="text/plain"):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def read_text(self, key):
        return (self.root / key).read_text(encoding="utf-8")

    def exists(self, key):
        return (self.root / key).is_file()

    def list(self, prefix=""):
        if not self.root.is_dir():
            return []
        keys = (p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())
        return sorted(k for k in keys if k.startswith(prefix))

    def delete(self, key):
        (self.root / key).unlink(missing_ok=True)

    def __str__(self):
        return str(self.root)


class GCSStorage(Storage):
    """gs://bucket/prefix. Needs google-cloud-storage and Google credentials.

    Covered by tests with a fake client only. Not exercised against a real bucket.
    """

    def __init__(self, url: str, client=None):
        if not url.startswith("gs://"):
            raise ValueError("GCS url must look like gs://bucket/prefix")
        bucket, _, prefix = url[5:].partition("/")
        if client is None:
            try:
                from google.cloud import storage as gcs
            except ImportError as exc:
                raise StorageUnavailable(
                    "The GCS backend needs google-cloud-storage. Install it with: uv sync --extra gcs"
                ) from exc
            client = gcs.Client()
        self.url, self.client, self.bucket_name = url.rstrip("/"), client, bucket
        self.bucket = client.bucket(bucket)
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""

    def write_text(self, key, text, content_type="text/plain"):
        self.bucket.blob(self.prefix + key).upload_from_string(text, content_type=content_type)

    def read_text(self, key):
        return self.bucket.blob(self.prefix + key).download_as_text()

    def exists(self, key):
        return self.bucket.blob(self.prefix + key).exists()

    def list(self, prefix=""):
        blobs = self.client.list_blobs(self.bucket_name, prefix=self.prefix + prefix)
        return sorted(b.name[len(self.prefix):] for b in blobs)

    def delete(self, key):
        self.bucket.blob(self.prefix + key).delete()

    def __str__(self):
        return self.url


def open_store(location: str, profile: str, client=None) -> Storage:
    """A store for one profile under a local folder or a gs:// url."""
    if location.startswith("gs://"):
        return GCSStorage(f"{location.rstrip('/')}/{profile}", client=client)
    return LocalStorage(Path(location) / profile)
