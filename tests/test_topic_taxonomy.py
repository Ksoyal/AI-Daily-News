import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import publisher
import summarizer
from topic_taxonomy import CANONICAL_TAGS, _load_taxonomy, normalize_tags, topic_prompt


@pytest.mark.parametrize("raw, expected", [
    ("AI 治理", "AI治理"),
    (" #AI商业化 ", "AI商业化"),
    ("#地缘政治", "地缘政治"),
    ("美中博弈", "中美博弈"),
    ("AI Agent", "AI智能体"),
    ("智能体", "AI智能体"),
    ("#半导体", "半导体"),
    ("#生成式AI", "生成式AI"),
    ("#SpaceX上市", "SpaceX上市"),
    ("#美伊冲突", "美伊冲突"),
    ("AI 资本化", "AI资本化"),
    ("＃ＡＩ　治理", "AI治理"),
    ("ai agent", "AI智能体"),
])
def test_reviewed_aliases_and_format_variants(raw, expected):
    assert normalize_tags([raw]) == ([expected], [])


def test_each_existing_canonical_topic_retains_its_meaning():
    for tag in CANONICAL_TAGS:
        assert normalize_tags([tag]) == ([tag], [])


@pytest.mark.parametrize("topics", [
    ["AI治理", "AI监管", "AI安全"],
    ["具身智能", "物理AI", "端侧AI"],
    ["中美关系", "中美博弈", "中美贸易"],
    ["AI商业化", "AI资本化", "资本市场"],
    ["半导体", "AI芯片", "半导体周期"],
    ["传统工业转型", "传统产业转型", "产业升级"],
])
def test_independent_and_low_frequency_topics_are_not_collapsed(topics):
    assert normalize_tags(topics) == (topics, [])


def test_normalize_and_deduplicate_before_applying_limit():
    assert normalize_tags(["AI 治理", "AI治理", "AI治理", "#地缘政治", "半导体", "AI产业"]) == (
        ["AI治理", "地缘政治", "半导体"], [],
    )


def test_unknown_and_malformed_topics_are_review_candidates_not_guessed():
    assert normalize_tags(["量子智能新主题", "地缘政治", "中美对抗", None, "量子智能新主题"]) == (
        ["地缘政治"], ["量子智能新主题", "中美对抗", None],
    )
    assert normalize_tags([]) == ([], [])
    assert normalize_tags(None) == ([], [])
    with pytest.raises(ValueError, match="list or tuple"):
        normalize_tags("地缘政治")


@pytest.mark.parametrize("data, message", [
    ({"version": 1, "canonical_tags": ["AI治理", "AI治理"], "aliases": {}}, "Duplicate"),
    ({"version": 1, "canonical_tags": ["AI治理"], "aliases": {"治理": "不存在"}}, "Unknown alias"),
    ({"version": 1, "canonical_tags": ["AI治理", "AI监管"], "aliases": {"AI治理": "AI监管"}}, "Conflicting"),
    ({"version": 1, "canonical_tags": ["#AI治理"], "aliases": {}}, "Invalid"),
])
def test_invalid_taxonomy_fails_closed(tmp_path, data, message):
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        _load_taxonomy(path)


def test_parser_normalizes_tags_without_changing_headline_or_body(caplog):
    body = "## 01 今日主线\n原文 **事实**（来源：[36氪](https://36kr.com/a)）"
    parsed = summarizer._parse_report("HEADLINE: 原标题\nTAGS: AI 治理，AI治理,新话题,美中博弈,#地缘政治\n---\n" + body)
    assert parsed == {"headline": "原标题", "tags": ["AI治理", "中美博弈", "地缘政治"], "content": body}
    assert "新话题" in caplog.text and "pending taxonomy review" in caplog.text


def test_unknown_only_tags_do_not_get_fabricated_defaults():
    parsed = summarizer._parse_report("HEADLINE: 标题\nTAGS: 新主题,不认识\n---\n原正文")
    assert parsed == {"headline": "标题", "tags": [], "content": "原正文"}


def test_publisher_revalidates_even_existing_unapproved_notion_options(caplog):
    options = [
        {"name": "AI治理", "id": "governance"},
        {"name": "中美博弈", "id": "us-china"},
        {"name": "新主题", "id": "unreviewed"},
        {"name": "#地缘政治", "id": "legacy"},
    ]
    assert publisher._topic_option_ids(["AI 治理", "AI治理", "新主题", "美中博弈", "#地缘政治"], options) == [
        {"id": "governance"}, {"id": "us-china"},
    ]
    assert "新主题" in caplog.text and "地缘政治" in caplog.text


def test_page_creation_uses_ids_only_and_preserves_body(monkeypatch, caplog):
    calls = []
    options = [{"name": "AI治理", "id": "governance"}, {"name": "地缘政治", "id": "geopolitics"}]
    class Response:
        def __init__(self, payload):
            self.payload = payload
        def json(self):
            return self.payload
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        if method == "GET":
            return Response({"properties": {
                "无关分类": {"type": "multi_select", "multi_select": {"options": [{"name": "AI治理", "id": "wrong"}]}},
                "标题": {"type": "title"}, "发布日期": {"type": "date"},
                "核心话题": {"type": "multi_select", "multi_select": {"options": options}},
            }})
        if url.endswith("/query"):
            return Response({"results": []})
        return Response({"id": "new-page", "url": "https://notion.so/new-page"})
    monkeypatch.setenv("NOTION_TOKEN", "fake")
    monkeypatch.setenv("NOTION_DATABASE_ID", "fake-db")
    monkeypatch.setattr(publisher, "_retry_request", request)
    content = "## 01 今日主线\n原正文（来源：[36氪](https://36kr.com/a)）"
    report = {"headline": "原标题", "tags": ["AI 治理", "#地缘政治", "未审核新主题"], "content": content}
    publisher.push_to_notion(report)
    body = calls[-1][2]
    assert body["properties"]["核心话题"] == {"multi_select": [{"id": "governance"}, {"id": "geopolitics"}]}
    assert "无关分类" not in body["properties"]
    assert body["properties"]["标题"] == {"title": [{"text": {"content": "原标题"}}]}
    assert body["children"] == publisher._md_to_notion_blocks(content)
    assert report["tags"] == ["AI 治理", "#地缘政治", "未审核新主题"]
    assert "未审核新主题" in caplog.text
    assert [method for method, _, _ in calls] == ["GET", "POST", "POST"]


def test_unavailable_options_cannot_be_created_by_name():
    assert publisher._topic_option_ids(["AI治理", "新主题"], []) == []


def test_vocab_is_injected_even_with_custom_system_prompt(monkeypatch):
    from types import SimpleNamespace
    calls = []
    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                model="fake", usage=None,
                choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="HEADLINE: 标题\nTAGS: AI治理\n---\n正文"))],
            )
    monkeypatch.setattr(summarizer, "AI_SYSTEM_PROMPT", "自定义正文规则与来源白名单")
    monkeypatch.setattr(summarizer, "AI_API_KEY", "fake")
    monkeypatch.setattr(summarizer, "OpenAI", Client)
    summarizer.generate_report([{"title": "标题", "link": "https://example.com", "source": "36氪"}])
    assert calls[0]["messages"][0]["content"] == "自定义正文规则与来源白名单\n\n" + topic_prompt()
