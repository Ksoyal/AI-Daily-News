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
    STALE_WINDOW_HOURS, STALE_MAX_ENTRIES,
)

logger = logging.getLogger(__name__)

# Char-bigram Jaccard similarity at or above this means "same story".
# Deliberately near-exact: short, templated Chinese headlines score absurdly
# high on mere phrasing (加息 vs 降息 = 0.69, 收涨 vs 收跌 = 0.80), so anything
# below ~0.9 silently drops real news. Editorial merging of differently-worded
# same-event coverage is the model's job (the prompt asks it to merge and cite
# all sources), not this filter's.
_DEDUP_JACCARD = 0.9

# A challenger this much fresher than the incumbent wins the dedup outright,
# so stale-fallback copies can't shadow today's coverage via longer summaries.
_DEDUP_FRESHNESS_GAP = timedelta(hours=24)


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


def _normalize_title(title):
    """Lowercase and strip punctuation/whitespace for fuzzy title comparison."""
    return re.sub(r"[\W_]+", "", str(title).lower())


def _title_bigrams(title):
    """Character bigram set of a normalized title (whole string if shorter than 2)."""
    normalized = _normalize_title(title)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[i:i + 2] for i in range(len(normalized) - 1)}


def _beats(challenger, incumbent):
    """Dedup winner rule: a much fresher entry wins outright; otherwise the
    longer summary wins (tie keeps the incumbent, i.e. the earlier source)."""
    try:
        gap = (datetime.fromisoformat(challenger["published"])
               - datetime.fromisoformat(incumbent["published"]))
    except (KeyError, ValueError):
        gap = timedelta(0)
    if abs(gap) > _DEDUP_FRESHNESS_GAP:
        return gap > timedelta(0)
    return len(challenger.get("summary", "")) > len(incumbent.get("summary", ""))


def _dedup_entries(entries):
    """Merge near-identical stories (same wire copy / double-posts) across sources.

    Titles whose char-bigram Jaccard similarity is >= _DEDUP_JACCARD count as
    the same story; the winner is picked by _beats(). O(n^2), fine at n <= ~150.
    """
    kept = []
    kept_bigrams = []
    for entry in entries:
        bigrams = _title_bigrams(entry["title"])
        match_idx = None
        for i, existing in enumerate(kept_bigrams):
            if not bigrams or not existing:
                continue
            jaccard = len(bigrams & existing) / len(bigrams | existing)
            if jaccard >= _DEDUP_JACCARD:
                match_idx = i
                break
        if match_idx is None:
            kept.append(entry)
            kept_bigrams.append(bigrams)
            continue
        incumbent = kept[match_idx]
        if _beats(entry, incumbent):
            logger.info(f"Dedup: [{incumbent['source']}] {incumbent['title']!r} "
                        f"replaced by [{entry['source']}] {entry['title']!r}")
            kept[match_idx] = entry
            kept_bigrams[match_idx] = bigrams
        else:
            logger.info(f"Dedup: [{entry['source']}] {entry['title']!r} dropped as "
                        f"duplicate of [{incumbent['source']}] {incumbent['title']!r}")
    return kept


def fetch_news():
    """Fetch news from configured RSS sources and return filtered entries.

    Per source: keep entries from the last 24h; if a source has none but has
    entries within STALE_WINDOW_HOURS, fall back to the newest STALE_MAX_ENTRIES
    of those (these rescued entries are exempt from the MAX_ENTRIES tail cut —
    being oldest, they would otherwise always be truncated away first).
    Entries whose title contains an EXCLUDE_KEYWORDS keyword, or whose link
    contains a per-source "exclude_link_patterns" substring, are dropped.
    Near-identical stories across sources (char-bigram Jaccard >= 0.9 on
    normalized titles) are merged via _beats().

    Returns a list of dicts with keys: title, link, source, published (ISO str),
    summary — newest first, truncated to MAX_ENTRIES.
    Each source failure is logged but does not block other sources.
    """
    now = datetime.now(timezone.utc)
    fresh_cutoff = now - timedelta(hours=24)
    stale_cutoff = now - timedelta(hours=STALE_WINDOW_HOURS)
    entries = []
    rescued_ids = set()

    for src in RSS_SOURCES:
        # Support fallback URLs: try each in order until one succeeds
        urls = src.get("urls") or ()
        if not urls:
            logger.warning(f"{src.get('name', '?')}: no 'urls' configured, skipping source")
            continue
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

        link_patterns = src.get("exclude_link_patterns") or ()
        fresh = []
        stale = []
        for entry in feed.entries:
            published = _parse_published(entry)
            if published is None:
                continue
            if published < stale_cutoff:
                continue

            title = entry.get("title", "")
            if any(kw in title for kw in EXCLUDE_KEYWORDS):
                continue

            link = entry.get("link", "")
            if any(pattern in link for pattern in link_patterns):
                continue

            bucket = fresh if published >= fresh_cutoff else stale
            bucket.append({
                "title": title,
                "link": link,
                "source": src["name"],
                "published": published.isoformat(),
                "summary": _entry_summary(entry),
            })

        if fresh:
            accepted = fresh
        else:
            # Stale-source fallback: feed is alive but everything is >24h old
            # (common on weekends) — keep a few of the newest entries anyway.
            stale.sort(key=lambda e: e["published"], reverse=True)
            accepted = stale[:STALE_MAX_ENTRIES]
            rescued_ids.update(map(id, accepted))
            if accepted:
                logger.info(f"{src['name']}: no entries within 24h, keeping "
                            f"{len(accepted)} within {STALE_WINDOW_HOURS}h instead")

        entries.extend(accepted)
        logger.info(f"{src['name']}: {len(accepted)} entries accepted")

    entries = _dedup_entries(entries)
    # Rescued (stale-fallback) entries are exempt from the tail cut: sorted by
    # recency they are always last, so a plain [:MAX_ENTRIES] would structurally
    # defeat the fallback on any busy day.
    rescued = [e for e in entries if id(e) in rescued_ids]
    fresh_entries = [e for e in entries if id(e) not in rescued_ids]
    fresh_entries.sort(key=lambda e: e["published"], reverse=True)
    entries = fresh_entries[:max(0, MAX_ENTRIES - len(rescued))] + rescued
    entries.sort(key=lambda e: e["published"], reverse=True)
    return entries


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    news = fetch_news()
    logger.info(f"Total: {len(news)} entries")
    for i, item in enumerate(news, 1):
        logger.info(f"{i}. [{item['source']}] {item['title']}")
        logger.info(f"   {item['link']}")
