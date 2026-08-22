import logging
import os
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _env(name, default=None):
    """Return a stripped environment value, treating empty strings as unset."""
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_int(name, default):
    """Parse an int env var, falling back to default on malformed values."""
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} is not a valid integer, using default {default}")
        return default


def _env_float(name, default):
    """Parse a float env var, falling back to default on malformed values."""
    raw = _env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} is not a valid number, using default {default}")
        return default


# Project root (where config.py lives)
PROJECT_DIR = Path(__file__).resolve().parent

# The pipeline's definition of "today" (page dates, idempotency check).
# Deliberately NOT env-configurable: daily_run_guard.py hardcodes UTC+8 for the
# CI duplicate check, and the two must agree or idempotency breaks across days.
REPORT_TZ = timezone(timedelta(hours=8))

# ── RSS ──────────────────────────────────────────
RSS_SOURCES = [
    # Support fallback URLs: each source has a list of urls to try in order.
    # The first URL that returns 200 is used; subsequent attempts log the failure and move on.
    # Optional "exclude_link_patterns": entries whose link contains any of these
    # substrings are dropped (used to skip non-news columns within a feed).
    {"name": "纽约时报中文", "urls": ["https://cn.nytimes.com/rss/"]},
    {"name": "36氪",         "urls": ["https://36kr.com/feed"]},
    {"name": "BBC中文",      "urls": ["https://www.bbc.com/zhongwen/simp/index.xml"]},
    {"name": "FT中文网",      "urls": [
        "https://www.ftchinese.com/rss/news",
    ]},
    {"name": "量子位",        "urls": ["https://www.qbitai.com/rss"]},
    {"name": "德国之声中文",  "urls": ["https://rss.dw.com/rdf/rss-chi-all"]},
    {"name": "爱范儿",        "urls": ["https://www.ifanr.com/feed"]},
    {"name": "端传媒",        "urls": ["https://theinitium.com/feed/"],
     # Feed mixes news with comics/podcasts; those columns carry link slugs.
     # Essays/features have plain date-slug links and cannot be filtered by link.
     "exclude_link_patterns": ["opinion-cartoon", "initium-audio"]},
    {"name": "共同社中文",    "urls": ["https://china.kyodonews.net/rss/news.xml"]},
    {"name": "RFI中文",      "urls": ["https://www.rfi.fr/cn/rss"]},
    {"name": "中央社财经",    "urls": ["https://feeds.feedburner.com/rsscna/finance"]},
    {"name": "联合早报",      "urls": ["https://plink.anyfeeder.com/zaobao/realtime/world"]},
]

EXCLUDE_KEYWORDS = [
    "娱乐", "明星", "八卦", "体育", "票房", "世界杯",
    # Lottery-draw noise from wire-service feeds (中央社财经 carries these)
    "开奖", "開獎", "威力彩", "統一發票",
]

MAX_ENTRIES = _env_int("MAX_ENTRIES", 100)
RSS_SUMMARY_MAX_CHARS = _env_int("RSS_SUMMARY_MAX_CHARS", 600)

# Stale-source fallback: if a source has no entries within 24h but does have
# entries within STALE_WINDOW_HOURS, keep the newest STALE_MAX_ENTRIES of those
# (weekend feeds often fall entirely outside the 24h window).
STALE_WINDOW_HOURS = _env_int("STALE_WINDOW_HOURS", 72)
STALE_MAX_ENTRIES = _env_int("STALE_MAX_ENTRIES", 3)

FETCH_TIMEOUT = _env_int("FETCH_TIMEOUT", 30)
FETCH_USER_AGENT = _env(
    "FETCH_USER_AGENT",
    "Mozilla/5.0 (compatible; AI-Daily-News/1.0; +https://github.com/Ksoyal/AI-Daily-News)"
)

# ── AI ───────────────────────────────────────────
# Provider-agnostic: change AI_BASE_URL + AI_MODEL + AI_API_KEY to switch
# Google AI Studio (OpenAI-compatible endpoint)
# Get key at https://aistudio.google.com/apikey
# OpenRouter: base_url="https://openrouter.ai/api/v1", model="provider/model"
AI_BASE_URL = _env("AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
AI_API_KEY = _env("AI_API_KEY") or _env("GEMINI_API_KEY") or _env("OPENROUTER_API_KEY", "")
AI_MODEL = _env("AI_MODEL", "gemini-3.7-flash")
AI_TEMPERATURE = _env_float("AI_TEMPERATURE", 0.5)
AI_TIMEOUT = _env_int("AI_TIMEOUT", 180)
AI_MAX_TOKENS = _env_int("AI_MAX_TOKENS", 16384)
AI_MAX_INPUT_CHARS = _env_int("AI_MAX_INPUT_CHARS", 32000)
# Per-source floor: when truncating for token budget, try to keep at least
# this many entries from each source that has entries.
AI_MIN_PER_SOURCE = 2

# ── AI Prompt ─────────────────────────────────────
# Priority: AI_SYSTEM_PROMPT (inline) > AI_PROMPT_FILE (path) > prompt.txt (default)
def _load_prompt():
    """Load the system prompt with env-var override support."""
    # 1. Inline env var wins
    inline = _env("AI_SYSTEM_PROMPT")
    if inline:
        return inline

    # 2. Custom file path
    file_path = _env("AI_PROMPT_FILE")
    if file_path and Path(file_path).exists():
        return Path(file_path).read_text(encoding="utf-8")

    # 3. Default prompt.txt in project root
    default = PROJECT_DIR / "prompt.txt"
    if default.exists():
        return default.read_text(encoding="utf-8")

    # 4. Built-in fallback (minimal)
    return _FALLBACK_PROMPT


_FALLBACK_PROMPT = """你是一位资深编辑，请根据输入的新闻列表生成高质量中文晨报。
HEADLINE: <标题，≤30字>
TAGS: <标签1>, <标签2>, <标签3>
---
## 🌟 今日要闻
（概述今天最重要的 2-3 件事）
## 🌍 全球时政
- **[标题]**：（2-3句摘要）（来源：XXX）
## 💻 科技与 AI
- **[标题]**：（2-3句摘要）（来源：XXX）
## 📈 财经与市场
- **[标题]**：（2-3句摘要）（来源：XXX）
## 🔥 社会热点
- **[标题]**：（2-3句摘要）（来源：XXX）"""

AI_SYSTEM_PROMPT = _load_prompt()

# ── Notion ───────────────────────────────────────
NOTION_VERSION = "2022-06-28"

# ── HTTP ─────────────────────────────────────────
HTTP_TIMEOUT = _env_int("HTTP_TIMEOUT", 30)
HTTP_RETRIES = _env_int("HTTP_RETRIES", 3)
HTTP_RETRY_BACKOFF = (1, 2, 4)  # seconds for retries 1/2/3
NOTION_MAX_CHILDREN_PER_REQUEST = _env_int("NOTION_MAX_CHILDREN_PER_REQUEST", 100)
NOTION_RICH_TEXT_CHUNK_SIZE = _env_int("NOTION_RICH_TEXT_CHUNK_SIZE", 2000)

# ── Push notification ───────────────────────────
NOTIFY_TIMEOUT = _env_int("NOTIFY_TIMEOUT", 10)
