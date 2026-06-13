import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import publisher
from publisher import _md_to_notion_blocks, _parse_rich_text


class TestRetryRequest:
    def test_reuses_last_backoff_when_retry_count_exceeds_schedule(self, monkeypatch):
        attempts = []

        class FakeResponse:
            status_code = 503
            text = "unavailable"

            def raise_for_status(self):
                error = requests.HTTPError("503")
                error.response = self
                raise error

        def fake_request(method, url, **kwargs):
            attempts.append((method, url))
            return FakeResponse()

        sleeps = []
        monkeypatch.setattr(publisher, "HTTP_RETRIES", 4)
        monkeypatch.setattr(publisher, "HTTP_RETRY_BACKOFF", (0, 0))
        monkeypatch.setattr(publisher.requests, "request", fake_request)
        monkeypatch.setattr(publisher.time, "sleep", lambda delay: sleeps.append(delay))

        with pytest.raises(requests.HTTPError):
            publisher._retry_request("GET", "https://example.com")

        assert len(attempts) == 5
        assert sleeps == [0, 0, 0, 0]


class TestParseRichText:
    def test_plain_text_no_bold(self):
        result = _parse_rich_text("hello world")
        assert len(result) == 1
        assert result[0]["text"]["content"] == "hello world"
        assert result[0]["annotations"]["bold"] is False

    def test_single_bold_segment(self):
        result = _parse_rich_text("this is **bold** text")
        assert len(result) == 3
        assert result[0]["text"]["content"] == "this is "
        assert result[0]["annotations"]["bold"] is False
        assert result[1]["text"]["content"] == "bold"
        assert result[1]["annotations"]["bold"] is True
        assert result[2]["text"]["content"] == " text"
        assert result[2]["annotations"]["bold"] is False

    def test_no_bold_markers(self):
        result = _parse_rich_text("plain text only")
        assert len(result) == 1
        assert result[0]["annotations"]["bold"] is False

    def test_long_text_is_split_for_notion_limits(self):
        result = _parse_rich_text("a" * 2001)

        assert len(result) == 2
        assert len(result[0]["text"]["content"]) == 2000
        assert len(result[1]["text"]["content"]) == 1
        assert all(part["annotations"]["bold"] is False for part in result)

    def test_long_bold_text_preserves_annotation_when_split(self):
        result = _parse_rich_text(f"**{'b' * 2001}**")

        assert len(result) == 2
        assert len(result[0]["text"]["content"]) == 2000
        assert len(result[1]["text"]["content"]) == 1
        assert all(part["annotations"]["bold"] is True for part in result)


class TestMdToNotionBlocks:
    def test_heading_2(self):
        blocks = _md_to_notion_blocks("## 今日要闻")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "heading_2"
        assert blocks[0]["heading_2"]["rich_text"][0]["text"]["content"] == "今日要闻"

    def test_bulleted_list_item(self):
        blocks = _md_to_notion_blocks("- 这是一条新闻摘要")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "bulleted_list_item"

    def test_bulleted_with_bold(self):
        blocks = _md_to_notion_blocks("- **标题**：摘要内容")
        assert blocks[0]["type"] == "bulleted_list_item"
        rich = blocks[0]["bulleted_list_item"]["rich_text"]
        assert rich[0]["text"]["content"] == "标题"
        assert rich[0]["annotations"]["bold"] is True

    def test_paragraph_fallback(self):
        blocks = _md_to_notion_blocks("这是普通段落文字")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "paragraph"

    def test_empty_input(self):
        assert _md_to_notion_blocks("") == []
        assert _md_to_notion_blocks("   \n  \n") == []

    def test_mixed_blocks(self):
        md = """## 科技新闻
- 新闻一
- 新闻二
结尾段落"""
        blocks = _md_to_notion_blocks(md)
        assert blocks[0]["type"] == "heading_2"
        assert blocks[1]["type"] == "bulleted_list_item"
        assert blocks[2]["type"] == "bulleted_list_item"
        assert blocks[3]["type"] == "paragraph"


class TestPushToNotion:
    def test_rejects_empty_report_body_before_creating_page(self, monkeypatch):
        calls = []

        def fake_retry_request(method, url, **kwargs):
            calls.append((method, url))
            raise AssertionError("Notion API should not be called")

        monkeypatch.setenv("NOTION_TOKEN", "secret")
        monkeypatch.setenv("NOTION_DATABASE_ID", "database")
        monkeypatch.setattr(publisher, "_retry_request", fake_retry_request)

        with pytest.raises(ValueError, match="report content produced no Notion blocks"):
            publisher.push_to_notion({
                "headline": "只有标题",
                "tags": [],
                "content": "   \n\n",
            })

        assert calls == []

    def test_appends_blocks_after_create_page_limit(self, monkeypatch):
        blocks = [
            {"type": "paragraph", "paragraph": {"rich_text": []}}
            for _ in range(101)
        ]
        calls = []

        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        def fake_retry_request(method, url, **kwargs):
            calls.append((method, url, kwargs.get("json")))
            if method == "POST" and url.endswith("/v1/pages"):
                return FakeResponse({"id": "page-123", "url": "https://notion.so/page-123"})
            return FakeResponse({"ok": True})

        monkeypatch.setenv("NOTION_TOKEN", "secret")
        monkeypatch.setenv("NOTION_DATABASE_ID", "database")
        monkeypatch.setattr(publisher, "_get_database_properties", lambda token, database_id: ("Name", "Date", None))
        monkeypatch.setattr(publisher, "_find_today_page", lambda token, database_id, date_col, today: None)
        monkeypatch.setattr(publisher, "_md_to_notion_blocks", lambda content: blocks)
        monkeypatch.setattr(publisher, "_retry_request", fake_retry_request)

        result = publisher.push_to_notion({
            "headline": "标题",
            "tags": [],
            "content": "正文",
        })

        assert result["url"] == "https://notion.so/page-123"
        assert calls[0][0] == "POST"
        assert len(calls[0][2]["children"]) == 100
        assert calls[1][0] == "PATCH"
        assert calls[1][1].endswith("/v1/blocks/page-123/children")
        assert len(calls[1][2]["children"]) == 1
