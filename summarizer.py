import logging
import os
import re
import sys
from openai import OpenAI
from dotenv import load_dotenv

from config import AI_MODEL, AI_TEMPERATURE, AI_TIMEOUT, AI_MAX_INPUT_CHARS, AI_MIN_PER_SOURCE

load_dotenv()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个资深的全球资讯主编。请将输入的新闻列表进行去重、合并同类新闻，并严格按照以下格式输出高质量的日报。

【输出格式】
严格遵守以下格式，只输出正文，不要任何额外说明：

HEADLINE: <今天最重要的一条新闻标题，不超过30字，作为日报标题和头版头条>
TAGS: <标签1>, <标签2>, <标签3>

---

## 🌟 今日要闻
（用 3-5 句话概述今天全球最重要的 1-3 件事，让读者快速把握今日脉络）

## 🌍 全球时政
- **[新闻标题]**：2-3 句话摘要，包含事件要点、关键背景和潜在影响。（来源：XXX）

## 💻 科技与 AI
- **[新闻标题]**：2-3 句话摘要，尽量包含技术细节、行业影响或数据。（来源：XXX）

## 📈 财经与市场
- **[新闻标题]**：2-3 句话摘要，尽量包含具体数据、市场反应或趋势分析。（来源：XXX）

## 🔥 社会热点
- **[新闻标题]**：2-3 句话摘要，包含事件背景和社会反响。（来源：XXX）

【总体原则】
- 去重：同一事件的报道合并为一条，综合多个来源的信息
- 深度：每条新闻写 2-3 句话，包含关键事实、数据、影响或背景
- 可读：让读者不用点开原文就能理解事件全貌
- 语言：专业但不枯燥，类似财新/端传媒的编辑风格
- 标签：TAGS 提取 2-3 个今日新闻最核心的话题关键词，如"AI治理"、"中美关系"、"资本市场"
- 板块内新闻不要超过 8 条，超出则只保留最重要的"""


def _build_news_text(news_list):
    """Build the news text for the LLM prompt, respecting the token budget.

    Uses a two-pass approach:
      1. Take an even share from each source (round-robin).
      2. If budget remains, fill remaining slots in original order.

    Returns the formatted text and a count of entries included.
    """
    # Group entries by source
    by_source = {}
    for item in news_list:
        by_source.setdefault(item["source"], []).append(item)

    source_names = list(by_source.keys())
    indices = {s: 0 for s in source_names}
    selected = []

    # Round-robin: pick one from each source until budget exhausted or all picked
    budget = AI_MAX_INPUT_CHARS
    while True:
        added = False
        for src in source_names:
            src_entries = by_source[src]
            idx = indices[src]
            if idx >= len(src_entries):
                continue
            entry = src_entries[idx]
            line = f"[{len(selected) + 1}] 标题：{entry['title']}\n链接：{entry['link']}\n来源：{entry['source']}\n\n"
            if budget - len(line) < 0:
                # Check if this source still hasn't met the floor
                if idx < AI_MIN_PER_SOURCE and idx < len(src_entries):
                    # Truncate the title to fit
                    max_title_len = budget - len(f"[{len(selected) + 1}] 标题：\n链接：{entry['link']}\n来源：{entry['source']}\n\n")
                    if max_title_len > 10:
                        truncated_title = entry['title'][:max_title_len] + "..."
                        line = f"[{len(selected) + 1}] 标题：{truncated_title}\n链接：{entry['link']}\n来源：{entry['source']}\n\n"
                        selected.append(line)
                        budget -= len(line)
                    indices[src] = idx + 1
                    added = True
                continue
            selected.append(line)
            budget -= len(line)
            indices[src] = idx + 1
            added = True
        if not added:
            break

    news_text = "".join(selected).rstrip()
    logger.info(f"Token budget: {AI_MAX_INPUT_CHARS - budget}/{AI_MAX_INPUT_CHARS} chars, "
                f"{len(selected)} entries included (from {len(news_list)} total)")
    return news_text


def generate_report(news_list):
    """Send news list to LLM and return structured daily report.

    Returns:
        dict with keys: headline (str), tags (list[str]), content (str — markdown body)
    """
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        timeout=AI_TIMEOUT,
    )

    news_text = _build_news_text(news_list)

    resp = client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"以下是今日新闻列表，请生成日报：\n\n{news_text}"},
        ],
        temperature=AI_TEMPERATURE,
    )

    choice = resp.choices[0]
    finish_reason = choice.finish_reason
    raw = choice.message.content

    logger.info(f"OpenRouter response: model={resp.model}, finish_reason={finish_reason}, "
                f"content_length={len(raw) if raw else 0}, "
                f"usage={resp.usage}")

    if raw is None:
        logger.error(f"Empty content from OpenRouter. finish_reason={finish_reason}, "
                     f"message={choice.message}")
        raise RuntimeError(
            f"OpenRouter returned empty content (finish_reason={finish_reason}). "
            "The free model may be overloaded — try switching to a paid model."
        )

    # Parse structured output: HEADLINE, TAGS, ---, then body
    headline_match = re.search(r'^HEADLINE:\s*(.+)$', raw, re.MULTILINE)
    tags_match = re.search(r'^TAGS:\s*(.+)$', raw, re.MULTILINE)

    headline = headline_match.group(1).strip() if headline_match else "AI 晨报"
    tags_raw = tags_match.group(1).strip() if tags_match else ""
    tags = [t.strip() for t in tags_raw.replace("，", ",").split(",") if t.strip()][:3]

    # Extract body after --- separator
    body_match = re.search(r'^---\s*\n(.+)$', raw, re.MULTILINE | re.DOTALL)
    content = body_match.group(1).strip() if body_match else raw

    logger.info(f"Parsed: headline='{headline[:40]}...', tags={tags}")

    return {
        "headline": headline,
        "tags": tags,
        "content": content,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Fake data for testing the prompt output
    fake_news = [
        {
            "title": "联合国通过首个全球AI治理决议",
            "link": "https://example.com/ai-governance",
            "source": "联合早报",
        },
        {
            "title": "OpenAI发布GPT-6，推理能力再次突破",
            "link": "https://example.com/gpt6",
            "source": "36氪",
        },
        {
            "title": "美股三大指数集体收涨，科技股领涨",
            "link": "https://example.com/us-stock",
            "source": "BBC中文",
        },
        {
            "title": "北京持续高温，多地气温突破40℃",
            "link": "https://example.com/heatwave",
            "source": "联合早报",
        },
        {
            "title": "欧盟通过新AI法案，严格监管高风险应用",
            "link": "https://example.com/eu-ai-act",
            "source": "BBC中文",
        },
    ]

    report = generate_report(fake_news)
    print(f"HEADLINE: {report['headline']}")
    print(f"TAGS: {report['tags']}")
    print(f"---")
    print(report['content'])
