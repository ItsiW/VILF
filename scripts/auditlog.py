"""
AUDIT_LOG.md: a tracked, append-only record of when the review data was last
checked against Google, so the next person can tell whether a re-audit is due.

`./vilf audit` and `./vilf check --fix` append one line each; `audit` also
prints when the last audit happened.
"""

import re
from datetime import date
from pathlib import Path

FILENAME = "AUDIT_LOG.md"
HEADER = (
    "# Audit log\n\n"
    "Appended automatically by `./vilf audit` and `./vilf check --fix` (newest last).\n"
    "Use the last `audit` line to decide when the reviews are due another pass.\n\n"
)
_LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) (.+?): ")


def path_for(places_dir) -> Path:
    """The log lives next to places/, i.e. at the repo root."""
    return Path(places_dir).resolve().parent / FILENAME


def append(places_dir, kind: str, summary: str, today: date | None = None) -> Path:
    """Append `- <date> <kind>: <summary>` and return the log path."""
    log = path_for(places_dir)
    if not log.exists():
        log.write_text(HEADER, encoding="utf-8")
    day = (today or date.today()).isoformat()
    with log.open("a", encoding="utf-8") as f:
        f.write(f"- {day} {kind}: {summary}\n")
    return log


def last(places_dir, kind: str) -> date | None:
    """Date of the most recent `kind` entry, or None."""
    log = path_for(places_dir)
    if not log.exists():
        return None
    found = None
    for line in log.read_text(encoding="utf-8").splitlines():
        m = _LINE.match(line)
        if m and m.group(2) == kind:
            found = date.fromisoformat(m.group(1))
    return found
