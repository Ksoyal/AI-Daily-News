# 03 · 配置系统 config.py

> **核心思想**: 把所有"可调整的数字和字符串"集中到一个文件，不改代码就能换模型、换源、改超时。

## 为什么要集中配置？

新手的直觉写法是参数散落各处：

```python
# ❌ 反模式：参数硬编码在代码里
resp = requests.get(url, timeout=30)  # 30 是什么？为什么要 30？
client = OpenAI(base_url="https://openrouter.ai/api/v1")  # URL 写死在业务逻辑里
```

集中的好处：
1. **改一处生效全局** — 换模型只改 `AI_MODEL`
2. **环境变量覆盖** — 服务器和本地可以不同配置
3. **一目了然** — 打开 `config.py` 就知道项目有哪些可调参数

## 逐段拆解

### 第一部分：加载环境变量

```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # ← 读取 .env 文件，把 KEY=VALUE 变成系统环境变量

PROJECT_DIR = Path(__file__).resolve().parent  # 项目根目录（config.py 所在目录）
```

**新知**: `Path(__file__).resolve().parent`
- `__file__` — 当前文件的路径（`d:/Work/.../config.py`）
- `.resolve()` — 转为绝对路径
- `.parent` — 父目录（即 `AI-Daily-News/`）

### 第二部分：RSS 配置

```python
RSS_SOURCES = [
    {"name": "纽约时报中文", "urls": [
        "https://cn.nytimes.com/rss/",          # 主 URL
        "https://rsshub.app/nytimes/zh-Hans",    # 备选 URL（镜像）
    ]},
    {"name": "36氪", "urls": ["https://36kr.com/feed"]},
    # ... 共 9 个源
]
```

**新知**: `urls` 列表 — 不是单个 `url` 字符串。fetcher 会依次尝试直到成功：
```
1. 试直连 URL → 200 ✅ 就用它
2. 403/超时 → 试第 2 个（RSSHub 镜像）
3. 全部失败 → 打 warning，跳过这个源
```

```python
EXCLUDE_KEYWORDS = ["娱乐", "明星", "八卦", "体育"]
MAX_ENTRIES = int(os.getenv("MAX_ENTRIES", "100"))      # 环境变量或 100
FETCH_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "30"))    # 单源请求 30 秒超时
FETCH_USER_AGENT = os.getenv("FETCH_USER_AGENT", "Mozilla/5.0 (...)")
```

**新知**: `os.getenv("KEY", "默认值")` — 先查环境变量，没有就用默认值

### 第三部分：AI 配置

```python
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1")
AI_API_KEY = (
    os.getenv("AI_API_KEY")          # 优先级 1: 通用变量
    or os.getenv("OPENROUTER_API_KEY")  # 优先级 2: OpenRouter 专用
    or os.getenv("GEMINI_API_KEY")      # 优先级 3: Gemini 专用
    or ""  # 都没设则为空
)
AI_MODEL = os.getenv("AI_MODEL", "moonshotai/kimi-k2.6:free")
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.5"))
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "8192"))
AI_MAX_INPUT_CHARS = int(os.getenv("AI_MAX_INPUT_CHARS", "32000"))
AI_MIN_PER_SOURCE = 2  # 每个 RSS 源至少保留 2 条
```

**新知**: `or` 链式回退（短路的妙用）
```python
result = a or b or c or d
# 等价于：
if a: result = a
elif b: result = b
elif c: result = c
else: result = d
```

> [!tip] 怎么换模型？
> ```bash
> # 方法 1: 改 .env
> AI_MODEL=gemini-3-flash-preview
> AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
> 
> # 方法 2: 改 config.py 的默认值（上面的代码）
> ```

### 第四部分：Prompt 加载（高级）

```python
def _load_prompt():
    # 1. 环境变量直接设置 Prompt → 最高优先级
    inline = os.getenv("AI_SYSTEM_PROMPT")
    if inline:
        return inline
    
    # 2. 指定外部文件路径
    file_path = os.getenv("AI_PROMPT_FILE")
    if file_path and Path(file_path).exists():
        return Path(file_path).read_text(encoding="utf-8")
    
    # 3. 默认文件
    default = PROJECT_DIR / "prompt.txt"
    if default.exists():
        return default.read_text(encoding="utf-8")
    
    # 4. 实在没有，用内置最小 Prompt
    return _FALLBACK_PROMPT

AI_SYSTEM_PROMPT = _load_prompt()  # 模块导入时就加载好了
```

**新知**:
- `Path("file.txt").read_text(encoding="utf-8")` — 一次读入整个文件
- `PROJECT_DIR / "prompt.txt"` — 用 `/` 拼接路径（比 `+` 拼接字符串优雅）

### 第五部分：下游配置

```python
NOTION_VERSION = "2022-06-28"
HTTP_TIMEOUT = 30
HTTP_RETRIES = 3
HTTP_RETRY_BACKOFF = (1, 2, 4)  # 第 1 次重试等 1s, 第 2 次等 2s, 第 3 次等 4s
NOTIFY_TIMEOUT = 10
```

---

## 本模块学到的 Python 知识点

| 概念 | 代码示例 |
|------|---------|
| 环境变量 | `os.getenv("KEY", "default")` |
| 路径操作 | `Path(__file__).resolve().parent` |
| `or` 链短路 | `a or b or c` 返回第一个真值 |
| 类型转换 | `int()`, `float()` 字符串→数字 |
| 列表嵌套字典 | `[{"name": "x", "urls": [...]}]` |
| 文件读取 | `Path("f.txt").read_text(encoding="utf-8")` |

---

→ 下一步: [[04-RSS抓取-fetcher]]
