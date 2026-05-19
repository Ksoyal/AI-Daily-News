# CLAUDE.md

## 项目

AI 资讯聚合管线：RSS 抓取 → OpenRouter AI 摘要 → Notion 数据库发布 → Server酱手机推送。每日自动运行。

## 架构

```
RSS feeds (5 sources)
    │
    ▼
fetcher.py          ── 24h 过滤、关键词黑名单、50条截断
    │
    ▼
summarizer.py       ── OpenRouter API (deepseek-v4-flash:free)
    │                   返回 {headline, tags, content}
    ▼
publisher.py        ── Markdown→Notion Blocks，动态发现数据库列
    │                   标题=AI headline，日期=today，标签=多选
    ▼
main.py             ── 串联 + Server酱推送通知
```

## 模块

### `fetcher.py` — RSS 抓取
- `RSS_SOURCES`: 5 个源（纽约时报中文/36氪/BBC中文/FT中文网/量子位）
- `_parse_published()`: 从 `published_parsed` 或 `updated_parsed` 提取 UTC 时间
- `fetch_news()` → `list[dict]`，每条含 `title/link/source/published`
- 过滤: 24h 窗口 → 黑名单关键词（娱乐/明星/八卦/体育）→ 取最新 50 条

### `summarizer.py` — AI 摘要
- `generate_report(news_list)` → `dict{headline, tags, content}`
- 模型: `deepseek/deepseek-v4-flash:free`，OpenAI 兼容接口，temperature=0.3
- Prompt 要求 AI 输出 `HEADLINE: / TAGS: / ---` 三段式，正则解析
- 防范: content 为 None 时抛出 RuntimeError（免费模型偶尔空响应）

### `publisher.py` — Notion 发布
- `push_to_notion(report)`: 接收 summarizer 输出的 dict
- `_get_database_properties()`: 查询 schema，自动发现 title/date/multi_select 列
- `_md_to_notion_blocks()`: 解析 `## heading` → heading_2, `- item` → bulleted_list_item, `**bold**` → annotations
- 如果数据库缺少 date 或 multi_select 列，仅打日志跳过，不报错

### `main.py` — 入口
- `logging.basicConfig` 在 import 之前配置，确保所有模块日志格式统一
- `notify()`: Server酱推送，PUSH_KEY 未设时静默跳过
- `main()`: fetch → summarize → publish，异常时推送失败通知

### `.github/workflows/daily_run.yml`
- 定时: `cron: "0 0 * * *"` (UTC 0:00 = 北京时间 8:00)
- 手动: `workflow_dispatch`
- Secrets: `OPENROUTER_API_KEY`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `PUSH_KEY`

## 运行

```bash
# 本地完整运行
python main.py

# 单独测试各模块
python fetcher.py       # 打印抓取的新闻列表
python summarizer.py    # 用假数据测试 AI 摘要
python publisher.py     # 打印 Notion blocks JSON（不调 API）
```

## 依赖

- `feedparser` — RSS 解析
- `openai` — OpenRouter 兼容接口
- `requests` — Notion API / Server酱
- `python-dotenv` — `.env` 加载

## 环境变量 (`.env`)

| 变量 | 用途 |
|------|------|
| `OPENROUTER_API_KEY` | OpenRouter API 密钥 |
| `NOTION_TOKEN` | Notion Integration Token |
| `NOTION_DATABASE_ID` | 目标数据库 ID (32位 hex) |
| `PUSH_KEY` | Server酱 SendKey (可选) |

## 设计决策

- **OpenRouter 而非直连**: 统一网关，模型切换零成本，当前用免费 deepseek-v4-flash
- **Notion 而非数据库**: 天然支持富文本/Markdown，零运维，移动端直接阅读
- **feedparser 而非 Scrapy**: RSS 聚合不需要爬虫框架，feedparser 轻量且够用
- **Server酱而非 PushPlus**: 简单 HTTP POST，无需 SDK
- **动态列名**: publisher 不硬编码列名，运行时从 schema 自动发现
- **免费模型容错**: summarizer 检测 None content 并转抛 RuntimeError，不静默失败
