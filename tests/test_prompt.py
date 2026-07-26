import re
from pathlib import Path


PROMPT = (Path(__file__).resolve().parents[1] / "prompt.txt").read_text(encoding="utf-8")
LINES = PROMPT.splitlines()
H2 = {line.strip() for line in LINES if line.startswith("## ")}
H3 = {line.strip() for line in LINES if line.startswith("### ")}


class TestMachineParseContract:
    def test_headline_tags_divider_order(self):
        assert "HEADLINE:" in PROMPT
        assert "TAGS:" in PROMPT
        tags_idx = PROMPT.index("TAGS:")
        assert PROMPT.index("HEADLINE:") < tags_idx
        # A "---" divider must follow the TAGS line (earlier "---" mentions in
        # the syntax rules section don't count)
        assert PROMPT.index("---", tags_idx) > tags_idx

    def test_keeps_header_and_footer(self):
        assert "## AI 晨报" in PROMPT
        assert "AI 晨报 · 每天 8:00 · 多源整理 · 审慎判断" in PROMPT


class TestStructuralContract:
    def test_numbered_sections_are_h2(self):
        required = [
            "## 01 今日主线",
            "## 02 必读",
            "## 03 深读一条",
            "## 04 分区速览",
            "## 05 接下来关注",
        ]
        for section in required:
            assert section in H2, f"missing H2 section: {section}"
        # No leftover H3 numbered sections (the old inverted layout)
        assert not any(line.startswith("### 0") for line in LINES)

    def test_subsections_are_h3(self):
        required = ["### 全球时政", "### 科技与 AI", "### 财经与市场", "### 值得注意"]
        for sub in required:
            assert sub in H3, f"missing H3 sub-section: {sub}"
        # And they must not still be H2 (the old inverted layout)
        for sub in ["## 全球时政", "## 科技与 AI", "## 财经与市场", "## 值得注意"]:
            assert sub not in H2

    def test_markdown_syntax_section_before_output_format(self):
        assert "【排版语法】" in PROMPT
        assert "【输出格式】" in PROMPT
        assert PROMPT.index("【排版语法】") < PROMPT.index("【输出格式】")
        # Forbidden syntaxes are named explicitly
        assert "1. 2. 3." in PROMPT
        assert "斜体" in PROMPT
        assert "表格" in PROMPT
        assert "```" in PROMPT

    def test_no_bracketed_placeholders(self):
        assert "**[标题]**" not in PROMPT
        assert "**[观察点]**" not in PROMPT
        # Explicit instruction that placeholders are notation, not literal output
        assert "占位" in PROMPT
        assert "方括号" in PROMPT

    def test_subsection_exclusivity_and_omission_rules(self):
        assert "不得在这里重复出现" in PROMPT
        assert "最多 3 条" in PROMPT
        assert "整个子板块直接省略" in PROMPT
        # The old 时政-only omission sentence must be gone
        assert "没有足够重要的时政新闻则省略" not in PROMPT

    def test_quote_is_distinct_takeaway(self):
        assert "一句话结论" in PROMPT
        assert "重复开头引语" in PROMPT

    def test_deep_read_cites_source_exactly_once(self):
        assert "第一段末尾" in PROMPT
        assert "整节只标注这一次" in PROMPT


class TestEditorialGuards:
    def test_date_anchoring(self):
        assert "日期锚定" in PROMPT
        assert "星期" in PROMPT
        assert "训练记忆" in PROMPT
        assert "休市" in PROMPT  # mind weekends / market closures

    def test_length_budget_and_trim_priority(self):
        assert "2000-2800 字" in PROMPT
        assert "先减少分区速览" in PROMPT
        assert "来源标注" in PROMPT

    def test_yesterday_continuity(self):
        assert "【上期日报概要】" in PROMPT
        assert "较上期" in PROMPT

    def test_input_is_sample_not_ranking(self):
        assert "样本" in PROMPT
        assert "顺序不代表重要性" in PROMPT
        assert "不等于不重要" in PROMPT

    def test_anti_hallucination_rules(self):
        assert "没有摘要" in PROMPT  # title-only items: one factual sentence max
        assert "历史价格" in PROMPT  # no background data from memory
        assert "全称" in PROMPT  # no invented expansions for abbreviations
        assert "逐字" in PROMPT  # verbatim quotes / verbatim source field
        assert "据路透社报道" in PROMPT  # quoted media are not sources
        assert "上下游" in PROMPT  # causal/industry-chain claims must come from input
        assert "口径" in PROMPT  # reconcile conflicting monetary figures

    def test_source_whitelist_line(self):
        idx = PROMPT.index("来源白名单")
        whitelist_line = PROMPT[idx:PROMPT.index("\n", idx)]
        # The whitelist must stay verbatim-consistent with config.RSS_SOURCES:
        # the prompt tells the model to copy these names exactly.
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import config
        config_names = [src["name"] for src in config.RSS_SOURCES]
        for name in config_names:
            assert name in whitelist_line, f"whitelist missing source: {name}"
        listed = whitelist_line.split("——", 1)[-1].rstrip("。")
        for name in re.split(r"[、，,]\s*", listed):
            name = name.strip()
            if name:
                assert name in config_names, f"whitelist has unknown source: {name}"

    def test_linked_source_citation_format(self):
        assert "（来源：[XXX](原文链接)）" in PROMPT
        assert "（来源：[A](链接A)、[B](链接B)）" in PROMPT

    def test_insight_calibration(self):
        # Forbidden insight openers are named
        assert "这标志着" in PROMPT
        assert "这代表" in PROMPT
        # Bold at most one key phrase, never a whole sentence
        assert "加粗一个关键短语" in PROMPT
        # Evidence-matched hedging
        assert "迹象显示" in PROMPT
        # Slow news days: no manufactured significance
        assert "制造重要性" in PROMPT

    def test_judgment_cliche_budget(self):
        assert "不是A而是B" in PROMPT
        assert "最多出现一次" in PROMPT


class TestLegacyEditorialContract:
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

    def test_avoids_decorative_banner_lines(self):
        assert "▁▁" not in PROMPT
        assert "▔▔" not in PROMPT
