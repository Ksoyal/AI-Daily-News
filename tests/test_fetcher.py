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


def _install_feed(monkeypatch, entries):
    """Point fetch_news at a single fake source whose feed yields the given entries."""
    class FakeResponse:
        content = b"feed"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(fetcher, "RSS_SOURCES", [{
        "name": "测试源",
        "urls": ["https://feed.example/rss"],
    }])
    monkeypatch.setattr(fetcher.requests, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(fetcher.feedparser, "parse",
                        lambda content: SimpleNamespace(entries=entries, bozo=False))


def _install_feeds(monkeypatch, sources):
    """Install several fake sources; sources is a list of (source_dict, entries) pairs."""
    class FakeResponse:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

    feed_map = {}
    for src, feed_entries in sources:
        for url in src["urls"]:
            feed_map[url.encode("utf-8")] = feed_entries

    monkeypatch.setattr(fetcher, "RSS_SOURCES", [src for src, _ in sources])
    monkeypatch.setattr(fetcher.requests, "get",
                        lambda url, **kwargs: FakeResponse(url.encode("utf-8")))
    monkeypatch.setattr(fetcher.feedparser, "parse",
                        lambda content: SimpleNamespace(entries=feed_map[content], bozo=False))


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


class TestFetchNewsFiltering:
    def test_entry_older_than_24h_is_dropped(self, monkeypatch):
        now = datetime.now(timezone.utc)
        fresh = FakeEntry(published_parsed=(now - timedelta(hours=1)).timetuple(),
                          title="新鲜新闻", link="https://example.com/fresh")
        stale = FakeEntry(published_parsed=(now - timedelta(hours=25)).timetuple(),
                          title="过期新闻", link="https://example.com/stale")
        _install_feed(monkeypatch, [stale, fresh])

        result = fetcher.fetch_news()

        assert [e["title"] for e in result] == ["新鲜新闻"]

    def test_title_with_exclude_keyword_is_dropped(self, monkeypatch):
        now = datetime.now(timezone.utc)
        kept = FakeEntry(published_parsed=now.timetuple(),
                         title="AI 芯片新进展", link="https://example.com/ai")
        excluded = FakeEntry(published_parsed=now.timetuple(),
                             title="娱乐圈大事件", link="https://example.com/gossip")
        _install_feed(monkeypatch, [excluded, kept])

        result = fetcher.fetch_news()

        assert [e["title"] for e in result] == ["AI 芯片新进展"]

    def test_max_entries_truncation_keeps_newest_first(self, monkeypatch):
        now = datetime.now(timezone.utc)
        entries = [
            FakeEntry(published_parsed=(now - timedelta(minutes=10 * i)).timetuple(),
                      title=f"新闻{i}", link=f"https://example.com/{i}")
            for i in range(5)
        ]
        # feed delivers oldest-first; fetch_news must re-sort newest-first
        _install_feed(monkeypatch, list(reversed(entries)))
        monkeypatch.setattr(fetcher, "MAX_ENTRIES", 2)

        result = fetcher.fetch_news()

        assert len(result) == 2
        assert [e["title"] for e in result] == ["新闻0", "新闻1"]
        assert result[0]["published"] > result[1]["published"]

    def test_entry_without_timestamp_is_dropped(self, monkeypatch):
        now = datetime.now(timezone.utc)
        dated = FakeEntry(published_parsed=now.timetuple(),
                          title="有时间戳", link="https://example.com/dated")
        undated = FakeEntry(title="无时间戳", link="https://example.com/undated")
        _install_feed(monkeypatch, [undated, dated])

        result = fetcher.fetch_news()

        assert [e["title"] for e in result] == ["有时间戳"]

    def test_new_noise_keywords_are_dropped(self, monkeypatch):
        now = datetime.now(timezone.utc)
        box_office = FakeEntry(published_parsed=now.timetuple(),
                               title="电影《八仙！》票房破十亿", link="https://example.com/movie")
        world_cup = FakeEntry(published_parsed=now.timetuple(),
                              title="世界杯旅游热潮席卷全球", link="https://example.com/cup")
        kept = FakeEntry(published_parsed=now.timetuple(),
                         title="央行宣布降准", link="https://example.com/econ")
        _install_feed(monkeypatch, [box_office, world_cup, kept])

        result = fetcher.fetch_news()

        assert [e["title"] for e in result] == ["央行宣布降准"]


class TestStaleFallback:
    def test_source_with_only_stale_entries_yields_capped_newest(self, monkeypatch):
        now = datetime.now(timezone.utc)
        # 5 entries, all ~30h old: outside 24h but inside the 72h stale window
        entries = [
            FakeEntry(published_parsed=(now - timedelta(hours=30, minutes=10 * i)).timetuple(),
                      title=f"旧闻{i}", link=f"https://example.com/{i}")
            for i in range(5)
        ]
        _install_feed(monkeypatch, list(reversed(entries)))

        result = fetcher.fetch_news()

        # capped at STALE_MAX_ENTRIES (3), newest first
        assert [e["title"] for e in result] == ["旧闻0", "旧闻1", "旧闻2"]

    def test_rescued_entries_survive_max_entries_truncation(self, monkeypatch):
        # Rescued stale entries are the oldest by definition; a plain
        # [:MAX_ENTRIES] recency cut would always drop them first.
        monkeypatch.setattr(fetcher, "MAX_ENTRIES", 3)
        now = datetime.now(timezone.utc)
        fresh = [
            FakeEntry(published_parsed=(now - timedelta(hours=1, minutes=i)).timetuple(),
                      title=f"新闻{i}电力市场改革方案第{i}批", link=f"https://a.example/{i}")
            for i in range(3)
        ]
        stale = FakeEntry(published_parsed=(now - timedelta(hours=40)).timetuple(),
                          title="周末长文：产业深度观察", link="https://b.example/old")
        _install_feeds(monkeypatch, [
            ({"name": "源A", "urls": ["https://a.example/rss"]}, fresh),
            ({"name": "源B", "urls": ["https://b.example/rss"]}, [stale]),
        ])

        result = fetcher.fetch_news()

        assert len(result) == 3
        assert any(e["source"] == "源B" for e in result)

    def test_fresh_entries_suppress_stale_fallback(self, monkeypatch):
        now = datetime.now(timezone.utc)
        fresh = FakeEntry(published_parsed=(now - timedelta(hours=1)).timetuple(),
                          title="新鲜新闻", link="https://example.com/fresh")
        stale = FakeEntry(published_parsed=(now - timedelta(hours=30)).timetuple(),
                          title="旧新闻", link="https://example.com/stale")
        _install_feed(monkeypatch, [stale, fresh])

        result = fetcher.fetch_news()

        assert [e["title"] for e in result] == ["新鲜新闻"]

    def test_entries_beyond_stale_window_are_dropped(self, monkeypatch):
        now = datetime.now(timezone.utc)
        ancient = FakeEntry(published_parsed=(now - timedelta(hours=80)).timetuple(),
                            title="远古新闻", link="https://example.com/ancient")
        _install_feed(monkeypatch, [ancient])

        result = fetcher.fetch_news()

        assert result == []


class TestCrossSourceDedup:
    def test_near_identical_titles_merge_keeping_longer_summary(self, monkeypatch):
        now = datetime.now(timezone.utc)
        short = FakeEntry(published_parsed=(now - timedelta(hours=1)).timetuple(),
                          title="OpenAI 发布 GPT-6 模型", link="https://a.example/1")
        short.summary = "简短摘要"
        long = FakeEntry(published_parsed=(now - timedelta(hours=2)).timetuple(),
                         title="OpenAI发布GPT-6模型！", link="https://b.example/1")
        long.summary = "这是一条更长更详细的摘要，包含背景与上下文信息。"
        _install_feeds(monkeypatch, [
            ({"name": "源A", "urls": ["https://a.example/rss"]}, [short]),
            ({"name": "源B", "urls": ["https://b.example/rss"]}, [long]),
        ])

        result = fetcher.fetch_news()

        assert len(result) == 1
        assert result[0]["source"] == "源B"
        assert result[0]["summary"] == "这是一条更长更详细的摘要，包含背景与上下文信息。"

    def test_tie_on_summary_length_keeps_earlier_source(self, monkeypatch):
        now = datetime.now(timezone.utc)
        first = FakeEntry(published_parsed=(now - timedelta(hours=2)).timetuple(),
                          title="苹果发布新款iPhone 17系列", link="https://a.example/1")
        first.summary = "摘要一样长"
        second = FakeEntry(published_parsed=(now - timedelta(hours=1)).timetuple(),
                           title="苹果发布新款 iPhone 17 系列！", link="https://b.example/1")
        second.summary = "摘要一样长"
        _install_feeds(monkeypatch, [
            ({"name": "源A", "urls": ["https://a.example/rss"]}, [first]),
            ({"name": "源B", "urls": ["https://b.example/rss"]}, [second]),
        ])

        result = fetcher.fetch_news()

        assert len(result) == 1
        assert result[0]["source"] == "源A"

    def test_much_fresher_entry_beats_longer_stale_summary(self, monkeypatch):
        now = datetime.now(timezone.utc)
        stale = FakeEntry(published_parsed=(now - timedelta(hours=60)).timetuple(),
                          title="半导体巨头宣布千亿投资计划", link="https://a.example/old")
        stale.summary = "非常" * 100 + "长的旧全文摘要"
        fresh = FakeEntry(published_parsed=(now - timedelta(hours=2)).timetuple(),
                          title="半导体巨头宣布千亿投资计划", link="https://b.example/new")
        fresh.summary = "短快讯"
        _install_feeds(monkeypatch, [
            ({"name": "源A", "urls": ["https://a.example/rss"]}, [stale]),
            ({"name": "源B", "urls": ["https://b.example/rss"]}, [fresh]),
        ])

        result = fetcher.fetch_news()

        assert len(result) == 1
        assert result[0]["source"] == "源B"
        assert result[0]["link"] == "https://b.example/new"

    def test_distinct_titles_are_not_merged(self, monkeypatch):
        now = datetime.now(timezone.utc)
        a = FakeEntry(published_parsed=(now - timedelta(hours=1)).timetuple(),
                      title="美联储宣布加息25个基点", link="https://a.example/1")
        b = FakeEntry(published_parsed=(now - timedelta(hours=2)).timetuple(),
                      title="日本央行维持利率不变", link="https://b.example/1")
        _install_feeds(monkeypatch, [
            ({"name": "源A", "urls": ["https://a.example/rss"]}, [a]),
            ({"name": "源B", "urls": ["https://b.example/rss"]}, [b]),
        ])

        result = fetcher.fetch_news()

        assert len(result) == 2

    def test_similar_phrasing_with_opposite_meaning_is_not_merged(self, monkeypatch):
        # Regression guard for the 0.5-threshold blocker: templated Chinese
        # headlines score high on phrasing alone (加息/降息 ≈ 0.69, 收涨/收跌 ≈ 0.80)
        now = datetime.now(timezone.utc)
        pairs = [
            ("美联储宣布加息25个基点", "美联储宣布降息25个基点"),
            ("美股三大指数集体收涨", "美股三大指数集体收跌"),
            ("北京多区发布高温红色预警", "上海多区发布高温红色预警"),
        ]
        for title_a, title_b in pairs:
            a = FakeEntry(published_parsed=(now - timedelta(hours=1)).timetuple(),
                          title=title_a, link="https://a.example/1")
            b = FakeEntry(published_parsed=(now - timedelta(hours=2)).timetuple(),
                          title=title_b, link="https://b.example/1")
            _install_feeds(monkeypatch, [
                ({"name": "源A", "urls": ["https://a.example/rss"]}, [a]),
                ({"name": "源B", "urls": ["https://b.example/rss"]}, [b]),
            ])

            result = fetcher.fetch_news()

            assert len(result) == 2, f"误合并: {title_a!r} vs {title_b!r}"


class TestExcludeLinkPatterns:
    def test_entry_with_matching_link_pattern_is_dropped(self, monkeypatch):
        now = datetime.now(timezone.utc)
        comic = FakeEntry(published_parsed=now.timetuple(), title="漫评：急出口",
                          link="https://theinitium.com/20260726-opinion-cartoon-final-exit/")
        podcast = FakeEntry(published_parsed=now.timetuple(), title="端聞 Podcast",
                            link="https://theinitium.com/20260724-initium-audio-taiwan/")
        news = FakeEntry(published_parsed=now.timetuple(), title="台湾油品污染事件",
                         link="https://theinitium.com/20260724-whatsnew-taiwan-oil/")
        _install_feeds(monkeypatch, [
            ({"name": "端传媒", "urls": ["https://feed.example/rss"],
              "exclude_link_patterns": ["opinion-cartoon", "initium-audio"]},
             [comic, podcast, news]),
        ])

        result = fetcher.fetch_news()

        assert [e["title"] for e in result] == ["台湾油品污染事件"]

    def test_source_without_patterns_keeps_all_links(self, monkeypatch):
        now = datetime.now(timezone.utc)
        entry = FakeEntry(published_parsed=now.timetuple(), title="普通新闻",
                          link="https://example.com/opinion-cartoon-lookalike")
        _install_feed(monkeypatch, [entry])

        result = fetcher.fetch_news()

        assert [e["title"] for e in result] == ["普通新闻"]
