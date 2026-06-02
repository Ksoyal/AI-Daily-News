# CLAUDE.md

## 项目

AI 资讯聚合管线：RSS 抓取 → Google AI Studio AI 摘要 → Notion 数据库发布 → Server酱手机推送。每日自动运行。

## 架构

```
config.py           ── 集中配置（RSS源/AI参数/超时/预算），环境变量可覆盖
    │
    ▼
RSS feeds (9 sources)
    │
    ▼
fetcher.py          ── 30s 超时抓取、User-Agent 伪装、单源异常隔离、24h 过滤、关键词黑名单、100条截断
    │
    ▼
summarizer.py       ── Google AI Studio (gemini-3-flash-preview, OpenAI 兼容端点, 60s timeout)
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
- `FETCH_TIMEOUT`, `FETCH_USER_AGENT` — RSS 请求策略
- `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`, `AI_TEMPERATURE`, `AI_TIMEOUT` — AI 参数
- `AI_MAX_INPUT_CHARS`, `AI_MIN_PER_SOURCE` — Token 预算控制
- `NOTION_VERSION` — Notion API 版本
- `HTTP_TIMEOUT`, `HTTP_RETRIES`, `HTTP_RETRY_BACKOFF` — HTTP 重试策略
- `NOTIFY_TIMEOUT` — 推送超时
- 所有值均可通过环境变量覆盖，`.env` 在模块 import 时自动加载

### `fetcher.py` — RSS 抓取
- `RSS_SOURCES`: 9 个源（纽约时报中文/36氪/BBC中文/FT中文网/量子位/德国之声中文/日经中文网/爱范儿/端传媒）
- 用 `requests.get(url, timeout=30)` 先拉 XML 再 `feedparser.parse(string)`
- 带 `User-Agent` 头伪装浏览器，避免 403 拦截
- 每个源独立 try/except，失败只打 warning 不阻断其他源
- `_parse_published()`: 从 `published_parsed` 或 `updated_parsed` 提取 UTC 时间
- `fetch_news()` → `list[dict]`，每条含 `title/link/source/published`
- 过滤: 24h 窗口 → 黑名单关键词（娱乐/明星/八卦/体育）→ 取最新 100 条

### `summarizer.py` — AI 摘要
- `generate_report(news_list)` → `dict{headline, tags, content}`
- 模型: `gemini-3-flash-preview`，Google AI Studio OpenAI 兼容端点，temperature=0.5
- `_build_news_text()`: 按源轮询选取条目，32K chars 字符预算，每源保底2条，避免单一来源占满上下文
- Prompt 要求 AI 输出 `HEADLINE: / TAGS: / ---` 三段式，正则解析；日报含5大板块 + 🔍深度解读（150-250字独立编辑分析），目标2000-3000字
- 防范: content 为 None 时抛出 RuntimeError

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
- Secrets: `GEMINI_API_KEY`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `PUSH_KEY`

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
- `openai` — Google AI Studio OpenAI 兼容接口
- `requests` — Notion API / Server酱 / RSS 抓取
- `python-dotenv` — `.env` 加载

**开发** (`requirements-dev.txt`)
- `pytest` — 单元测试

## 环境变量 (`.env`)

| 变量 | 用途 |
|------|------|
| `GEMINI_API_KEY` | Google AI Studio API 密钥（免费，aistudio.google.com） |
| `NOTION_TOKEN` | Notion Integration Token |
| `NOTION_DATABASE_ID` | 目标数据库 ID (32位 hex) |
| `PUSH_KEY` | Server酱 SendKey (可选) |
| `MAX_ENTRIES` | 最大抓取条数 (默认 100) |
| `FETCH_TIMEOUT` | RSS 抓取超时秒数 (默认 30) |
| `AI_MODEL` | 模型名 (默认 gemini-3-flash-preview) |
| `AI_BASE_URL` | AI API 端点 (默认 Google AI Studio) |
| `AI_TIMEOUT` | AI 请求超时秒数 (默认 60) |
| `AI_MAX_INPUT_CHARS` | AI 输入字符预算 (默认 32000) |
| `HTTP_TIMEOUT` | Notion API 超时秒数 (默认 30) |

## 设计决策

- **Google AI Studio 而非 OpenRouter**: 免费 Gemini 3 Flash Preview，大上下文，中文能力强
- **OpenAI 兼容端点**: 不改 SDK，只换 `base_url` + `api_key`，迁移零摩擦
- **Notion 而非数据库**: 天然支持富文本/Markdown，零运维，移动端直接阅读
- **feedparser 而非 Scrapy**: RSS 聚合不需要爬虫框架，feedparser 轻量且够用
- **Server酱而非 PushPlus**: 简单 HTTP POST，无需 SDK
- **动态列名**: publisher 不硬编码列名，运行时从 schema 自动发现
- **单源异常隔离**: 某个 RSS 源不可达不影响其他源，每个源独立 try/except
- **幂等发布**: 创建 Notion 页面前查询当日是否已有记录，防止 workflow 重跑导致重复
- **指数退避重试**: Notion API 返回 429/5xx 时自动重试，间隔 1s/2s/4s
- **Token 预算控制**: 按源轮询截断新闻列表，确保每个源至少保留若干条，避免单一来源占满上下文
- **配置外部化**: 所有可调参数集中在 config.py，支持环境变量覆盖，无需改代码即可调整
- **User-Agent 伪装**: 部分 RSS 源（如量子位）会封默认 UA，配置独立的 User-Agent 头解决
- **深度解读板块**: 日报不仅有条目摘要，还有 AI 编辑挑选当天最重要事件写150-250字独立分析，提供观点和趋势判断
- **较高温度参数**: temperature=0.5 而非极保守的0.3，让 AI 语言更生动、有编辑判断力，类似财新风格
