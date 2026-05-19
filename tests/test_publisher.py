import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from publisher import _md_to_notion_blocks, _parse_rich_text


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
