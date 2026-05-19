import logging
import sys
import feedparser
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

RSS_SOURCES = [
    {"name": "纽约时报中文", "url": "https://cn.nytimes.com/rss/"},
    {"name": "36氪",     "url": "https://36kr.com/feed"},
    {"name": "BBC中文",  "url": "https://www.bbc.com/zhongwen/simp/index.xml"},
    {"name": "FT中文网",  "url": "https://www.ftchinese.com/rss/news"},
    {"name": "量子位",    "url": "https://www.qbitai.com/rss"},
]

EXCLUDE_KEYWORDS = ["娱乐", "明星", "八卦", "体育"]

MAX_ENTRIES = 30


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
    Filters applied:
      1. Published within the last 24 hours (UTC).
      2. Title contains none of the exclude keywords.
      3. Capped at 30 entries, newest first.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    entries = []

    for src in RSS_SOURCES:
        feed = feedparser.parse(src["url"])
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

    entries.sort(key=lambda e: e["published"], reverse=True)
    return entries[:MAX_ENTRIES]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    news = fetch_news()
    logger.info(f"共获取 {len(news)} 条新闻:")
    for i, item in enumerate(news, 1):
        logger.info(f"{i}. [{item['source']}] {item['title']}")
        logger.info(f"   {item['link']}")
