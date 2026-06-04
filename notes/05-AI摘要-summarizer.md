# 05 · AI 摘要 summarizer.py

> 这个模块是项目的"大脑"——把 100 条新闻标题和链接交给大模型，让它生成一份结构化的日报。

## 整体流程

```
100 条新闻 → 按源轮询截断（32K 字符预算）
           → 构建 Prompt（系统 Prompt + 用户消息）
           → 调用 OpenRouter API
           → 解析返回的结构化文本
           → 返回 {headline, tags, content}
```

## 逐段讲解

### 导入

```python
import re                            # 正则表达式，用来解析 AI 返回的文本
from openai import OpenAI            # OpenAI SDK（兼容 OpenRouter）
from config import (AI_BASE_URL, AI_API_KEY, AI_MODEL, ...)
```

`from config import (...)` — 圆括号允许换行写多个 import。

### Token 预算控制（核心算法）

```python
def _build_news_text(news_list):
    by_source = {}                   # 按源分组: {"36氪": [...], "BBC中文": [...]}
    for item in news_list:
        by_source.setdefault(item["source"], []).append(item)
    
    source_names = list(by_source.keys())
    indices = {s: 0 for s in source_names}  # 每个源读到第几条了
    selected = []
    budget = AI_MAX_INPUT_CHARS             # 32000 字符的预算
```

**新知**: `dict.setdefault(key, default)`
```python
# 如果 key 不存在 → 新建 []，返回这个空列表
# 如果 key 已存在 → 返回已有列表
by_source.setdefault("36氪", []).append(item)
```

### 轮询算法（Round-Robin）

```
源 A: [新闻1, 新闻2, 新闻3, ...]
源 B: [新闻1, 新闻2, ...]
源 C: [新闻1, ...]

轮询取法: A1 → B1 → C1 → A2 → B2 → C2 → A3 → ...
```

```python
    while True:
        added = False
        for src in source_names:
            idx = indices[src]
            if idx >= len(by_source[src]):
                continue              # 这个源已经取完了
            
            entry = by_source[src][idx]
            line = f"[{len(selected)+1}] 标题：{entry['title']}\n..."
            
            if budget - len(line) < 0:    # 预算不够了
                if idx < AI_MIN_PER_SOURCE:  # 每源至少保底 2 条
                    # 截断标题，硬塞进去
                    max_title_len = budget - (固定部分长度)
                    if max_title_len > 10:
                        truncated = entry['title'][:max_title_len] + "..."
                        line = f"...标题：{truncated}..."
                        selected.append(line)
                        budget -= len(line)
                continue              # 这个源本轮跳过，试下一个源
            
            selected.append(line)
            budget -= len(line)
            indices[src] += 1
            added = True
        
        if not added:                  # 所有源都取完了或预算都分配完了
            break
```

> [!tip] 为什么用轮询而不是直接取前 50 条？
> 如果直接按时间排序取，36氪（每天 ~30 条）会挤占大部分位置。轮询保证 BBC中文（每天 ~7 条）和日经中文网（~10 条）也能被代表。

### API 调用

```python
def generate_report(news_list):
    client = OpenAI(
        base_url=AI_BASE_URL,    # OpenRouter 端点
        api_key=AI_API_KEY,      # 你的密钥
        timeout=AI_TIMEOUT,
    )
    
    news_text = _build_news_text(news_list)
    
    resp = client.chat.completions.create(
        model=AI_MODEL,          # "moonshotai/kimi-k2.6:free"
        messages=[
            {"role": "system", "content": AI_SYSTEM_PROMPT},   # 系统指令
            {"role": "user",   "content": f"请生成日报:\n\n{news_text}"},  # 用户数据
        ],
        temperature=AI_TEMPERATURE,  # 0.5 — 有创造力但不胡编
        max_tokens=AI_MAX_TOKENS,    # 最大输出 8192 tokens
    )
```

**新概念**: 对话模型的消息结构
```
messages = [
    {"role": "system", "content": "你是一个编辑..."},   ← 角色设定
    {"role": "user",   "content": "这是今天的新闻..."},  ← 任务输入
]
```

`system message` 告诉 AI 它是谁、要做什么、什么格式。`user message` 是具体的任务数据。

### 空响应检测

```python
    choice = resp.choices[0]
    raw = choice.message.content       # AI 返回的文本
    
    if raw is None:                    # 模型可能过载，返回空
        raise RuntimeError("AI returned empty content...")
    
    # ...继续解析
```

**新知**: `raise` — 主动抛出异常
```python
raise RuntimeError("错误描述")
# 调用方（main.py）的 try/except 会捕获它，并推送失败通知
```

### 正则解析（关键）

AI 返回的文本格式：
```
HEADLINE: 特朗普取消对伊朗新攻击
TAGS: 地缘政治, AI监管

---

## 🌟 今日要闻
...
```

提取逻辑：
```python
    headline_match = re.search(r'^HEADLINE:\s*(.+)$', raw, re.MULTILINE)
    tags_match = re.search(r'^TAGS:\s*(.+)$', raw, re.MULTILINE)
    
    headline = headline_match.group(1).strip() if headline_match else "AI 晨报"
    tags_raw = tags_match.group(1).strip() if tags_match else ""
    tags = [t.strip() for t in tags_raw.replace("，", ",").split(",") if t.strip()][:3]
    
    body_match = re.search(r'^---\s*\n(.+)$', raw, re.MULTILINE | re.DOTALL)
    content = body_match.group(1).strip() if body_match else raw
```

**正则表达式解释**:

| 正则 | 含义 |
|------|------|
| `^HEADLINE:` | 行首匹配 "HEADLINE:" |
| `\s*` | 0 或多个空白字符 |
| `(.+)` | 捕获一个或多个任意字符 |
| `$` | 行尾 |
| `re.MULTILINE` | `^` `$` 匹配每行的开头结尾 |
| `re.DOTALL` | `.` 也匹配换行符 |

`group(1)` 返回第一个括号 `(...)` 捕获的内容。`group(0)` 是完整匹配。

### 返回值

```python
    return {
        "headline": headline,          # str: AI 生成的标题
        "tags": tags,                  # list[str]: 2-3 个标签
        "content": content,            # str: Markdown 日报正文
    }
```

---

## 本模块学到的 Python 知识点

| 概念 | 场景 |
|------|------|
| `dict.setdefault()` | 按键分组（RSS 源名 → 新闻列表） |
| 字典推导式 | `{s: 0 for s in sources}` |
| `openai` SDK | 标准化的 LLM 调用模式 |
| 列表推导式 | `[t.strip() for t in s.split(",")]` |
| 正则表达式 | 解析 AI 返回的结构化文本 |
| `raise` | 主动抛出异常 |
| `if x else y` 三元表达式 | 安全的 fallback |

---

→ 下一步: [[06-Notion发布-publisher]]
