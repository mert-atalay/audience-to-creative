"""Stage 6: experiment memory. An append-only JSONL log of briefs, variants, reviews and results."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .storage import Storage

KEY = "memory.jsonl"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Memory:
    def __init__(self, store: Storage):
        self.store = store

    def events(self, kind: str | None = None) -> list[dict]:
        if not self.store.exists(KEY):
            return []
        rows = [json.loads(line) for line in self.store.read_text(KEY).splitlines() if line.strip()]
        return [r for r in rows if kind is None or r["type"] == kind]

    def append(self, kind: str, at: str | None = None, **fields) -> dict:
        """Add one event. Events are never edited or removed."""
        event = {"id": f"mem-{len(self.events()) + 1:04d}", "type": kind, "at": at or now(), **fields}
        self.store.append_line(KEY, json.dumps(event, ensure_ascii=False))
        return event

    def next_run(self) -> int:
        return len(self.events("run")) + 1

    def decisions(self) -> dict[str, dict]:
        """Latest human review event per variant."""
        return {e["variant_id"]: e for e in self.events("review")}

    def rejected_headlines(self) -> dict[tuple, str]:
        """(segment, angle, lowercased headline) -> reviewer note, for variants a person rejected."""
        variants = {e["variant_id"]: e for e in self.events("variant")}
        return {(variants[vid]["segment"], variants[vid]["angle"], variants[vid]["headline"].lower()): d["note"]
                for vid, d in self.decisions().items() if d["decision"] == "rejected"}

    def import_results(self, rows: list[dict], at: str | None = None) -> tuple[list[dict], list[dict]]:
        """Record results for approved variants only. Returns (imported events, skipped rows with a reason)."""
        variants = {e["variant_id"]: e for e in self.events("variant")}
        decisions = self.decisions()
        done = {e["variant_id"] for e in self.events("result")}
        imported, skipped = [], []
        for row in rows:
            vid = row["variant_id"]
            if vid not in variants:
                skipped.append({**row, "reason": "unknown variant"})
            elif decisions.get(vid, {}).get("decision") != "approved":
                skipped.append({**row, "reason": "variant was not approved"})
            elif vid in done:
                skipped.append({**row, "reason": "results already imported"})
            else:
                v = variants[vid]
                keys = {k: v[k] for k in ("variant_id", "brief_id", "segment", "angle", "format", "hook_type")}
                metrics = {k: row[k] for k in ("impressions", "clicks", "leads", "spend", "weeks_running")}
                imported.append(self.append("result", at=at, **keys, **metrics))
                done.add(vid)
        return imported, skipped
