import logging
import html
import re
import sys
import feedparser
import requests
from datetime import datetime, timedelta, timezone

from config import (
    RSS_SOURCES, EXCLUDE_KEYWORDS, MAX_ENTRIES, FETCH_TIMEOUT,
    FETCH_USER_AGENT, RSS_SUMMARY_MAX_CHARS,
)

logger = logging.getLogger(__name__)


def _parse_published(entry):
    """Extract UTC datetime from a feed entry, trying published_parsed then updated_parsed."""
    for attr in ("published_parsed", "updated_parsed"):
        struct = getattr(entry, attr, None)
        if struct:
            return datetime(*struct[:6], tzinfo=timezone.utc)
    return None


def _clean_text(value):
    """Convert RSS HTML fragments to compact plain text."""
    if not value:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > RSS_SUMMARY_MAX_CHARS:
        return text[:RSS_SUMMARY_MAX_CHARS].rstrip() + "..."
    return text


def _entry_summary(entry):
    """Extract a plain-text summary from common RSS/Atom fields."""
    for key in ("summary", "description", "subtitle"):
        cleaned = _clean_text(entry.get(key))
        if cleaned:
            return cleaned

    summary_detail = entry.get("summary_detail")
    if isinstance(summary_detail, dict):
        cleaned = _clean_text(summary_detail.get("value"))
        if cleaned:
            return cleaned

    content_items = entry.get("content") or []
    for item in content_items:
        value = item.get("value") if isinstance(item, dict) else getattr(item, "value", "")
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned

    return ""


def _feed_has_entries(feed):
    return bool(getattr(feed, "entries", None))


def fetch_news():
    """Fetch news from configured RSS sources and return filtered entries.

    Returns a list of dicts with keys: title, link, source, published (ISO str).
    Each source failure is logged but does not block other sources.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    entries = []

    for src in RSS_SOURCES:
        # Support fallback URLs: try each in order until one succeeds
        urls = src.get("urls") or [src["url"]]
        feed = None
        last_error = None
        for url in urls:
            try:
                resp = requests.get(url, timeout=FETCH_TIMEOUT,
                                    headers={"User-Agent": FETCH_USER_AGENT})
                resp.raise_for_status()
                parsed_feed = feedparser.parse(resp.content)
                if not _feed_has_entries(parsed_feed):
                    last_error = ValueError("feed parsed but contained no entries")
                    continue
                feed = parsed_feed
                if url != urls[0]:
                    logger.info(f"{src['name']}: fell back to {url}")
                break
            except requests.RequestException as e:
                last_error = e
                continue
        if feed is None:
            logger.warning(f"Failed to fetch {src['name']} (tried {len(urls)} URL(s), last: {last_error})")
            continue

        source_count = 0
        for entry in feed.entries:
            published = _parse_published(entry)
            if published is None:
                continue
            if published < cutoff:
                continue

            title = entry.get("title", "")
            if any(kw in title for kw in EXCLUDE_KEYWORDS):
                continue

            entries.append({
                "title": title,
                "link": entry.get("link", ""),
                "source": src["name"],
                "published": published.isoformat(),
                "summary": _entry_summary(entry),
            })
            source_count += 1

        logger.info(f"{src['name']}: {source_count} entries accepted")

    entries.sort(key=lambda e: e["published"], reverse=True)
    return entries[:MAX_ENTRIES]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    news = fetch_news()
    logger.info(f"Total: {len(news)} entries")
    for i, item in enumerate(news, 1):
        logger.info(f"{i}. [{item['source']}] {item['title']}")
        logger.info(f"   {item['link']}")
