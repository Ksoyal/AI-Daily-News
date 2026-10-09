import sys
import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import httpx
from openai import AuthenticationError, BadRequestError, APITimeoutError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from summarizer import _build_news_text, _format_news_item
import summarizer
import config
from config import REPORT_TZ

FROZEN_NOW = datetime(2026, 7, 24, 9, 0, tzinfo=REPORT_TZ)


class FakeDatetime(datetime):
    """datetime subclass with a frozen now() for deterministic tests."""

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW


class FakeRateLimitError(summarizer.RateLimitError):
    """RateLimitError without the httpx.Response ceremony."""

    def __init__(self, message="rate limited"):
        Exception.__init__(self, message)
        self.message = message


def _make_response(content, with_choice=True):
    if with_choice:
        choices = [SimpleNamespace(finish_reason="stop",
                                   message=SimpleNamespace(content=content))]
    else:
        choices = []
    return SimpleNamespace(choices=choices, model="fake-model", usage=None)


def _fake_openai_factory(outcomes, calls):
    """Build a fake OpenAI class whose create() pops outcomes (exception → raise)."""

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    return FakeOpenAI


class TestBuildNewsText:
    def test_few_entries_all_included(self):
        news = [
            {"title": "新闻A", "link": "http://a.com", "source": "源1"},
            {"title": "新闻B", "link": "http://b.com", "source": "源2"},
            {"title": "新闻C", "link": "http://c.com", "source": "源1"},
        ]
        text = _build_news_text(news)
        assert "新闻A" in text
        assert "新闻B" in text
        assert "新闻C" in text

    def test_many_entries_respect_budget(self):
        news = []
        for i in range(200):
            news.append({
                "title": f"新闻标题{i}",
                "link": f"http://example.com/{i}",
                "source": f"源{i % 5}",
            })
        text = _build_news_text(news)
        assert len(text) <= config.AI_MAX_INPUT_CHARS

    def test_empty_list_returns_empty(self):
        assert _build_news_text([]) == ""

    def test_single_source_gets_all_entries(self):
        news = [
            {"title": f"新闻{i}", "link": "http://x.com", "source": "唯一源"}
            for i in range(10)
        ]
        text = _build_news_text(news)
        assert text.count("标题：") == 10

    def test_summary_is_included_when_present(self):
        news = [{
            "title": "新闻A",
            "link": "http://a.com",
            "source": "源1",
            "summary": "这是用于减少幻觉的新闻上下文。",
        }]

        text = _build_news_text(news)

        assert "摘要：这是用于减少幻觉的新闻上下文。" in text


class TestBudgetTruncation:
    def test_budget_strips_summaries_and_drops_overflow(self, monkeypatch):
        monkeypatch.setattr(summarizer, "AI_MAX_INPUT_CHARS", 700)
        monkeypatch.setattr(summarizer, "AI_MIN_PER_SOURCE", 2)
        news = []
        for src in ("源A", "源B"):
            for i in range(3):
                news.append({
                    "title": f"{src}标题{i}" + "长" * 6,
                    "link": f"http://x.com/{src}{i}",
                    "source": src,
                    "summary": "详" * 200,
                })

        text = _build_news_text(news)

        assert len(text) <= 700
        # 2 of 6 entries dropped, but every source keeps the per-source floor
        assert text.count("标题：") == 4
        assert text.count("来源：源A") == 2
        assert text.count("来源：源B") == 2
        assert "源A标题2" not in text
        assert "源B标题2" not in text
        # only the first entry per source keeps its summary; floor entries are stripped
        assert text.count("摘要：") == 2

    def test_floor_entry_title_truncated_with_ellipsis(self, monkeypatch):
        monkeypatch.setattr(summarizer, "AI_MAX_INPUT_CHARS", 150)
        monkeypatch.setattr(summarizer, "AI_MIN_PER_SOURCE", 2)
        long_title = "深" * 200
        news = [
            {"title": "短标题", "link": "http://a.com", "source": "源1"},
            {"title": long_title, "link": "http://b.com", "source": "源1"},
        ]

        text = _build_news_text(news)

        assert len(text) <= 150
        assert text.count("标题：") == 2
        assert long_title not in text
        assert "深" * 82 + "..." in text


class TestGenerateReport:
    VALID_OUTPUT = """HEADLINE: 测试标题
TAGS: AI治理, 地缘政治
---
## 今日要闻
正文内容"""

    SAMPLE_NEWS = [
        {"title": "新闻A", "link": "http://a.com", "source": "源1"},
        {"title": "新闻B", "link": "http://b.com", "source": "源2"},
    ]

    def _patch(self, monkeypatch, outcomes):
        calls = []
        sleeps = []
        monkeypatch.setattr(summarizer, "AI_API_KEY", "dummy-key")
        monkeypatch.setattr(summarizer, "OpenAI", _fake_openai_factory(outcomes, calls))
        monkeypatch.setattr(summarizer.time, "sleep", lambda delay: sleeps.append(delay))
        return calls, sleeps

    def test_rate_limit_retries_then_succeeds(self, monkeypatch):
        outcomes = [FakeRateLimitError(), FakeRateLimitError(),
                    _make_response(self.VALID_OUTPUT)]
        calls, sleeps = self._patch(monkeypatch, outcomes)

        report = summarizer.generate_report(self.SAMPLE_NEWS)

        assert report["headline"] == "测试标题"
        assert report["tags"] == ["AI治理", "地缘政治"]
        assert report["content"] == "## 今日要闻\n正文内容"
        assert len(calls) == 3
        assert sleeps == [60, 300]

    def test_rate_limit_retries_exhausted_propagates(self, monkeypatch):
        outcomes = [FakeRateLimitError() for _ in range(4)]
        calls, sleeps = self._patch(monkeypatch, outcomes)

        with pytest.raises(summarizer.RateLimitError):
            summarizer.generate_report(self.SAMPLE_NEWS)

        assert len(calls) == 4
        assert sleeps == [60, 300, 900]

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_server_outage_recovers_on_last_delayed_attempt(self, monkeypatch, status):
        response = httpx.Response(status, request=httpx.Request("POST", "https://example.com"))
        error = summarizer.InternalServerError("overloaded", response=response, body=None)
        calls, sleeps = self._patch(monkeypatch, [error] * 3 + [_make_response(self.VALID_OUTPUT)])

        report = summarizer.generate_report(self.SAMPLE_NEWS)

        assert report["headline"] == "测试标题"
        assert len(calls) == 4
        assert sleeps == [60, 300, 900]
        # Retry the same editorial input, without switching model or provider.
        assert all(call == calls[0] for call in calls)

    def test_server_outage_exhaustion_has_no_extra_request_or_sleep(self, monkeypatch):
        response = httpx.Response(503, request=httpx.Request("POST", "https://example.com"))
        error = summarizer.InternalServerError("overloaded", response=response, body=None)
        calls, sleeps = self._patch(monkeypatch, [error] * 4)

        with pytest.raises(summarizer.InternalServerError):
            summarizer.generate_report(self.SAMPLE_NEWS)

        assert len(calls) == 4
        assert sleeps == [60, 300, 900]

    @pytest.mark.parametrize("error_class", [summarizer.APIConnectionError, APITimeoutError])
    def test_network_failure_uses_delayed_retry(self, monkeypatch, error_class):
        error = error_class(request=httpx.Request("POST", "https://example.com"))
        calls, sleeps = self._patch(monkeypatch, [error, _make_response(self.VALID_OUTPUT)])

        summarizer.generate_report(self.SAMPLE_NEWS)

        assert len(calls) == 2
        assert sleeps == [60]

    @pytest.mark.parametrize("status,error_class", [(400, BadRequestError), (401, AuthenticationError)])
    def test_permanent_errors_fail_immediately(self, monkeypatch, status, error_class):
        response = httpx.Response(status, request=httpx.Request("POST", "https://example.com"))
        error = error_class("invalid request", response=response, body=None)
        calls, sleeps = self._patch(monkeypatch, [error])

        with pytest.raises(error_class):
            summarizer.generate_report(self.SAMPLE_NEWS)

        assert len(calls) == 1
        assert sleeps == []

    def test_success_does_not_wait(self, monkeypatch):
        calls, sleeps = self._patch(monkeypatch, [_make_response(self.VALID_OUTPUT)])

        summarizer.generate_report(self.SAMPLE_NEWS)

        assert len(calls) == 1
        assert sleeps == []

    def test_disables_sdk_retries_to_avoid_nested_attempts(self, monkeypatch):
        calls = []
        client_options = {}
        fake_client = _fake_openai_factory(
            [_make_response(self.VALID_OUTPUT)], calls
        )

        def capturing_client(**kwargs):
            client_options.update(kwargs)
            return fake_client(**kwargs)

        monkeypatch.setattr(summarizer, "AI_API_KEY", "dummy-key")
        monkeypatch.setattr(summarizer, "OpenAI", capturing_client)

        summarizer.generate_report(self.SAMPLE_NEWS)

        assert client_options.get("max_retries") == 0

    def test_empty_choices_raises_runtime_error(self, monkeypatch):
        outcomes = [_make_response(None, with_choice=False)]
        calls, _ = self._patch(monkeypatch, outcomes)

        with pytest.raises(RuntimeError, match="no choices"):
            summarizer.generate_report(self.SAMPLE_NEWS)

        assert len(calls) == 1

    def test_none_content_raises_runtime_error(self, monkeypatch):
        outcomes = [_make_response(None)]
        calls, _ = self._patch(monkeypatch, outcomes)

        with pytest.raises(RuntimeError, match="empty content"):
            summarizer.generate_report(self.SAMPLE_NEWS)

        assert len(calls) == 1

    def test_empty_news_list_raises_without_api_call(self, monkeypatch):
        def forbidden_client(**kwargs):
            raise AssertionError("OpenAI client should not be constructed")

        monkeypatch.setattr(summarizer, "AI_API_KEY", "dummy-key")
        monkeypatch.setattr(summarizer, "OpenAI", forbidden_client)

        with pytest.raises(ValueError, match="news_list is empty"):
            summarizer.generate_report([])


class TestNewsItemAge:
    def _patch_now(self, monkeypatch):
        monkeypatch.setattr(summarizer, "datetime", FakeDatetime)

    def test_age_line_for_fresh_entry(self, monkeypatch):
        self._patch_now(monkeypatch)
        entry = {
            "title": "新闻A",
            "link": "http://a.com",
            "source": "源1",
            "published": (FROZEN_NOW - timedelta(hours=3)).isoformat(),
        }

        text = _format_news_item(1, entry)

        assert "发布：约3小时前" in text
        assert "链接：http://a.com" in text

    def test_age_rounds_to_nearest_hour(self, monkeypatch):
        self._patch_now(monkeypatch)
        entry = {
            "title": "新闻A",
            "link": "http://a.com",
            "source": "源1",
            "published": (FROZEN_NOW - timedelta(hours=2, minutes=50)).isoformat(),
        }

        text = _format_news_item(1, entry)

        assert "发布：约3小时前" in text

    def test_age_renders_days_beyond_48_hours(self, monkeypatch):
        self._patch_now(monkeypatch)
        entry = {
            "title": "新闻A",
            "link": "http://a.com",
            "source": "源1",
            "published": (FROZEN_NOW - timedelta(days=3)).isoformat(),
        }

        text = _format_news_item(1, entry)

        assert "发布：约3天前" in text

    def test_age_line_absent_when_published_missing(self, monkeypatch):
        self._patch_now(monkeypatch)
        entry = {"title": "新闻A", "link": "http://a.com", "source": "源1"}

        text = _format_news_item(1, entry)

        assert "发布：" not in text
        assert "链接：http://a.com" in text

    def test_age_line_absent_when_published_unparseable(self, monkeypatch):
        self._patch_now(monkeypatch)
        entry = {
            "title": "新闻A",
            "link": "http://a.com",
            "source": "源1",
            "published": "not-a-date",
        }

        text = _format_news_item(1, entry)

        assert "发布：" not in text


class TestUserMessage:
    SAMPLE_NEWS = [
        {"title": "新闻A", "link": "http://a.com", "source": "源1"},
        {"title": "新闻B", "link": "http://b.com", "source": "源2"},
    ]

    def _patch(self, monkeypatch):
        calls = []
        monkeypatch.setattr(summarizer, "AI_API_KEY", "dummy-key")
        monkeypatch.setattr(summarizer, "OpenAI",
                            _fake_openai_factory([_make_response(TestGenerateReport.VALID_OUTPUT)], calls))
        monkeypatch.setattr(summarizer, "datetime", FakeDatetime)
        return calls

    def _user_content(self, calls):
        return calls[0]["messages"][1]["content"]

    def test_user_message_starts_with_date_line(self, monkeypatch):
        calls = self._patch(monkeypatch)

        summarizer.generate_report(self.SAMPLE_NEWS)

        content = self._user_content(calls)
        assert content.startswith("今天是 2026年7月24日（星期五）。")
        assert "以下是最近的新闻列表（每条已标注发布时效），请生成日报：" in content
        assert "新闻A" in content

    def test_previous_context_block_inserted_before_news_list(self, monkeypatch):
        calls = self._patch(monkeypatch)

        summarizer.generate_report(self.SAMPLE_NEWS, previous_context="上期焦点：A公司发布新模型。")

        content = self._user_content(calls)
        assert "【上期日报概要】" in content
        assert "上期焦点：A公司发布新模型。" in content
        assert "（上期已覆盖且无新进展的事件请省略；有进展只写增量并注明与上期的差异。）" in content
        assert content.index("【上期日报概要】") < content.index("以下是最近的新闻列表")

    def test_previous_context_absent_by_default(self, monkeypatch):
        calls = self._patch(monkeypatch)

        summarizer.generate_report(self.SAMPLE_NEWS)

        content = self._user_content(calls)
        assert "【上期日报概要】" not in content

    def test_previous_context_empty_string_ignored(self, monkeypatch):
        calls = self._patch(monkeypatch)

        summarizer.generate_report(self.SAMPLE_NEWS, previous_context="   ")

        content = self._user_content(calls)
        assert "【上期日报概要】" not in content


class TestReportParsing:
    """Verify the regex parsing in generate_report handles various AI outputs."""

    def test_parse_valid_output(self):
        raw = """HEADLINE: 今日关键变化
TAGS: AI治理，资本市场, 贸易政策
---
## 今日要闻
正文内容"""

        result = summarizer._parse_report(raw)

        assert result == {
            "headline": "今日关键变化",
            "tags": ["AI治理", "资本市场", "贸易政策"],
            "content": "## 今日要闻\n正文内容",
        }

    def test_parse_output_without_markers_keeps_raw_body(self):
        result = summarizer._parse_report("没有结构化标记的正文")

        assert result["headline"] == "AI 晨报"
        assert result["tags"] == []
        assert result["content"] == "没有结构化标记的正文"

    def test_blank_output_is_rejected(self):
        with pytest.raises(RuntimeError, match="empty report body"):
            summarizer._parse_report("   \n\n")

    def test_metadata_only_output_is_rejected(self):
        raw = """HEADLINE: 今日标题
TAGS: AI, 市场
---"""

        with pytest.raises(RuntimeError, match="empty report body"):
            summarizer._parse_report(raw)
