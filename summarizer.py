import logging
import re
import sys
import time
from openai import OpenAI, RateLimitError, APIConnectionError, InternalServerError

from config import (AI_BASE_URL, AI_API_KEY, AI_MODEL, AI_TEMPERATURE, AI_TIMEOUT,
                    AI_MAX_TOKENS, AI_MAX_INPUT_CHARS, AI_MIN_PER_SOURCE, AI_SYSTEM_PROMPT)

logger = logging.getLogger(__name__)


def _format_news_item(index, entry, include_summary=True):
    lines = [
        f"[{index}] 标题：{entry['title']}",
        f"链接：{entry['link']}",
        f"来源：{entry['source']}",
    ]
    summary = (entry.get("summary") or "").strip()
    if include_summary and summary:
        lines.append(f"摘要：{summary}")
    return "\n".join(lines) + "\n\n"


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
            line = _format_news_item(len(selected) + 1, entry)
            if budget - len(line) < 0:
                # Check if this source still hasn't met the floor
                if idx < AI_MIN_PER_SOURCE and idx < len(src_entries):
                    line_without_summary = _format_news_item(len(selected) + 1, entry, include_summary=False)
                    if budget - len(line_without_summary) >= 0:
                        selected.append(line_without_summary)
                        budget -= len(line_without_summary)
                    else:
                        # Truncate the title to fit.
                        base_len = len(
                            f"[{len(selected) + 1}] 标题：\n"
                            f"链接：{entry['link']}\n"
                            f"来源：{entry['source']}\n\n"
                        )
                        max_title_len = budget - base_len - 3
                        if max_title_len > 10:
                            truncated_title = entry['title'][:max_title_len] + "..."
                            line = (
                                f"[{len(selected) + 1}] 标题：{truncated_title}\n"
                                f"链接：{entry['link']}\n"
                                f"来源：{entry['source']}\n\n"
                            )
                            selected.append(line)
                            budget -= len(line)
                    if budget < 0:
                        logger.warning("AI input budget exceeded while preserving per-source floor")
                        budget = 0
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


def _parse_report(raw):
    """Parse the structured LLM output into headline, tags, and markdown body."""
    raw = (raw or "").strip()
    if not raw:
        raise RuntimeError("AI model returned an empty report body")

    headline_match = re.search(r'^HEADLINE:\s*(.+)$', raw, re.MULTILINE)
    tags_match = re.search(r'^TAGS:\s*(.+)$', raw, re.MULTILINE)

    headline = headline_match.group(1).strip() if headline_match else "AI 晨报"
    tags_raw = tags_match.group(1).strip() if tags_match else ""
    tags = [t.strip() for t in tags_raw.replace("，", ",").split(",") if t.strip()][:3]

    body_match = re.search(r'^---\s*\n(.+)$', raw, re.MULTILINE | re.DOTALL)
    content = body_match.group(1).strip() if body_match else raw
    if not content or content == raw and re.fullmatch(
        r"(?s)\s*HEADLINE:\s*.+\nTAGS:\s*.*\n---\s*", raw
    ):
        raise RuntimeError("AI model returned an empty report body")

    return {
        "headline": headline,
        "tags": tags,
        "content": content,
    }


def generate_report(news_list):
    """Send news list to LLM and return structured daily report.

    Returns:
        dict with keys: headline (str), tags (list[str]), content (str — markdown body)
    """
    if not AI_API_KEY:
        raise ValueError("AI_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY must be set")

    client = OpenAI(
        base_url=AI_BASE_URL,
        api_key=AI_API_KEY,
        timeout=AI_TIMEOUT,
    )

    news_text = _build_news_text(news_list)

    # Retry on transient errors (rate limit, connection, server errors)
    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": AI_SYSTEM_PROMPT},
                    {"role": "user", "content": f"以下是今日新闻列表，请生成日报：\n\n{news_text}"},
                ],
                temperature=AI_TEMPERATURE,
                max_tokens=AI_MAX_TOKENS,
            )
            break  # success → stop retrying
        except (RateLimitError, APIConnectionError, InternalServerError) as e:
            if attempt < max_retries:
                delay = 2 ** (attempt + 3)  # 8, 16, 32 seconds
                logger.warning(f"AI API {type(e).__name__}, retrying in {delay}s "
                               f"(attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise

    choice = resp.choices[0]
    finish_reason = choice.finish_reason
    raw = choice.message.content

    logger.info(f"AI response: model={resp.model}, finish_reason={finish_reason}, "
                f"content_length={len(raw) if raw else 0}, "
                f"usage={resp.usage}")

    if raw is None or not raw.strip():
        logger.error(f"Empty AI response. finish_reason={finish_reason}, "
                     f"message={choice.message}")
        raise RuntimeError(
            f"AI model returned empty content (finish_reason={finish_reason}). "
            "The model may be overloaded — try switching to a different model."
        )

    report = _parse_report(raw)
    logger.info(f"Parsed: headline='{report['headline'][:40]}...', tags={report['tags']}")

    return report


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
