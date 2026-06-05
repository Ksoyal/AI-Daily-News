# CLAUDE.md

## 项目

AI 资讯聚合管线：RSS 抓取 → OpenRouter AI 摘要 → Notion 数据库发布 → Server酱手机推送。每日 8:00 自动运行。

## 架构

```
config.py           ── 集中配置（RSS源/AI参数/超时/预算），环境变量可覆盖
    │
    ▼
RSS feeds (9 sources)
    │
    ▼
fetcher.py          ── 30s 超时抓取、User-Agent 伪装、Fallback URL、单源异常隔离、
    │                   24h 过滤、关键词黑名单、100条截断
    ▼
summarizer.py       ── OpenRouter API (moonshotai/kimi-k2.6:free, OpenAI 兼容端点, 60s timeout)
    │                   Token 预算控制（32K chars, 按源轮询截断）
    │                   返回 {headline, tags, content}
    ▼
publisher.py        ── Markdown→Notion Blocks（H2/H3/Quote/Divider/Bullet），动态发现数据库列
    │                   幂等性检查（同日已有页面则跳过）
    │                   3次指数退避重试（429/5xx）
    ▼
main.py             ── 串联 + Server酱推送通知（10s timeout）

trigger.py          ── 外部精准触发器（repository_dispatch API）
```

## 模块

### `config.py` — 集中配置
- `RSS_SOURCES`: 9 个源，每个支持 `urls` 列表（fallback 机制）
- `EXCLUDE_KEYWORDS`, `MAX_ENTRIES`, `FETCH_TIMEOUT`, `FETCH_USER_AGENT` — RSS 参数
- `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`, `AI_TEMPERATURE`, `AI_TIMEOUT`, `AI_MAX_TOKENS` — AI 参数
- `AI_MAX_INPUT_CHARS`, `AI_MIN_PER_SOURCE` — Token 预算控制
- `AI_SYSTEM_PROMPT` — 按优先级加载：`AI_SYSTEM_PROMPT` 环境变量 > `AI_PROMPT_FILE` 路径 > `prompt.txt` > 内置 fallback
- `NOTION_VERSION`, `HTTP_TIMEOUT`, `HTTP_RETRIES`, `HTTP_RETRY_BACKOFF`, `NOTIFY_TIMEOUT` — 下游参数
- 所有值均可通过环境变量覆盖，`.env` 在模块 import 时自动加载

### `fetcher.py` — RSS 抓取
- `RSS_SOURCES`: 9 个源（纽约时报中文/36氪/BBC中文/FT中文网/量子位/德国之声中文/日经中文网/爱范儿/端传媒）
- 用 `requests.get(url, timeout=30)` 先拉 XML 再 `feedparser.parse(string)`
- Fallback URL：每个源配置 `urls` 列表，逐个尝试直到成功，RSSHub 做镜像中转
- 带 `User-Agent` 头伪装浏览器，避免 403 拦截
- 每个源独立 try/except，失败只打 warning 不阻断其他源
- `_parse_published()`: 从 `published_parsed` 或 `updated_parsed` 提取 UTC 时间
- `fetch_news()` → `list[dict]`，每条含 `title/link/source/published`
- 过滤: 24h 窗口 → 黑名单关键词（娱乐/明星/八卦/体育）→ 取最新 100 条

### `summarizer.py` — AI 摘要
- `generate_report(news_list)` → `dict{headline, tags, content}`
- 模型: `moonshotai/kimi-k2.6:free` (OpenRouter)，OpenAI 兼容接口，temperature=0.5
- `_build_news_text()`: 按源轮询选取条目，32K chars 字符预算，每源保底2条
- Prompt 外部化在 `prompt.txt`，编辑器风格（见 Prompt 模块）
- AI API 429 限流自动重试 3 次（8s/16s/32s 退避），免费模型过载不立即崩溃
- 防范: content 为 None 时抛出 RuntimeError

### `prompt.txt` — AI 日报模板
- 杂志风格排版：装饰线 → 引语 → 今日概览 → 焦点分析（短期/中期/长期）→ 四大板块（## H2 响应式标题，移动端适配）
- 每条新闻 3-4 句话 + 末尾注明信源（来源：XXX），信息密度优先
- 读者定位：每天只有 5 分钟的忙碌专业人士
- 编辑风格：财新 + 端传媒，有观点有判断
- 支持切换：`AI_SYSTEM_PROMPT` 环境变量直接覆盖，或 `AI_PROMPT_FILE` 指向新文件

### `publisher.py` — Notion 发布
- `push_to_notion(report)`: 接收 summarizer 输出的 dict
- `_retry_request()`: 对 429/5xx/连接错误自动 3 次指数退避重试（1s/2s/4s），4xx 不重试并记录响应体
- `_find_today_page()`: 查询数据库是否已有当日页面，有则跳过创建（幂等性）
- `_get_database_properties()`: 查询 schema，自动发现 title/date/multi_select 列
- `_md_to_notion_blocks()`: Markdown→Notion Blocks — `##` → H2, `###` → H3, `-`/`▪`/`▸` → Bullet, `>` → Quote, `---`/装饰线 → Divider, `❶-❿` → Numbered List, `**bold**` → annotations
- 如果数据库缺少 date 或 multi_select 列，仅打日志跳过，不报错

### `main.py` — 入口
- `logging.basicConfig` 在 import 之前配置，确保所有模块日志格式统一
- `notify()`: Server酱推送，10s 超时，PUSH_KEY 未设时静默跳过
- `main()`: fetch → summarize → publish，异常时推送失败通知

### `trigger.py` — 外部精准触发器
- 调用 GitHub `repository_dispatch` API 精准触发 workflow
- 支持 `gh auth token` 自动鉴权或 `--token` 手动指定
- 配合 Windows 任务计划程序或在线 cron 服务可 8:00 准时执行

### `.github/workflows/`
- `daily_run.yml` — 主流水线：schedule (兜底) + workflow_dispatch + repository_dispatch
- `precise_trigger.yml` — 守门员：每 15 分钟检查时间，UTC 0:00-0:15 触发主流水线，确保 8:00 BJT 准点
- Secrets: `OPENROUTER_API_KEY`, `WORKFLOW_PAT`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `PUSH_KEY`

## 运行

```bash
# 本地完整运行
python main.py

# 单独测试各模块
python fetcher.py       # 打印抓取的新闻列表（含各源统计）
python summarizer.py    # 用假数据测试 AI 摘要
python publisher.py     # 打印 Notion blocks JSON（不调 API）

# 精准触发 workflow
python trigger.py                  # 用 gh CLI 自动鉴权
python trigger.py --token ghp_xxx  # 手动指定 PAT

# 单元测试
python -m pytest tests/ -v
python -m pytest tests/test_fetcher.py -v
```

## 测试

`tests/` 目录，pytest 框架，无需网络：
- `test_fetcher.py` — `_parse_published()` 时间解析（4 cases）
- `test_summarizer.py` — `_build_news_text()` token 预算控制（4 cases）
- `test_publisher.py` — `_parse_rich_text()` 粗体解析（3 cases）+ `_md_to_notion_blocks()` 块转换（6 cases）

## 依赖

**生产**
- `feedparser` — RSS 解析
- `openai` — OpenAI 兼容接口（Google AI Studio / OpenRouter 均适用）
- `requests` — Notion API / Server酱 / RSS 抓取
- `python-dotenv` — `.env` 加载

**开发** (`requirements-dev.txt`)
- `pytest` — 单元测试

## 环境变量 (`.env`)

| 变量 | 用途 |
|------|------|
| `OPENROUTER_API_KEY` | OpenRouter API 密钥 |
| `GEMINI_API_KEY` | Google AI Studio API 密钥（fallback） |
| `AI_API_KEY` | 通用 AI API 密钥（优先级最高） |
| `NOTION_TOKEN` | Notion Integration Token |
| `NOTION_DATABASE_ID` | 目标数据库 ID (32位 hex) |
| `PUSH_KEY` | Server酱 SendKey (可选) |
| `MAX_ENTRIES` | 最大抓取条数 (默认 100) |
| `FETCH_TIMEOUT` | RSS 抓取超时秒数 (默认 30) |
| `AI_MODEL` | 模型名 (默认 moonshotai/kimi-k2.6:free) |
| `AI_BASE_URL` | AI API 端点 (默认 OpenRouter) |
| `AI_TEMPERATURE` | 模型温度 (默认 0.5) |
| `AI_TIMEOUT` | AI 请求超时秒数 (默认 60) |
| `AI_MAX_TOKENS` | AI 最大输出 token (默认 8192) |
| `AI_MAX_INPUT_CHARS` | AI 输入字符预算 (默认 32000) |
| `AI_SYSTEM_PROMPT` | 直接覆盖系统 Prompt |
| `AI_PROMPT_FILE` | 自定义 Prompt 文件路径 |
| `HTTP_TIMEOUT` | Notion API 超时秒数 (默认 30) |

## 设计决策

- **Kimi K2.6 + OpenRouter**: 免费模型中文编辑能力最强，观点犀利、表达生动
- **OpenAI 兼容端点**: 统一 SDK，换 `base_url` + `api_key` 即可切换模型，零摩擦迁移
- **Notion 而非数据库**: 天然支持富文本/Markdown，零运维，移动端直接阅读
- **feedparser 而非 Scrapy**: RSS 聚合不需要爬虫框架，feedparser 轻量且够用
- **Server酱而非 PushPlus**: 简单 HTTP POST，无需 SDK
- **动态列名**: publisher 不硬编码列名，运行时从 schema 自动发现 title/date/multi_select
- **单源异常隔离**: 某个 RSS 源不可达不影响其他源，每个源独立 try/except
- **Fallback URL**: 纽约时报/日经等源在 GA 跑可能被 CDN 封 IP，RSSHub 做镜像 fallback
- **幂等发布**: 创建 Notion 页面前查询当日是否已有记录，防止重复
- **指数退避重试**: Notion API 返回 429/5xx 时自动重试，间隔 1s/2s/4s
- **Token 预算控制**: 按源轮询截断新闻列表，每源保底2条，避免单一来源占满上下文
- **Precise Trigger**: GitHub 自带 cron 不准，15分钟守门员 workflow 准点触发主流水线
- **配置外部化**: 所有可调参数集中在 config.py，支持环境变量覆盖，Prompt 可独立替换
- **User-Agent 伪装**: 部分 RSS 源封默认 UA，配置独立的 User-Agent 头
