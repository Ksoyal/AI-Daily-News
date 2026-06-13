import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from summarizer import _build_news_text
import summarizer
import config


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


class TestReportParsing:
    """Verify the regex parsing in generate_report handles various AI outputs."""

    def test_parse_valid_output(self):
        raw = """HEADLINE: 今日关键变化
TAGS: AI，市场, 政策
---
## 今日要闻
正文内容"""

        result = summarizer._parse_report(raw)

        assert result == {
            "headline": "今日关键变化",
            "tags": ["AI", "市场", "政策"],
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
