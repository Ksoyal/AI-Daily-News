import logging
import re
import sys
import time
from datetime import datetime
from openai import OpenAI, RateLimitError, APIConnectionError, InternalServerError
from topic_taxonomy import normalize_tags, topic_prompt

from config import (AI_BASE_URL, AI_API_KEY, AI_MODEL, AI_TEMPERATURE, AI_TIMEOUT,
                    AI_MAX_TOKENS, AI_MAX_INPUT_CHARS, AI_MIN_PER_SOURCE, AI_SYSTEM_PROMPT,
                    AI_RETRY_DELAYS, REPORT_TZ)

logger = logging.getLogger(__name__)

WEEKDAY_NAMES = "一二三四五六日"


def _format_age(published):
    """Render '发布：约N小时前' (or 约N天前 beyond 48h) from an ISO-8601 timestamp.

    Returns None when the timestamp is missing or unparseable, so the caller
    can omit the line silently.
    """
    if not published:
        return None
    try:
        delta = datetime.now(REPORT_TZ) - datetime.fromisoformat(published)
    except (ValueError, TypeError):
        return None
    hours = max(0, round(delta.total_seconds() / 3600))
    if hours >= 48:
        return f"发布：约{round(hours / 24)}天前"
    return f"发布：约{hours}小时前"


def _format_news_item(index, entry, include_summary=True):
    lines = [
        f"[{index}] 标题：{entry['title']}",
        f"链接：{entry['link']}",
        f"来源：{entry['source']}",
    ]
    age = _format_age(entry.get("published"))
    if age:
        lines.append(age)
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
    tags, rejected = normalize_tags([
        t.strip() for t in tags_raw.replace("，", ",").split(",") if t.strip()
    ])
    if rejected:
        logger.warning("Unapproved core topics pending taxonomy review: %r", rejected)

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


def generate_report(news_list, previous_context=None):
    """Send news list to LLM and return structured daily report.

    Args:
        news_list: entries from fetcher.fetch_news()
        previous_context: optional summary of yesterday's report; when given,
            the model is asked to skip already-covered events and report deltas

    Returns:
        dict with keys: headline (str), tags (list[str]), content (str — markdown body)
    """
    if not news_list:
        raise ValueError(
            "news_list is empty — refusing to generate a report from nothing "
            "(the model would hallucinate content)"
        )

    if not AI_API_KEY:
        raise ValueError("AI_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY must be set")

    client = OpenAI(
        base_url=AI_BASE_URL,
        api_key=AI_API_KEY,
        timeout=AI_TIMEOUT,
        max_retries=0,
    )

    news_text = _build_news_text(news_list)

    # Ground the model in the current date so it doesn't guess from training data
    now = datetime.now(REPORT_TZ)
    date_line = f"今天是 {now.year}年{now.month}月{now.day}日（星期{WEEKDAY_NAMES[now.weekday()]}）。"

    # Optional hook: the previous report's summary, so today's report covers
    # deltas only. Worded as 上期 (not 昨日) — after a failed run the latest
    # report can be several days old, and its actual date is in the context.
    context_block = ""
    if previous_context and previous_context.strip():
        context_block = (
            "【上期日报概要】\n"
            f"{previous_context.strip()}\n"
            "（上期已覆盖且无新进展的事件请省略；有进展只写增量并注明与上期的差异。）\n\n"
        )

    user_message = (
        f"{date_line}\n\n"
        f"{context_block}"
        f"以下是最近的新闻列表（每条已标注发布时效），请生成日报：\n\n{news_text}"
    )

    # Retry only generation, before any Notion write or push notification.
    # Longer, bounded waits give overloaded providers time to recover while
    # preserving the four-request budget (SDK retries remain disabled).
    max_retries = len(AI_RETRY_DELAYS)
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": AI_SYSTEM_PROMPT + "\n\n" + topic_prompt()},
                    {"role": "user", "content": user_message},
                ],
                temperature=AI_TEMPERATURE,
                max_tokens=AI_MAX_TOKENS,
            )
            break  # success → stop retrying
        except (RateLimitError, APIConnectionError, InternalServerError) as e:
            if attempt < max_retries:
                delay = AI_RETRY_DELAYS[attempt]
                logger.warning(f"AI API {type(e).__name__}, retrying in {delay}s "
                               f"(attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise

    if not resp.choices:
        raise RuntimeError(
            f"AI model returned no choices (model={resp.model}, usage={resp.usage}) — "
            "the request may have been blocked by a safety policy or the service overloaded"
        )

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
