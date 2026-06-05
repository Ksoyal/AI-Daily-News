# 06 · Notion 发布 publisher.py

> 把 AI 生成的 Markdown 日报转为 Notion API 能理解的 JSON Blocks，创建一条格式精美的数据库页面。

## 核心挑战

Notion 不是 Markdown 编辑器。它的每个段落、标题、列表项都是一个**独立 JSON 对象**。本模块的工作就是把 `## 标题` 这样的 Markdown 文本转换成 Notion 的 block JSON。

## 模块架构

```
push_to_notion(report)          ← 入口
    │
    ├── _get_database_properties()  ← 查 Notion Schema
    ├── _find_today_page()          ← 幂等性检查
    ├── _md_to_notion_blocks()      ← Markdown → JSON
    │       └── _parse_rich_text()  ← **粗体** → annotation
    └── _retry_request()            ← 网络重试
```

## 逐段讲解

### Markdown → Notion Blocks 转换器

这是 147 行的核心函数。一个 `for` 循环逐行解析：

```python
def _md_to_notion_blocks(md_text):
    blocks = []
    for line in md_text.strip().split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
```

**新知**: `str.split("\n")` — 按换行符切割，得到每行字符串的列表。

```python
        # 分隔线
        if stripped == "---" or _is_decorative_line(stripped):
            blocks.append({"type": "divider", "divider": {}})
            continue

        # 二级标题
        if stripped.startswith("## "):
            blocks.append({
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": stripped[3:]}}]}
            })
            continue
```

**样式对照表**:

| Markdown | Notion Block Type | 视觉效果 |
|----------|-------------------|---------|
| `---` | `divider` | ────────── |
| `## 标题` | `heading_2` | 大字二级标题 |
| `### 标题` | `heading_3` | 中号三级标题 |
| `> 引用` | `quote` | 左边竖线 + 缩进 |
| `- 条目` | `bulleted_list_item` | · 圆点列表 |
| `❶ 条目` | `numbered_list_item` | 1. 数字列表 |
| 普通文本 | `paragraph` | 正文 |

### 粗体解析（正则拆分）

```python
def _parse_rich_text(text):
    parts = re.split(r"\*\*(.*?)\*\*", text)
    # "**新闻标题**：摘要内容"
    # → ["", "新闻标题", "：摘要内容"]
    
    rich_text = []
    for i, part in enumerate(parts):
        if not part:
            continue
        rich_text.append({
            "type": "text",
            "text": {"content": part},
            "annotations": {"bold": (i % 2 == 1)},  # 奇数索引 = 粗体
        })
    return rich_text
```

**巧妙的技巧**: `re.split` 捕获组保留分隔符在结果中
- `i=0` 偶数 → 普通文本
- `i=1` 奇数 → 分隔符之间的内容（要加粗的）

### 装饰行检测

```python
def _is_decorative_line(line):
    return bool(re.match(r'^[\s▁▔━─══║·•▪▸●◂]+$', line))
```

如果一行**全部**由装饰字符组成 → 转为 Notion 分隔线。空一行在 Markdown 中被打成 `continue`，保留排版呼吸感。

### 重试机制（智能：不重试 4xx）

```python
def _retry_request(method, url, **kwargs):
    RETRYABLE = (429, 502, 503, 504)    # 只有这些才重试
    for attempt in range(HTTP_RETRIES + 1):
        try:
            resp = requests.request(...)
            if resp.status_code in RETRYABLE and attempt < HTTP_RETRIES:
                time.sleep(HTTP_RETRY_BACKOFF[attempt])  # 1, 2, 4 秒
                continue              # 服务器忙 → 等一会再试
            # 400 等 4xx 错误 → 直接报错并记录响应内容（不重试）
            if 400 <= resp.status_code < 500:
                logger.error(f"{resp.status_code}: {resp.text[:500]}")
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            is_retryable = (
                isinstance(e, HTTPError) and e.response.status_code in RETRYABLE
            ) or not isinstance(e, HTTPError)  # 连接错误可重试
            if is_retryable and attempt < HTTP_RETRIES:
                time.sleep(delay)
            else:
                raise       # 4xx 不重试，直接抛出
```

**新知**: `**kwargs` — 接受任意关键字参数
```python
# 调用时:
_retry_request("GET", url, headers={...}, json={...})
# headers 和 json 会通过 **kwargs 传递给 requests.request
```

### 幂等性检查

```python
def _find_today_page(token, database_id, date_col, today):
    resp = _retry_request("POST", url, json={
        "filter": {
            "property": date_col,
            "date": {"equals": today},   # Notion API 的日期过滤语法
        }
    })
    results = resp.json().get("results", [])
    if results:
        return results[0].get("url")    # 找到了 → 返回已有页面 URL
    return None                         # 没找到 → 可以创建
```

**为什么要幂等性？** 如果 GitHub Actions 一天跑了两次（比如手动触发 + 定时触发），没有幂等性检查就会创建两条"2026-06-04 AI 晨报"。

### 数据库属性自动发现

```python
def _get_database_properties(token, database_id):
    resp = _retry_request("GET", url)
    for name, prop in resp.json().get("properties", {}).items():
        ptype = prop.get("type")
        if ptype == "title":       title_col = name       # 找到"标题"列
        elif ptype == "date":      date_col = name        # 找到"日期"列
        elif ptype == "multi_select": tags_col = name     # 找到"标签"列
    
    if title_col is None:
        raise ValueError("没有 title 列！")
    return title_col, date_col, tags_col
```

**设计亮点**: 不硬编码列名。中文"标题"、英文"Name"、日文"タイトル"都能自动适配。

---

## 本模块学到的 Python 知识点

| 概念 | 场景 |
|------|------|
| `**kwargs` | 传递请求参数 |
| `re.split()` | 按 `**...**` 标记拆分粗体 |
| `time.sleep()` | 重试前的等待 |
| `raise`（最后的重试） | 重试耗尽后抛出 |
| Notion API JSON 结构 | 嵌套 dict/list 的实际应用 |
| `resp.json()` | API 响应 JSON → Python dict |

---

→ 下一步: [[07-主流程-main]]
