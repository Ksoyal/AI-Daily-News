import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


SAMPLE_NEWS = [
    {"title": "新闻A", "link": "http://a.com", "source": "源1", "summary": "摘要A"},
    {"title": "新闻B", "link": "http://b.com", "source": "源2", "summary": "摘要B"},
]

SAMPLE_REPORT = {
    "headline": "今日关键变化",
    "tags": ["AI", "市场"],
    "content": "## 今日要闻\n正文内容",
}


@pytest.fixture
def notify_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "notify", lambda title, desp="": calls.append((title, desp)))
    return calls


@pytest.fixture(autouse=True)
def no_previous_context(monkeypatch):
    """Keep tests offline: never hit Notion for yesterday's report."""
    monkeypatch.setattr(main, "get_previous_report_context", lambda: None)


class TestMainOrchestration:
    def test_empty_fetch_exits_with_failure_notify(self, monkeypatch, notify_calls):
        monkeypatch.setattr(main, "fetch_news", lambda: [])
        monkeypatch.setattr(main, "generate_report",
                            lambda news, **kw: pytest.fail("must not summarize"))
        monkeypatch.setattr(main, "push_to_notion", lambda report: pytest.fail("must not publish"))

        with pytest.raises(SystemExit) as exc_info:
            main.main()

        assert exc_info.value.code == 1
        assert len(notify_calls) == 1
        title, desp = notify_calls[0]
        assert title.startswith("❌")
        assert "RuntimeError" in desp

    def test_happy_path_sends_success_notify(self, monkeypatch, notify_calls):
        published = []
        monkeypatch.setattr(main, "fetch_news", lambda: SAMPLE_NEWS)
        monkeypatch.setattr(main, "generate_report", lambda news, **kw: SAMPLE_REPORT)
        monkeypatch.setattr(
            main, "push_to_notion",
            lambda report: published.append(report) or {"url": "https://notion.so/page"},
        )

        main.main()

        assert published == [SAMPLE_REPORT]
        assert len(notify_calls) == 1
        title, desp = notify_calls[0]
        assert "✅" in title
        assert SAMPLE_REPORT["headline"] in title
        assert "AI/市场" in desp

    def test_skipped_publish_sends_skip_notify_not_success(self, monkeypatch, notify_calls):
        monkeypatch.setattr(main, "fetch_news", lambda: SAMPLE_NEWS)
        monkeypatch.setattr(main, "generate_report", lambda news, **kw: SAMPLE_REPORT)
        monkeypatch.setattr(
            main, "push_to_notion",
            lambda report: {"skipped": True, "url": "https://notion.so/existing"},
        )

        main.main()

        assert len(notify_calls) == 1
        title, desp = notify_calls[0]
        assert "⏭️" in title
        assert desp == "https://notion.so/existing"
        assert not any("✅" in t for t, _ in notify_calls)

    def test_generate_report_failure_exits_with_failure_notify(self, monkeypatch, notify_calls):
        monkeypatch.setattr(main, "fetch_news", lambda: SAMPLE_NEWS)

        def boom(news, **kw):
            raise ValueError("AI exploded")

        monkeypatch.setattr(main, "generate_report", boom)
        monkeypatch.setattr(main, "push_to_notion", lambda report: pytest.fail("must not publish"))

        with pytest.raises(SystemExit) as exc_info:
            main.main()

        assert exc_info.value.code == 1
        assert len(notify_calls) == 1
        title, desp = notify_calls[0]
        assert title.startswith("❌")
        assert "ValueError: AI exploded" in desp

    def test_previous_context_is_passed_to_generate_report(self, monkeypatch, notify_calls):
        received = {}
        monkeypatch.setattr(main, "fetch_news", lambda: SAMPLE_NEWS)
        monkeypatch.setattr(main, "get_previous_report_context", lambda: "昨日标题：X")

        def capture(news, previous_context=None):
            received["ctx"] = previous_context
            return SAMPLE_REPORT

        monkeypatch.setattr(main, "generate_report", capture)
        monkeypatch.setattr(main, "push_to_notion", lambda report: {"url": "https://notion.so/p"})

        main.main()

        assert received["ctx"] == "昨日标题：X"
