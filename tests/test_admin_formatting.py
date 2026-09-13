from datetime import UTC, datetime

import pytest

from app.formatting import human_datetime


@pytest.mark.parametrize("value,expected", [
    ("2026-09-13T00:42:17Z", "Sep 12, 2026 at 5:42 PM PDT"),
    ("2026-01-13T00:42:17+00:00", "Jan 12, 2026 at 4:42 PM PST"),
    ("2026-09-12T07:00:00Z", "Sep 12, 2026 at 12:00 AM PDT"),
    ("2026-09-12T19:00:00Z", "Sep 12, 2026 at 12:00 PM PDT"),
    ("2026-03-08T09:59:00Z", "Mar 8, 2026 at 1:59 AM PST"),
    ("2026-03-08T10:00:00Z", "Mar 8, 2026 at 3:00 AM PDT"),
    (datetime(2026, 9, 13, 0, 42, tzinfo=UTC), "Sep 12, 2026 at 5:42 PM PDT"),
    (None, "—"), ("", "—"), ("invalid", "Unknown date"),
])
def test_human_datetime(value, expected):
    assert human_datetime(value) == expected
