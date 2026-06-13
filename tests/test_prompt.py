from pathlib import Path


PROMPT = (Path(__file__).resolve().parents[1] / "prompt.txt").read_text(encoding="utf-8")


class TestPromptTemplate:
    def test_keeps_machine_parse_contract(self):
        assert "HEADLINE:" in PROMPT
        assert "TAGS:" in PROMPT
        assert "---" in PROMPT
        assert PROMPT.index("HEADLINE:") < PROMPT.index("TAGS:") < PROMPT.index("---")

    def test_uses_notion_editorial_layout(self):
        required_sections = [
            "## AI 晨报",
            "### 01 今日主线",
            "### 02 必读",
            "### 03 深读一条",
            "### 04 分区速览",
            "### 05 接下来关注",
        ]

        for section in required_sections:
            assert section in PROMPT

        assert "发生了什么" in PROMPT
        assert "为什么重要" in PROMPT
        assert "接下来观察" in PROMPT

    def test_avoids_decorative_banner_lines(self):
        assert "▁▁" not in PROMPT
        assert "▔▔" not in PROMPT
