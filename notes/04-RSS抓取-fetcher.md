# 04 · RSS 抓取 fetcher.py

> 这一模块的职责：从互联网的 RSS/XML 订阅源拉取新闻，过滤掉无关内容，输出标准格式。

## 整体流程

```
for 每个 RSS 源:
    ① HTTP GET 拉取 XML
    ② feedparser 解析
    ③ 遍历条目: 提取时间 → 24h 过滤 → 关键词过滤 → 收集
④ 按时间降序排列
⑤ 截断到 MAX_ENTRIES 条
输出: list[dict]
```

## 逐段讲解

### 导入和 logger

```python
import feedparser      # 解析 RSS/XML
import requests        # 发 HTTP 请求
from datetime import datetime, timedelta, timezone  # 处理时间
from config import RSS_SOURCES, EXCLUDE_KEYWORDS, MAX_ENTRIES, FETCH_TIMEOUT, FETCH_USER_AGENT

logger = logging.getLogger(__name__)  # 日志标签 "fetcher"
```

**新知**: `from config import ...` — 在其他 `.py` 文件中 `import` 当前项目自己的模块，路径从项目根开始

### 时间解析函数

```python
def _parse_published(entry):
    for attr in ("published_parsed", "updated_parsed"):
        struct = getattr(entry, attr, None)
        if struct:
            return datetime(*struct[:6], tzinfo=timezone.utc)
    return None
```

**逐行解释**:

| 行 | 含义 |
|----|------|
| `("published_parsed", "updated_parsed")` | 元组：先试"发布时间"，再试"更新时间" |
| `getattr(entry, attr, None)` | 相当于 `entry.published_parsed` 但找不到返回 `None` |
| `*struct[:6]` | 解包前 6 个元素 `(年,月,日,时,分,秒)` |
| `tzinfo=timezone.utc` | 标注为 UTC 时区 |

**新知**: `*` 解包运算符
```python
# struct = (2026, 6, 4, 8, 0, 0)
datetime(*struct[:6])
# 等价于 → datetime(2026, 6, 4, 8, 0, 0)
```

### 主抓取函数

```python
def fetch_news():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    # 计算 24 小时前的时间点，比如现在 2026-06-04T18:00Z，cutoff = 2026-06-03T18:00Z
    entries = []
```

**新知**: `timedelta` — 时间差
```python
now = datetime.now(timezone.utc)
yesterday = now - timedelta(hours=24)   # 24 小时前
one_week_ago = now - timedelta(days=7)  # 7 天前
```

### Fallback URL 和异常隔离（核心模式）

```python
    for src in RSS_SOURCES:
        urls = src.get("urls")   # 取 URLs 列表
        feed = None
        last_error = None
        
        for url in urls:         # 依次尝试每个 URL
            try:
                resp = requests.get(url, timeout=FETCH_TIMEOUT,
                                    headers={"User-Agent": FETCH_USER_AGENT})
                resp.raise_for_status()        # 非 200 就抛异常
                feed = feedparser.parse(resp.content)
                break                          # 成功！退出 URL 循环
            except requests.RequestException as e:
                last_error = e
                continue                       # 失败，试下一个 URL
        
        if feed is None:                       # 所有 URL 都失败
            logger.warning(f"Failed ...")
            continue                           # 跳过这个源，不阻断其他源
```

**核心概念**: 这整个 `try/except` 在 `for src` 循环内部。一个源失败 → 打 log → `continue` → 进入下一个源。这叫**单源异常隔离**。

### 过滤和收集

```python
        source_count = 0
        for entry in feed.entries:             # feed.entries 是解析后的条目列表
            published = _parse_published(entry)
            if published is None:              # 没有时间信息 → 跳过
                continue
            if published < cutoff:             # 超过 24 小时 → 跳过
                continue
            
            title = entry.get("title", "")
            if any(kw in title for kw in EXCLUDE_KEYWORDS):
                continue  # 标题含"娱乐""明星"等 → 跳过
            
            entries.append({                    # 收集到列表
                "title": title,
                "link": entry.get("link", ""),
                "source": src["name"],
                "published": published.isoformat(),
            })
            source_count += 1
        
        logger.info(f"{src['name']}: {source_count} entries accepted")
```

**新知**: `any()` — 任何元素为 True 就返回 True
```python
any(kw in "娱乐新闻" for kw in ["娱乐", "明星", "八卦"])
# "娱乐" in "娱乐新闻" → True → any 返回 True → 跳过这条
```

### 排序和截断

```python
    entries.sort(key=lambda e: e["published"], reverse=True)
    return entries[:MAX_ENTRIES]
```

**新知**: `lambda` — 匿名函数
```python
# key=lambda e: e["published"]
# 等价于:
def get_published(e):
    return e["published"]
entries.sort(key=get_published, reverse=True)
```

`reverse=True` → 降序 → 最新的在前面
`[:MAX_ENTRIES]` → 取前 100 条（切片）

---

## 本模块学到的 Python 知识点

| 概念 | 场景 |
|------|------|
| `try/except` | 网络请求可能超时/403 |
| `continue` | 跳过一个源，继续下一个 |
| `*struct[:6]` | 列表/元组解包 |
| `datetime` + `timedelta` | 时间计算（24h 过滤） |
| `lambda` | 排序 key 的简写 |
| `any()` | 检查是否存在任何匹配 |
| 切片 `[:100]` | 取列表前 100 条 |
| `getattr(obj, attr, default)` | 安全的属性访问 |
| `dict.get(key, default)` | 安全的字典取值 |

---

→ 下一步: [[05-AI摘要-summarizer]]
