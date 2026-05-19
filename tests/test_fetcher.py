import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fetcher import _parse_published


class FakeEntry:
    """Minimal feedparser entry mock."""
    def __init__(self, published_parsed=None, updated_parsed=None, title="", link=""):
        self.published_parsed = published_parsed
        self.updated_parsed = updated_parsed
        self.title = title
        self.link = link

    def get(self, key, default=None):
        return getattr(self, key, default)


class TestParsePublished:
    def test_published_parsed_returns_utc_datetime(self):
        entry = FakeEntry(published_parsed=(2026, 5, 19, 8, 0, 0, 0, 0, 0))
        result = _parse_published(entry)
        assert result == datetime(2026, 5, 19, 8, 0, 0, tzinfo=timezone.utc)

    def test_fallback_to_updated_parsed(self):
        entry = FakeEntry(
            published_parsed=None,
            updated_parsed=(2026, 5, 19, 9, 30, 0, 0, 0, 0),
        )
        result = _parse_published(entry)
        assert result == datetime(2026, 5, 19, 9, 30, 0, tzinfo=timezone.utc)

    def test_both_none_returns_none(self):
        entry = FakeEntry()
        assert _parse_published(entry) is None

    def test_published_parsed_takes_priority(self):
        entry = FakeEntry(
            published_parsed=(2026, 5, 19, 8, 0, 0, 0, 0, 0),
            updated_parsed=(2026, 5, 19, 10, 0, 0, 0, 0, 0),
        )
        result = _parse_published(entry)
        assert result == datetime(2026, 5, 19, 8, 0, 0, tzinfo=timezone.utc)
