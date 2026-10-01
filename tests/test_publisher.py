import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import publisher
from publisher import _md_to_notion_blocks, _parse_rich_text


class FakeJsonResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(str(self.status_code))
            error.response = self
            raise error


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

    def test_400_raises_without_retry_or_sleep(self, monkeypatch):
        attempts = []
        sleeps = []

        def fake_request(method, url, **kwargs):
            attempts.append((method, url))
            return FakeJsonResponse({"message": "bad request"}, status_code=400)

        monkeypatch.setattr(publisher.requests, "request", fake_request)
        monkeypatch.setattr(publisher.time, "sleep", lambda delay: sleeps.append(delay))

        with pytest.raises(requests.HTTPError):
            publisher._retry_request("POST", "https://example.com")

        assert len(attempts) == 1
        assert sleeps == []

    def test_500_then_200_retries_and_succeeds(self, monkeypatch):
        attempts = []
        sleeps = []
        responses = [
            FakeJsonResponse({"message": "boom"}, status_code=500),
            FakeJsonResponse({"ok": True}, status_code=200),
        ]

        def fake_request(method, url, **kwargs):
            attempts.append((method, url))
            return responses.pop(0)

        monkeypatch.setattr(publisher, "HTTP_RETRY_BACKOFF", (0,))
        monkeypatch.setattr(publisher.requests, "request", fake_request)
        monkeypatch.setattr(publisher.time, "sleep", lambda delay: sleeps.append(delay))

        resp = publisher._retry_request("GET", "https://example.com")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert len(attempts) == 2
        assert sleeps == [0]


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


class TestParseRichTextLinks:
    def test_link_produces_linked_rich_text(self):
        result = _parse_rich_text("[36氪](https://36kr.com/p/x)")
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert result[0]["text"]["content"] == "36氪"
        assert result[0]["text"]["link"] == {"url": "https://36kr.com/p/x"}
        assert result[0]["annotations"]["bold"] is False

    def test_source_pattern_link_followed_by_plain_text(self):
        result = _parse_rich_text("（来源：[36氪](https://36kr.com/p/x)）")
        assert [part["text"]["content"] for part in result] == ["（来源：", "36氪", "）"]
        assert "link" not in result[0]["text"]
        assert result[1]["text"]["link"] == {"url": "https://36kr.com/p/x"}
        assert "link" not in result[2]["text"]

    def test_link_in_paragraph_with_surrounding_bold(self):
        result = _parse_rich_text("**重点**：详见[报道](https://example.com/a)。")
        assert result[0]["text"]["content"] == "重点"
        assert result[0]["annotations"]["bold"] is True
        assert result[1]["text"]["content"] == "：详见"
        assert result[1]["annotations"]["bold"] is False
        assert result[2]["text"]["content"] == "报道"
        assert result[2]["text"]["link"] == {"url": "https://example.com/a"}
        assert result[2]["annotations"]["bold"] is False
        assert result[3]["text"]["content"] == "。"
        assert result[3]["annotations"]["bold"] is False

    def test_bold_markers_inside_link_text_are_stripped(self):
        result = _parse_rich_text("[**36氪**](https://36kr.com/p/x)")
        assert len(result) == 1
        assert result[0]["text"]["content"] == "36氪"
        assert result[0]["text"]["link"] == {"url": "https://36kr.com/p/x"}

    def test_non_http_target_stays_literal(self):
        result = _parse_rich_text("[点击](ftp://example.com/file)")
        assert all("link" not in part["text"] for part in result)
        assert "".join(part["text"]["content"] for part in result) == "[点击](ftp://example.com/file)"

    def test_non_link_text_around_link_is_still_chunked(self):
        result = _parse_rich_text("a" * 2001 + "[36氪](https://36kr.com/p/x)")
        assert [len(part["text"]["content"]) for part in result] == [2000, 1, 3]
        assert result[2]["text"]["link"] == {"url": "https://36kr.com/p/x"}


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

    def test_heading_3(self):
        blocks = _md_to_notion_blocks("### 短期影响")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "heading_3"
        assert "heading_2" not in blocks[0]
        assert blocks[0]["heading_3"]["rich_text"][0]["text"]["content"] == "短期影响"

    def test_quote(self):
        blocks = _md_to_notion_blocks("> 今日引语")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "quote"
        assert blocks[0]["quote"]["rich_text"][0]["text"]["content"] == "今日引语"

    def test_divider_dash_and_decorative_line(self):
        blocks = _md_to_notion_blocks("---\n━━━")
        assert [block["type"] for block in blocks] == ["divider", "divider"]

    def test_numbered_list_item(self):
        blocks = _md_to_notion_blocks("❶ 第一条要闻")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "numbered_list_item"
        assert blocks[0]["numbered_list_item"]["rich_text"][0]["text"]["content"] == "第一条要闻"

    def test_bullet_with_link(self):
        blocks = _md_to_notion_blocks("- 新闻摘要（来源：[36氪](https://36kr.com/p/x)）")
        assert blocks[0]["type"] == "bulleted_list_item"
        rich = blocks[0]["bulleted_list_item"]["rich_text"]
        linked = [part for part in rich if "link" in part["text"]]
        assert len(linked) == 1
        assert linked[0]["text"]["content"] == "36氪"
        assert linked[0]["text"]["link"] == {"url": "https://36kr.com/p/x"}

    def test_heading_2_strips_bold_markers(self):
        blocks = _md_to_notion_blocks("## **今日要闻**")
        rich = blocks[0]["heading_2"]["rich_text"]
        assert rich[0]["text"]["content"] == "今日要闻"
        assert "annotations" not in rich[0]

    def test_heading_3_strips_bold_markers(self):
        blocks = _md_to_notion_blocks("### 短期**影响**")
        assert blocks[0]["heading_3"]["rich_text"][0]["text"]["content"] == "短期影响"


class TestGetDatabaseProperties:
    def test_discovers_title_date_and_multi_select_columns(self, monkeypatch):
        schema = {
            "properties": {
                "备注": {"type": "rich_text"},
                "标题": {"type": "title"},
                "发布日期": {"type": "date"},
                "核心话题": {"type": "multi_select"},
            }
        }
        monkeypatch.setattr(
            publisher, "_retry_request",
            lambda method, url, **kwargs: FakeJsonResponse(schema),
        )

        result = publisher._get_database_properties("secret", "database")

        assert result == ("标题", "发布日期", "核心话题", [])

    def test_missing_title_column_raises_value_error(self, monkeypatch):
        schema = {
            "properties": {
                "发布日期": {"type": "date"},
                "核心话题": {"type": "multi_select"},
            }
        }
        monkeypatch.setattr(
            publisher, "_retry_request",
            lambda method, url, **kwargs: FakeJsonResponse(schema),
        )

        with pytest.raises(ValueError, match="title"):
            publisher._get_database_properties("secret", "database")


class TestFindTodayPage:
    def test_query_body_filters_date_property_with_equals(self, monkeypatch):
        calls = []

        def fake_retry_request(method, url, **kwargs):
            calls.append((method, url, kwargs.get("json")))
            return FakeJsonResponse({"results": []})

        monkeypatch.setattr(publisher, "_retry_request", fake_retry_request)

        result = publisher._find_today_page("secret", "database", "发布日期", "2026-07-26")

        assert result is None
        method, url, body = calls[0]
        assert method == "POST"
        assert url.endswith("/v1/databases/database/query")
        assert body["filter"]["property"] == "发布日期"
        assert body["filter"]["date"] == {"equals": "2026-07-26"}

    def test_existing_page_returns_its_url(self, monkeypatch):
        payload = {"results": [{"id": "page-1", "url": "https://notion.so/existing"}]}
        monkeypatch.setattr(
            publisher, "_retry_request",
            lambda method, url, **kwargs: FakeJsonResponse(payload),
        )

        result = publisher._find_today_page("secret", "database", "发布日期", "2026-07-26")

        assert result == "https://notion.so/existing"

    def test_page_without_url_falls_back_to_id(self, monkeypatch):
        payload = {"results": [{"id": "ab-cd-ef"}]}
        monkeypatch.setattr(
            publisher, "_retry_request",
            lambda method, url, **kwargs: FakeJsonResponse(payload),
        )

        result = publisher._find_today_page("secret", "database", "发布日期", "2026-07-26")

        assert result == "https://notion.so/abcdef"

    def test_no_date_column_skips_query(self, monkeypatch):
        def fake_retry_request(method, url, **kwargs):
            raise AssertionError("Notion API should not be called")

        monkeypatch.setattr(publisher, "_retry_request", fake_retry_request)

        assert publisher._find_today_page("secret", "database", None, "2026-07-26") is None


class TestToday:
    def test_passes_report_tz_to_datetime_now(self, monkeypatch):
        captured = []

        class FakeDateTime:
            @staticmethod
            def now(tz=None):
                captured.append(tz)
                return datetime(2026, 7, 26, 23, 30, tzinfo=tz)

        monkeypatch.setattr(publisher, "datetime", FakeDateTime)

        assert publisher._today() == "2026-07-26"
        assert captured == [publisher.REPORT_TZ]

    def test_report_tz_rolls_date_forward_past_utc_midnight(self, monkeypatch):
        class FakeDateTime:
            @staticmethod
            def now(tz=None):
                base = datetime(2026, 7, 26, 20, 0, tzinfo=timezone.utc)
                return base.astimezone(tz)

        monkeypatch.setattr(publisher, "datetime", FakeDateTime)
        monkeypatch.setattr(publisher, "REPORT_TZ", timezone(timedelta(hours=8)))

        # 20:00 UTC is already 04:00 next day in UTC+8
        assert publisher._today() == "2026-07-27"


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
        monkeypatch.setattr(publisher, "_get_database_properties", lambda token, database_id: ("Name", "Date", None, []))
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

    def test_skips_page_creation_when_today_page_exists(self, monkeypatch):
        calls = []

        def fake_retry_request(method, url, **kwargs):
            calls.append((method, url))
            if method == "GET" and "/v1/databases/" in url:
                return FakeJsonResponse({"properties": {
                    "Name": {"type": "title"},
                    "Date": {"type": "date"},
                }})
            if method == "POST" and url.endswith("/query"):
                return FakeJsonResponse({"results": [
                    {"id": "page-old", "url": "https://notion.so/existing"}
                ]})
            raise AssertionError(f"unexpected request: {method} {url}")

        monkeypatch.setenv("NOTION_TOKEN", "secret")
        monkeypatch.setenv("NOTION_DATABASE_ID", "database")
        monkeypatch.setattr(publisher, "_retry_request", fake_retry_request)

        result = publisher.push_to_notion({
            "headline": "标题",
            "tags": ["AI"],
            "content": "## 今日要闻\n- 一条新闻",
        })

        assert result == {"url": "https://notion.so/existing", "skipped": True}
        assert not any(
            method == "POST" and url.endswith("/v1/pages")
            for method, url in calls
        )


class TestGetPreviousReportContext:
    SCHEMA = {"properties": {
        "标题": {"type": "title"},
        "发布日期": {"type": "date"},
        "核心话题": {"type": "multi_select"},
    }}

    PAGE = {
        "id": "page-prev",
        "properties": {
            "标题": {"title": [{"plain_text": "昨日头条"}]},
            "发布日期": {"date": {"start": "2026-07-25"}},
            "核心话题": {"multi_select": [{"name": "AI"}, {"name": "芯片"}]},
        },
    }

    BLOCKS = {"results": [
        {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "01 今日主线"}]}},
        {"type": "bulleted_list_item",
         "bulleted_list_item": {"rich_text": [{"plain_text": "主线一：AI 重资产化"}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "02 必读"}]}},
        {"type": "bulleted_list_item",
         "bulleted_list_item": {"rich_text": [{"plain_text": "必读内容不应入选"}]}},
    ]}

    def test_returns_summary_of_latest_previous_page(self, monkeypatch):
        def fake_retry_request(method, url, **kwargs):
            if method == "GET" and "/v1/databases/" in url and "query" not in url:
                return FakeJsonResponse(self.SCHEMA)
            if method == "POST" and url.endswith("/query"):
                body = kwargs["json"]
                assert body["filter"]["date"].get("before")
                assert body["sorts"][0]["direction"] == "descending"
                return FakeJsonResponse({"results": [self.PAGE]})
            if method == "GET" and "/v1/blocks/page-prev/children" in url:
                return FakeJsonResponse(self.BLOCKS)
            raise AssertionError(f"unexpected request: {method} {url}")

        monkeypatch.setenv("NOTION_TOKEN", "secret")
        monkeypatch.setenv("NOTION_DATABASE_ID", "database")
        monkeypatch.setattr(publisher, "_context_request", fake_retry_request)

        context = publisher.get_previous_report_context()

        assert "日期：2026-07-25" in context
        assert "标题：昨日头条" in context
        assert "标签：AI、芯片" in context
        assert "主线：主线一：AI 重资产化" in context
        assert "必读内容不应入选" not in context

    def test_returns_none_without_credentials(self, monkeypatch):
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)

        assert publisher.get_previous_report_context() is None

    def test_returns_none_when_no_previous_page(self, monkeypatch):
        def fake_retry_request(method, url, **kwargs):
            if method == "GET" and "/v1/databases/" in url:
                return FakeJsonResponse(self.SCHEMA)
            if method == "POST" and url.endswith("/query"):
                return FakeJsonResponse({"results": []})
            raise AssertionError(f"unexpected request: {method} {url}")

        monkeypatch.setenv("NOTION_TOKEN", "secret")
        monkeypatch.setenv("NOTION_DATABASE_ID", "database")
        monkeypatch.setattr(publisher, "_context_request", fake_retry_request)

        assert publisher.get_previous_report_context() is None

    def test_swallows_api_errors_and_returns_none(self, monkeypatch):
        def boom(method, url, **kwargs):
            raise requests.HTTPError("500")

        monkeypatch.setenv("NOTION_TOKEN", "secret")
        monkeypatch.setenv("NOTION_DATABASE_ID", "database")
        monkeypatch.setattr(publisher, "_context_request", boom)

        assert publisher.get_previous_report_context() is None


class TestLinkEdgeCases:
    def test_url_with_parentheses_is_kept_whole(self):
        rich = _parse_rich_text("[维基](https://en.wikipedia.org/wiki/AI_(disambiguation))")

        assert rich[0]["text"]["link"]["url"] == "https://en.wikipedia.org/wiki/AI_(disambiguation)"
        assert len(rich) == 1

    def test_bold_wrapped_link_drops_stray_markers(self):
        rich = _parse_rich_text("（来源：**[36氪](https://36kr.com/p/1)**）")

        plain = "".join(rt["text"]["content"] for rt in rich)
        assert "**" not in plain
        assert any(rt["text"].get("link", {}).get("url") == "https://36kr.com/p/1"
                   for rt in rich if rt["text"].get("link"))
