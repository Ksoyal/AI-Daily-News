import logging
import sys
import feedparser
import requests
from datetime import datetime, timedelta, timezone

from config import RSS_SOURCES, EXCLUDE_KEYWORDS, MAX_ENTRIES, FETCH_TIMEOUT, FETCH_USER_AGENT

logger = logging.getLogger(__name__)


def _parse_published(entry):
    """Extract UTC datetime from a feed entry, trying published_parsed then updated_parsed."""
    for attr in ("published_parsed", "updated_parsed"):
        struct = getattr(entry, attr, None)
        if struct:
            return datetime(*struct[:6], tzinfo=timezone.utc)
    return None


def fetch_news():
    """Fetch news from configured RSS sources and return filtered entries.

    Returns a list of dicts with keys: title, link, source, published (ISO str).
    Each source failure is logged but does not block other sources.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    entries = []

    for src in RSS_SOURCES:
        try:
            resp = requests.get(src["url"], timeout=FETCH_TIMEOUT,
                                headers={"User-Agent": FETCH_USER_AGENT})
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch {src['name']} ({src['url']}): {e}")
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
