import os
import sys
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetcher
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


class TestEntrySummary:
    def test_extracts_and_cleans_html_summary(self):
        entry = FakeEntry(title="标题", link="https://example.com")
        entry.summary = "<p>第一段&nbsp;<b>重点</b></p><p>第二段</p>"

        result = fetcher._entry_summary(entry)

        assert result == "第一段 重点 第二段"

    def test_falls_back_to_content_value(self):
        entry = FakeEntry(title="标题", link="https://example.com")
        entry.content = [{"value": "<div>正文内容</div>"}]

        assert fetcher._entry_summary(entry) == "正文内容"


class TestFetchNews:
    def test_falls_back_when_first_feed_has_no_entries_and_includes_summary(self, monkeypatch):
        now = datetime.now(timezone.utc)
        accepted_entry = FakeEntry(
            published_parsed=now.timetuple(),
            title="重要新闻",
            link="https://example.com/news",
        )
        accepted_entry.summary = "<p>这是一条有上下文的摘要。</p>"
        calls = []

        class FakeResponse:
            def __init__(self, content):
                self.content = content

            def raise_for_status(self):
                return None

        def fake_get(url, **kwargs):
            calls.append(url)
            return FakeResponse(url.encode("utf-8"))

        def fake_parse(content):
            if content == b"https://bad.example/rss":
                return SimpleNamespace(entries=[], bozo=False)
            return SimpleNamespace(entries=[accepted_entry], bozo=False)

        monkeypatch.setattr(fetcher, "RSS_SOURCES", [{
            "name": "测试源",
            "urls": ["https://bad.example/rss", "https://good.example/rss"],
        }])
        monkeypatch.setattr(fetcher, "MAX_ENTRIES", 10)
        monkeypatch.setattr(fetcher.requests, "get", fake_get)
        monkeypatch.setattr(fetcher.feedparser, "parse", fake_parse)

        result = fetcher.fetch_news()

        assert calls == ["https://bad.example/rss", "https://good.example/rss"]
        assert result == [{
            "title": "重要新闻",
            "link": "https://example.com/news",
            "source": "测试源",
            "published": datetime(*now.timetuple()[:6], tzinfo=timezone.utc).isoformat(),
            "summary": "这是一条有上下文的摘要。",
        }]

    def test_all_empty_feeds_are_logged_as_source_failure(self, monkeypatch, caplog):
        class FakeResponse:
            content = b"not a feed"

            def raise_for_status(self):
                return None

        monkeypatch.setattr(fetcher, "RSS_SOURCES", [{
            "name": "空源",
            "urls": ["https://empty.example/rss"],
        }])
        monkeypatch.setattr(fetcher.requests, "get", lambda *args, **kwargs: FakeResponse())
        monkeypatch.setattr(fetcher.feedparser, "parse", lambda content: SimpleNamespace(entries=[], bozo=False))

        result = fetcher.fetch_news()

        assert result == []
        assert "Failed to fetch 空源" in caplog.text
