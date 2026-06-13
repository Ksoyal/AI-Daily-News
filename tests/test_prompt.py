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

    def test_prefers_natural_insight_over_mechanical_labels(self):
        assert "洞见句" in PROMPT
        assert "自然段" in PROMPT
        assert "不要逐条套用" in PROMPT
        assert "统一放在最后" in PROMPT

        mechanical_labels = [
            "发生了什么：",
            "为什么重要：",
            "接下来观察：",
        ]
        for label in mechanical_labels:
            assert label not in PROMPT

    def test_does_not_cap_individual_item_length(self):
        forbidden_limits = [
            "90-140",
            "150-220",
            "控制在",
            "每条用以下结构",
        ]
        for phrase in forbidden_limits:
            assert phrase not in PROMPT

    def test_avoids_short_reading_time_anchors(self):
        compression_anchors = [
            "每天只有几分钟",
            "阅读约 4 分钟",
            "阅读 4 分钟",
        ]
        for phrase in compression_anchors:
            assert phrase not in PROMPT

        assert "系统理解今天的重要变化" in PROMPT
        assert "深度整理" in PROMPT
        assert "重点判断" in PROMPT

    def test_avoids_decorative_banner_lines(self):
        assert "▁▁" not in PROMPT
        assert "▔▔" not in PROMPT
