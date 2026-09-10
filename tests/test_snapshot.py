import json
from pathlib import Path

from scripts.snapshot import Diff, diff_rows, dump_rows, load_rows

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "snapshot.json").read_text())
SORTED = sorted(FIXTURE, key=lambda r: r["slug"])


def copy(rows):
    return [dict(r) for r in rows]


def test_round_trip():
    text = dump_rows(FIXTURE)
    assert load_rows(text) == SORTED
    assert text.endswith("]\n") and not text.endswith("\n\n")
    assert '\n {\n  "name"' in text  # indent=1


def test_non_ascii_kept():
    rows = [dict(FIXTURE[0], name="Café")]
    assert "Café" in dump_rows(rows)


def test_diff_identical():
    d = diff_rows(FIXTURE, FIXTURE)
    assert d == Diff([], [], {}) and not d


def test_diff_added_removed():
    d = diff_rows(FIXTURE, [r for r in FIXTURE if r["slug"] != "gone-place"])
    assert d.removed == ["gone-place"] and d.added == [] and d.changed == {}
    extra = dict(FIXTURE[0], slug="zzz")
    d = diff_rows(FIXTURE, FIXTURE + [extra])
    assert d.added == ["zzz"] and d.removed == []


def test_diff_changed_body_and_closed():
    new = copy(FIXTURE)
    tp = next(r for r in new if r["slug"] == "test-place")
    old_body = tp["body"]
    tp["body"] = "\nNew **dish**.\n"
    tp["closed"] = True
    d = diff_rows(FIXTURE, new)
    assert d.changed == {"test-place": {"body": (old_body, "\nNew **dish**.\n"), "closed": (False, True)}}
    assert bool(d)


def test_diff_ignores_timestamps():
    new = copy(FIXTURE)
    for r in new:
        r["created_at"] = "1999-01-01T00:00:00Z"
        r["updated_at"] = "2030-01-01T00:00:00Z"
        r["published_at"] = None
    assert diff_rows(FIXTURE, new) == Diff([], [], {})
