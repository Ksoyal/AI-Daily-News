import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project root (where config.py lives)
PROJECT_DIR = Path(__file__).resolve().parent

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

MAX_ENTRIES = int(os.getenv("MAX_ENTRIES", "100"))

FETCH_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "30"))
FETCH_USER_AGENT = os.getenv(
    "FETCH_USER_AGENT",
    "Mozilla/5.0 (compatible; AI-Daily-News/1.0; +https://github.com/Ksoyal/AI-Daily-News)"
)

# ── AI ───────────────────────────────────────────
# Provider-agnostic: change AI_BASE_URL + AI_MODEL + AI_API_KEY to switch
# Google AI Studio (OpenAI-compatible endpoint)
# Get key at https://aistudio.google.com/apikey
# OpenRouter: base_url="https://openrouter.ai/api/v1", model="provider/model"
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
AI_API_KEY = os.getenv("AI_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("OPENROUTER_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gemini-3-flash-preview")
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.5"))
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "60"))
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "8192"))
AI_MAX_INPUT_CHARS = int(os.getenv("AI_MAX_INPUT_CHARS", "32000"))
# Per-source floor: when truncating for token budget, try to keep at least
# this many entries from each source that has entries.
AI_MIN_PER_SOURCE = 2

# ── AI Prompt ─────────────────────────────────────
# Priority: AI_SYSTEM_PROMPT (inline) > AI_PROMPT_FILE (path) > prompt.txt (default)
def _load_prompt():
    """Load the system prompt with env-var override support."""
    # 1. Inline env var wins
    inline = os.getenv("AI_SYSTEM_PROMPT")
    if inline:
        return inline

    # 2. Custom file path
    file_path = os.getenv("AI_PROMPT_FILE")
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
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
HTTP_RETRIES = 3
HTTP_RETRY_BACKOFF = (1, 2, 4)  # seconds for retries 1/2/3

# ── Push notification ───────────────────────────
NOTIFY_TIMEOUT = int(os.getenv("NOTIFY_TIMEOUT", "10"))
