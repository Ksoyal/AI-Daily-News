# CLAUDE.md

## 项目

AI 资讯聚合管线：RSS 抓取 → OpenRouter AI 摘要 → Notion 数据库发布 → Server酱手机推送。每日自动运行。

## 架构

```
config.py           ── 集中配置（RSS源/AI参数/超时/预算），环境变量可覆盖
    │
    ▼
RSS feeds (5 sources)
    │
    ▼
fetcher.py          ── 30s 超时抓取、单源异常隔离、24h 过滤、关键词黑名单、50条截断
    │
    ▼
summarizer.py       ── OpenRouter API (deepseek-v4-flash:free, 60s timeout)
    │                   Token 预算控制（32K chars, 按源轮询截断）
    │                   返回 {headline, tags, content}
    ▼
publisher.py        ── Markdown→Notion Blocks，动态发现数据库列
    │                   幂等性检查（同日已有页面则跳过）
    │                   3次指数退避重试（429/5xx）
    ▼
main.py             ── 串联 + Server酱推送通知（10s timeout）
```

## 模块

### `config.py` — 集中配置
- `RSS_SOURCES`, `EXCLUDE_KEYWORDS`, `MAX_ENTRIES` — RSS 参数
- `AI_MODEL`, `AI_TEMPERATURE`, `AI_TIMEOUT`, `AI_MAX_INPUT_CHARS`, `AI_MIN_PER_SOURCE` — AI 参数
- `NOTION_VERSION` — Notion API 版本
- `HTTP_TIMEOUT`, `HTTP_RETRIES`, `HTTP_RETRY_BACKOFF` — HTTP 重试策略
- `FETCH_TIMEOUT`, `NOTIFY_TIMEOUT` — 各环节超时
- 所有值均可通过环境变量覆盖

### `fetcher.py` — RSS 抓取
- `RSS_SOURCES`: 5 个源（纽约时报中文/36氪/BBC中文/FT中文网/量子位）
- 用 `requests.get(url, timeout=30)` 先拉 XML 再 `feedparser.parse(string)`
- 每个源独立 try/except，失败只打 warning 不阻断其他源
- `_parse_published()`: 从 `published_parsed` 或 `updated_parsed` 提取 UTC 时间
- `fetch_news()` → `list[dict]`，每条含 `title/link/source/published`
- 过滤: 24h 窗口 → 黑名单关键词（娱乐/明星/八卦/体育）→ 取最新 50 条

### `summarizer.py` — AI 摘要
- `generate_report(news_list)` → `dict{headline, tags, content}`
- 模型: `deepseek/deepseek-v4-flash:free`，OpenAI 兼容接口，temperature=0.3
- `_build_news_text()`: 按源轮询选取条目，32K chars 字符预算，超预算时截断标题以保证每个源至少保留若干条
- Prompt 要求 AI 输出 `HEADLINE: / TAGS: / ---` 三段式，正则解析
- 防范: content 为 None 时抛出 RuntimeError（免费模型偶尔空响应）

### `publisher.py` — Notion 发布
- `push_to_notion(report)`: 接收 summarizer 输出的 dict
- `_retry_request()`: 对 429/502/503/504 自动 3 次指数退避重试（1s/2s/4s）
- `_find_today_page()`: 查询数据库是否已有当日页面，有则跳过创建（幂等性）
- `_get_database_properties()`: 查询 schema，自动发现 title/date/multi_select 列
- `_md_to_notion_blocks()`: 解析 `## heading` → heading_2, `- item` → bulleted_list_item, `**bold**` → annotations
- 如果数据库缺少 date 或 multi_select 列，仅打日志跳过，不报错

### `main.py` — 入口
- `logging.basicConfig` 在 import 之前配置，确保所有模块日志格式统一
- `notify()`: Server酱推送，10s 超时，PUSH_KEY 未设时静默跳过
- `main()`: fetch → summarize → publish，异常时推送失败通知

### `.github/workflows/daily_run.yml`
- 定时: `cron: "0 0 * * *"` (UTC 0:00 = 北京时间 8:00)
- 手动: `workflow_dispatch`
- `timeout-minutes: 15` 防止卡死
- Secrets: `OPENROUTER_API_KEY`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `PUSH_KEY`

## 运行

```bash
# 本地完整运行
python main.py

# 单独测试各模块
python fetcher.py       # 打印抓取的新闻列表（含各源统计）
python summarizer.py    # 用假数据测试 AI 摘要（需 API key）
python publisher.py     # 打印 Notion blocks JSON（不调 API）

# 单元测试
python -m pytest tests/ -v        # 全部测试
python -m pytest tests/test_fetcher.py -v  # 单模块
```

## 测试

`tests/` 目录，pytest 框架，无需网络：
- `test_fetcher.py` — `_parse_published()` 时间解析（4 cases）
- `test_summarizer.py` — `_build_news_text()` token 预算控制（4 cases）
- `test_publisher.py` — `_parse_rich_text()` 粗体解析（3 cases）+ `_md_to_notion_blocks()` 块转换（6 cases）

## 依赖

**生产**
- `feedparser` — RSS 解析
- `openai` — OpenRouter 兼容接口
- `requests` — Notion API / Server酱
- `python-dotenv` — `.env` 加载

**开发** (`requirements-dev.txt`)
- `pytest` — 单元测试

## 环境变量 (`.env`)

| 变量 | 用途 |
|------|------|
| `OPENROUTER_API_KEY` | OpenRouter API 密钥 |
| `NOTION_TOKEN` | Notion Integration Token |
| `NOTION_DATABASE_ID` | 目标数据库 ID (32位 hex) |
| `PUSH_KEY` | Server酱 SendKey (可选) |
| `MAX_ENTRIES` | 最大抓取条数 (默认 50) |
| `FETCH_TIMEOUT` | RSS 抓取超时秒数 (默认 30) |
| `AI_MODEL` | OpenRouter 模型名 (默认 deepseek-v4-flash:free) |
| `AI_TIMEOUT` | AI 请求超时秒数 (默认 60) |
| `AI_MAX_INPUT_CHARS` | AI 输入字符预算 (默认 32000) |
| `HTTP_TIMEOUT` | Notion API 超时秒数 (默认 30) |

## 设计决策

- **OpenRouter 而非直连**: 统一网关，模型切换零成本，当前用免费 deepseek-v4-flash
- **Notion 而非数据库**: 天然支持富文本/Markdown，零运维，移动端直接阅读
- **feedparser 而非 Scrapy**: RSS 聚合不需要爬虫框架，feedparser 轻量且够用
- **Server酱而非 PushPlus**: 简单 HTTP POST，无需 SDK
- **动态列名**: publisher 不硬编码列名，运行时从 schema 自动发现
- **免费模型容错**: summarizer 检测 None content 并转抛 RuntimeError，不静默失败
- **单源异常隔离**: 某个 RSS 源不可达不影响其他源，每个源独立 try/except
- **幂等发布**: 创建 Notion 页面前查询当日是否已有记录，防止 workflow 重跑导致重复
- **指数退避重试**: Notion API 返回 429/5xx 时自动重试，间隔 1s/2s/4s
- **Token 预算控制**: 按源轮询截断新闻列表，确保每个源至少保留若干条，避免单一来源占满上下文
- **配置外部化**: 所有可调参数集中在 config.py，支持环境变量覆盖，无需改代码即可调整
