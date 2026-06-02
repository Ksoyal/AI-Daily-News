import os

from dotenv import load_dotenv

load_dotenv()

# ── RSS ──────────────────────────────────────────
RSS_SOURCES = [
    {"name": "纽约时报中文", "url": "https://cn.nytimes.com/rss/"},
    {"name": "36氪",         "url": "https://36kr.com/feed"},
    {"name": "BBC中文",      "url": "https://www.bbc.com/zhongwen/simp/index.xml"},
    {"name": "FT中文网",      "url": "https://www.ftchinese.com/rss/news"},
    {"name": "量子位",        "url": "https://www.qbitai.com/rss"},
    {"name": "德国之声中文",  "url": "https://rss.dw.com/rdf/rss-chi-all"},
    {"name": "日经中文网",    "url": "https://cn.nikkei.com/rss.html"},
    {"name": "爱范儿",        "url": "https://www.ifanr.com/feed"},
    {"name": "端传媒",        "url": "https://theinitium.com/feed/"},
]

EXCLUDE_KEYWORDS = ["娱乐", "明星", "八卦", "体育"]

MAX_ENTRIES = int(os.getenv("MAX_ENTRIES", "50"))

FETCH_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "30"))
FETCH_USER_AGENT = os.getenv(
    "FETCH_USER_AGENT",
    "Mozilla/5.0 (compatible; AI-Daily-News/1.0; +https://github.com/Ksoyal/AI-Daily-News)"
)

# ── AI ───────────────────────────────────────────
# Google AI Studio (OpenAI-compatible endpoint)
# Get key at https://aistudio.google.com/apikey
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
AI_API_KEY = os.getenv("GEMINI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gemini-3-flash-preview")
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.3"))
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "60"))
AI_MAX_INPUT_CHARS = int(os.getenv("AI_MAX_INPUT_CHARS", "32000"))
# Per-source floor: when truncating for token budget, try to keep at least
# this many entries from each source that has entries.
AI_MIN_PER_SOURCE = 2

# ── Notion ───────────────────────────────────────
NOTION_VERSION = "2022-06-28"

# ── HTTP ─────────────────────────────────────────
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
HTTP_RETRIES = 3
HTTP_RETRY_BACKOFF = (1, 2, 4)  # seconds for retries 1/2/3

# ── Push notification ───────────────────────────
NOTIFY_TIMEOUT = int(os.getenv("NOTIFY_TIMEOUT", "10"))
