"""Snapshot format: a JSON list of place rows (see tests/fixtures/snapshot.json)."""

import json
from typing import NamedTuple

TIMESTAMPS = ("created_at", "updated_at", "published_at")


def dump_rows(rows: list[dict]) -> str:
    return json.dumps(sorted(rows, key=lambda r: r["slug"]), indent=1, ensure_ascii=False) + "\n"


def load_rows(text: str) -> list[dict]:
    rows = json.loads(text)
    if not isinstance(rows, list):
        raise ValueError("snapshot must be a JSON list of rows")
    return rows


class Diff(NamedTuple):
    added: list[str]
    removed: list[str]
    changed: dict[str, dict[str, tuple]]  # slug -> key -> (old, new)

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.changed)


def diff_rows(old_rows: list[dict], new_rows: list[dict]) -> Diff:
    """Compare every key except the timestamps; body differences appear under 'body'."""
    old = {r["slug"]: r for r in old_rows}
    new = {r["slug"]: r for r in new_rows}
    changed = {}
    for slug in sorted(old.keys() & new.keys()):
        # Google-link preferences do not change the published restaurant page.
        keys = (old[slug].keys() | new[slug].keys()) - set(TIMESTAMPS) - {"unlinked"}
        delta = {k: (old[slug].get(k), new[slug].get(k)) for k in sorted(keys) if old[slug].get(k) != new[slug].get(k)}
        if delta:
            changed[slug] = delta
    return Diff(sorted(new.keys() - old.keys()), sorted(old.keys() - new.keys()), changed)
