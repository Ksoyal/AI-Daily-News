# CLAUDE.md

## 项目

AI 资讯聚合管线：RSS 抓取 → OpenAI 兼容 AI 摘要 → Notion 数据库发布 → Server酱手机推送。每日 8:00 自动运行。

## 架构

```
config.py           ── 集中配置（RSS源/AI参数/超时/预算），环境变量可覆盖
    │
    ▼
RSS feeds (12 sources)
    │
    ▼
fetcher.py          ── 30s 超时抓取、User-Agent 伪装、Fallback URL、单源异常隔离、
    │                   24h 过滤（空源回退 72h 取最新3条，回退条目豁免截断）、
    │                   关键词/链接模式黑名单、跨源近似标题去重、100条截断
    ▼
summarizer.py       ── OpenAI 兼容 API（默认 Google AI Studio / gemini-3.5-flash, 180s timeout）
    │                   Token 预算控制（32K chars, 按源轮询截断，包含 RSS 摘要与发布时效）
    │                   注入今日日期+星期、昨日日报概要（跨日连续性）
    │                   返回 {headline, tags, content}
    ▼
publisher.py        ── Markdown→Notion Blocks（H2/H3/Quote/Divider/Bullet/**bold**/[链接]），
    │                   动态发现数据库列，幂等性检查（按香港时区判"当日"，已有页面则跳过）
    │                   3次指数退避重试（429/500/502/503/504），超长 rich_text/blocks 分批写入
    │                   get_previous_report_context() 读取昨日页面供跨日承接
    ▼
main.py             ── 串联 + Server酱推送通知（10s timeout）；空新闻列表时中止并告警

trigger.py          ── 外部精准触发器（repository_dispatch API）
daily_run_guard.py  ── CI 防重跑守卫（查询当天香港日期内是否已有成功 run）
```

## 模块

### `config.py` — 集中配置
- `RSS_SOURCES`: 12 个源，每个支持 `urls` 列表（fallback 机制）与可选 `exclude_link_patterns`（按链接子串过滤非新闻栏目）
- `EXCLUDE_KEYWORDS`, `MAX_ENTRIES`, `RSS_SUMMARY_MAX_CHARS`, `FETCH_TIMEOUT`, `FETCH_USER_AGENT` — RSS 参数
- `STALE_WINDOW_HOURS` / `STALE_MAX_ENTRIES` — 空源回退窗口（默认 72h / 3 条）
- `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`, `AI_TEMPERATURE`, `AI_TIMEOUT`, `AI_MAX_TOKENS` — AI 参数
- `AI_MAX_INPUT_CHARS`, `AI_MIN_PER_SOURCE` — Token 预算控制
- `AI_SYSTEM_PROMPT` — 按优先级加载：`AI_SYSTEM_PROMPT` 环境变量 > `AI_PROMPT_FILE` 路径 > `prompt.txt` > 内置 fallback
- `NOTION_VERSION`, `HTTP_TIMEOUT`, `HTTP_RETRIES`, `HTTP_RETRY_BACKOFF`, `NOTIFY_TIMEOUT` — 下游参数
- `REPORT_TZ` — 管线对"今天"的定义，固定 UTC+8（刻意不可配置：须与 daily_run_guard.py 的硬编码口径一致）
- 数值型变量经 `_env_int()`/`_env_float()` 解析：非法值打 warning 并回落默认值，不会在 import 时崩溃
- 所有值均可通过环境变量覆盖，`.env` 在模块 import 时自动加载

### `fetcher.py` — RSS 抓取
- `RSS_SOURCES`: 12 个源（纽约时报中文/36氪/BBC中文/FT中文网/量子位/德国之声中文/爱范儿/端传媒/共同社中文/RFI中文/中央社财经/联合早报）
  - 2026-07 审计后调整：日经中文网已死源移除；rsshub.app 镜像整体 403 已放弃；新增 4 个周末也出稿的通讯社型源
- 用 `requests.get(url, timeout=30)` 先拉 XML 再 `feedparser.parse(string)`
- Fallback URL：每个源配置 `urls` 列表，逐个尝试直到解析到 entries
- 带 `User-Agent` 头伪装浏览器，避免 403 拦截
- 每个源独立 try/except，失败只打 warning 不阻断其他源
- `_parse_published()`: 从 `published_parsed` 或 `updated_parsed` 提取 UTC 时间
- `_entry_summary()`: 从 `summary/description/content` 提取纯文本摘要，清理 HTML 并按预算截断
- `fetch_news()` → `list[dict]`，每条含 `title/link/source/published/summary`
- 过滤: 24h 窗口（某源 24h 内为空则回退 `STALE_WINDOW_HOURS` 取最新 `STALE_MAX_ENTRIES` 条，周末救回低频源；回退条目豁免 MAX_ENTRIES 末尾截断）→ 黑名单关键词（娱乐/体育/票房/彩票开奖等）→ 每源 `exclude_link_patterns` 链接过滤（端传媒排除漫评/播客栏目）→ 跨源近似标题去重（归一化 + 字符 bigram Jaccard≥0.9 仅合并近乎相同标题——中文短标题在低阈值下会把"加息/降息"误判同题；胜者规则：新鲜 24h 以上者直接胜出，否则摘要长者胜）→ 取最新 100 条

### `summarizer.py` — AI 摘要
- `generate_report(news_list, previous_context=None)` → `dict{headline, tags, content}`
- 模型: 默认 `gemini-3.5-flash` (Google AI Studio OpenAI-compatible endpoint)，可通过 `AI_BASE_URL` + `AI_MODEL` + API key 切换到 OpenRouter 等提供商，temperature=0.5
- 用户消息首行注入今日日期+星期（按 `REPORT_TZ`），模型不再凭训练记忆猜日期
- `previous_context` 非空时插入【上期日报概要】块（措辞用"上期"而非"昨日"——运行中断后取回的可能是数天前的日报），要求模型对已覆盖事件只写增量（跨日去重播）
- `_format_news_item()`: 每条含 标题/链接/来源/发布时效（约N小时前）/摘要
- `_build_news_text()`: 按源轮询选取条目，32K chars 字符预算，每源保底2条
- 输入包含 RSS 摘要，减少模型只凭标题补细节的风险
- `_parse_report()`: 解析 `HEADLINE` / `TAGS` / body，支持中英文逗号分隔标签
- Prompt 外部化在 `prompt.txt`，编辑器风格（见 Prompt 模块）
- AI API 限流/连接错误/5xx（RateLimitError/APIConnectionError/InternalServerError）自动重试 3 次（8s/16s/32s 退避），免费模型过载不立即崩溃
- 防范: news_list 为空时抛 ValueError（拒绝无中生有）；choices 为空或 content 为 None/空串时抛 RuntimeError

### `prompt.txt` — AI 日报模板
- 五段式结构（`## 01-05` H2 主节，分区子栏目为 H3）：`01 今日主线` → `02 必读`（2-4 条自然段）→ `03 深读一条`（结构性分析 + 短/中/长期看点）→ `04 分区速览`（全球时政 / 科技与 AI / 财经与市场 / 值得注意，与 02/03 互斥、可整段省略）→ `05 接下来关注`（未来 24-72h 变量，落到具体日期）
- 【事实纪律】：无摘要条目禁扩写、禁记忆补数据/自加注释、直接引语须逐字、因果链须来自输入、数字口径对齐、来源白名单逐字照抄
- 【洞见要求】：禁"这表明/这标志着"开头、每条最多加粗一个短语、洞见强度匹配证据强度、清淡日允许降级
- 【排版语法】白名单与 publisher 渲染能力对齐；正文总长 2000-2800 字（5 分钟读完）
- 每条标注可点击信源（来源：[XXX](原文链接)），标题 ≤30 字，标签 2-3 个
- 支持切换：`AI_SYSTEM_PROMPT` 环境变量直接覆盖，或 `AI_PROMPT_FILE` 指向新文件

### `publisher.py` — Notion 发布
- `push_to_notion(report)`: 接收 summarizer 输出的 dict；当日已有页面时返回 `{url, skipped: True}`
- `get_previous_report_context()`: 查询今天之前最近一篇日报（标题/标签/01 主线要点），供跨日承接；任何失败返回 None，绝不阻断发布；请求走单次尝试 + 10s 超时（`_context_request`），不占用主重试预算
- `_retry_request()`: 对 429/500/502/503/504/连接错误自动 3 次指数退避重试（1s/2s/4s），4xx 不重试并记录响应体
- `_today()`: 按 `REPORT_TZ`（香港时区）取"今天"，与 daily_run_guard 的判重口径一致
- `_find_today_page()`: 查询数据库是否已有当日页面，有则跳过创建（幂等性）
- `_get_database_properties()`: 查询 schema，自动发现 title/date/multi_select 列
- `_md_to_notion_blocks()`: Markdown→Notion Blocks — `##` → H2, `###` → H3, `-`/`▪`/`▸` → Bullet, `>` → Quote, `---`/装饰线 → Divider, `❶-❿` → Numbered List, `**bold**` → annotations；标题行内的 `**` 防御性剥离
- `_parse_rich_text()`: 解析 `[文字](url)` → Notion 链接注解（http/https 之外保持字面量）+ `**粗体**`，并自动按 rich_text 长度限制拆分长文本
- 页面创建时最多携带 100 个 children blocks，剩余 blocks 通过 append children API 分批追加
- 如果数据库缺少 date 或 multi_select 列，仅打日志跳过，不报错

### `main.py` — 入口
- `logging.basicConfig` 在 import 之前配置，确保所有模块日志格式统一
- `notify()`: Server酱推送，10s 超时，PUSH_KEY 未设时静默跳过
- `main()`: fetch → (昨日概要 best-effort) → summarize → publish，异常时推送失败通知
- 空新闻列表直接中止（RuntimeError → 失败推送），防止模型无中生有
- publish 返回 `skipped=True` 时推送"已存在跳过"而非成功通知（本次生成的内容并未发布）

### `trigger.py` — 外部精准触发器
- 调用 GitHub `repository_dispatch` API 精准触发 workflow
- 支持 `gh auth token` 自动鉴权或 `--token` 手动指定
- HTTPError/URLError 均被捕获并打印 `[FAIL]`，非 200/204 显式返回失败
- 配合 Windows 任务计划程序或在线 cron 服务可 8:00 准时执行

### `daily_run_guard.py` — CI 防重跑守卫
- 仅用标准库（在 workflow 装依赖之前运行），查询 GitHub API 当天（香港时区）是否已有成功 run
- 只拦 `schedule` / `repository_dispatch` 自动触发，`workflow_dispatch` 手动触发直接放行
- API 失败时放行（宁可重跑不可漏跑），结果写入 `GITHUB_OUTPUT` 的 `skip`/`reason`
- 只能看到已完成的 run，并发场景靠 daily_run.yml 的 `concurrency` 组串行化兜底

### `.github/workflows/`
- `daily_run.yml` — 主流水线：schedule (兜底) + workflow_dispatch + repository_dispatch；`concurrency: daily-run` 组强制串行（同时最多 1 个运行 + 1 个等待，更多的 pending run 被 GitHub 自动取消并显示 Cancelled——非故障；等待的 run 执行时守卫可见前一个成功 run 而跳过）；自动触发先跑 daily_run_guard.py 判重；发布前先跑单元测试；timeout 30 分钟（覆盖 AI 重试最坏路径 ≈13 分钟）
- `precise_trigger.yml` — 守门员：每 15 分钟检查时间，UTC 00 时整个小时内触发主流水线（窗口放宽应对 cron 高峰延迟，重复 dispatch 由 concurrency + 守卫去重）；dispatch 失败会让 workflow 失败
- `tests.yml` — push / pull_request 自动运行单元测试
- Secrets: `AI_API_KEY` 或 `GEMINI_API_KEY` 或 `OPENROUTER_API_KEY`, `WORKFLOW_PAT`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `PUSH_KEY`；可选 `AI_BASE_URL`, `AI_MODEL`, `AI_TEMPERATURE`, `AI_TIMEOUT`, `AI_MAX_TOKENS`, `AI_MAX_INPUT_CHARS`

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
- `test_config.py` — 空环境变量不覆盖默认配置
- `test_fetcher.py` — `_parse_published()` 时间解析、RSS 摘要清洗、fallback URL、24h 窗口/黑名单/MAX_ENTRIES 过滤、空源 72h 回退、跨源去重、链接模式过滤
- `test_summarizer.py` — `_build_news_text()` 预算截断（保底/去摘要/截标题）、AI 输出解析、`generate_report()` 重试与空响应防护、日期首行/时效行/昨日概要块
- `test_publisher.py` — `_parse_rich_text()` 粗体/链接/长文本分片、`_md_to_notion_blocks()` 全部块类型、`_retry_request()` 重试矩阵、schema 发现、幂等跳过、昨日页面查询
- `test_main.py` — 空新闻中止、成功/跳过/失败三种通知路径、昨日概要透传
- `test_daily_run_guard.py` — 判重决策（事件类型/时区折算/API 失败放行）
- `test_prompt.py` — prompt.txt 结构约束（五段式标题等）

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
| `GEMINI_API_KEY` | Google AI Studio API 密钥 |
| `AI_API_KEY` | 通用 AI API 密钥（优先级最高） |
| `NOTION_TOKEN` | Notion Integration Token |
| `NOTION_DATABASE_ID` | 目标数据库 ID (32位 hex) |
| `PUSH_KEY` | Server酱 SendKey (可选) |
| `MAX_ENTRIES` | 最大抓取条数 (默认 100) |
| `RSS_SUMMARY_MAX_CHARS` | 每条 RSS 摘要最大字符数 (默认 600) |
| `FETCH_TIMEOUT` | RSS 抓取超时秒数 (默认 30) |
| `STALE_WINDOW_HOURS` | 空源回退窗口小时数 (默认 72) |
| `STALE_MAX_ENTRIES` | 空源回退最多取的条数 (默认 3) |
| `AI_MODEL` | 模型名 (默认 gemini-3.5-flash) |
| `AI_BASE_URL` | AI API 端点 (默认 Google AI Studio OpenAI-compatible endpoint) |
| `AI_TEMPERATURE` | 模型温度 (默认 0.5) |
| `AI_TIMEOUT` | AI 请求超时秒数 (默认 180) |
| `AI_MAX_TOKENS` | AI 最大输出 token (默认 16384) |
| `AI_MAX_INPUT_CHARS` | AI 输入字符预算 (默认 32000) |
| `AI_SYSTEM_PROMPT` | 直接覆盖系统 Prompt |
| `AI_PROMPT_FILE` | 自定义 Prompt 文件路径 |
| `HTTP_TIMEOUT` | Notion API 超时秒数 (默认 30) |
| `HTTP_RETRIES` | Notion API 重试次数 (默认 3) |
| `FETCH_USER_AGENT` | RSS 抓取 User-Agent 头 |
| `NOTIFY_TIMEOUT` | Server酱推送超时秒数 (默认 10) |
| `NOTION_MAX_CHILDREN_PER_REQUEST` | 单次请求最大 blocks 数 (默认 100) |
| `NOTION_RICH_TEXT_CHUNK_SIZE` | rich_text 分片长度 (默认 2000) |

## 设计决策

- **OpenAI 兼容端点**: 统一 SDK，默认 Google AI Studio，也可通过 `base_url` + `model` + API key 切换 OpenRouter 等提供商
- **Notion 而非数据库**: 天然支持富文本/Markdown，零运维，移动端直接阅读
- **feedparser 而非 Scrapy**: RSS 聚合不需要爬虫框架，feedparser 轻量且够用
- **Server酱而非 PushPlus**: 简单 HTTP POST，无需 SDK
- **动态列名**: publisher 不硬编码列名，运行时从 schema 自动发现 title/date/multi_select
- **单源异常隔离**: 某个 RSS 源不可达不影响其他源，每个源独立 try/except
- **Fallback URL**: 每个源支持多个候选 URL 逐个尝试（注：rsshub.app 公共实例已限流失效，2026-07 起不再依赖）
- **空源时间窗回退**: 低频源（NYT/FT/爱范儿）周末常整体落在 24h 窗口外，回退 72h 取最新 3 条，避免周末日报塌缩成单一源
- **跨源近似标题去重**: 入模前仅合并近乎相同的标题（阈值 0.9）——低阈值会把"加息/降息""收涨/收跌"这类同句式不同事实的新闻误判同题而丢新闻；措辞不同的同事件报道保留给模型做编辑性合并（prompt 要求合并并列出全部信源）
- **RSS 摘要入模**: 不只把标题交给模型，减少凭标题扩写导致的幻觉
- **日期与时效入模**: 用户消息注入今日日期+星期、每条注入发布时效，"接下来关注"能落到具体日期
- **跨日承接**: 发布前读取昨日日报概要注入 prompt，已覆盖事件只写增量，治愈跨天重播
- **可点击信源**: prompt 要求（来源：[XXX](链接)）+ publisher 解析 Markdown 链接，读者可回溯原文核实
- **幂等发布**: 创建 Notion 页面前查询当日（香港时区）是否已有记录，防止重复
- **指数退避重试**: Notion API 返回 429/500/502/503/504 时自动重试，间隔 1s/2s/4s
- **Notion 分批写入**: 规避 children blocks 和 rich_text 长度限制
- **Token 预算控制**: 按源轮询截断新闻列表，每源保底2条，避免单一来源占满上下文
- **空新闻熔断**: 全源失败时中止管线并告警，而不是让模型对着空输入编日报（幻觉页面一旦发布，幂等检查反而会锁定错误内容）
- **Precise Trigger**: GitHub 自带 cron 不准，15分钟守门员 workflow 在 UTC 00 时窗口触发主流水线；`concurrency` 组串行化 + 当天成功记录判重，双层防住精准触发和兜底 schedule 双跑
- **统一时区口径**: publisher、daily_run_guard 对"今天"统一用 UTC+8（`REPORT_TZ`），避免 UTC 与香港日错位导致写错日期或幂等失效
- **配置外部化**: 所有可调参数集中在 config.py，支持环境变量覆盖，Prompt 可独立替换
- **User-Agent 伪装**: 部分 RSS 源封默认 UA，配置独立的 User-Agent 头
