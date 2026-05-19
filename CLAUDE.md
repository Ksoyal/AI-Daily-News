# CLAUDE.md

## 项目概述
AI 资讯聚合项目：从 RSS 源抓取 AI 相关新闻，通过 OpenRouter API 进行 AI 摘要，存入 Notion 数据库，并支持手机推送通知。

## 今日完成 (2026-05-19)

### 核心模块全部实现并测试通过
- `fetcher.py` — RSS 抓取：feedparser 拉取 5 个源（纽约时报中文/36氪/BBC中文/FT中文网/量子位），24h 时区过滤，关键词黑名单过滤（娱乐/明星/八卦/体育），30 条安全阀截断
- `summarizer.py` — AI 摘要：OpenRouter + deepseek/deepseek-v4-flash:free，System Prompt 严格限定四大板块（全球时政/科技与AI/财经与市场/社会热点），temperature=0.3
- `publisher.py` — Notion 发布：Markdown→Notion Blocks 解析器（heading_2 / bulleted_list_item / bold），自动查询 title 列名，创建 Page 并写入正文
- `main.py` — 工作流串联：fetch → summarize → publish，Server酱 成功/失败推送通知
- `.github/workflows/daily_run.yml` — 每天 UTC 0:00（北京时间 8:00）自动运行，支持 workflow_dispatch 手动触发

## 当前 Bug
- （已修复）联合早报 RSS → 替换为纽约时报中文 `https://cn.nytimes.com/rss/`

## 核心架构决策
- 使用 OpenRouter 作为 AI API 网关（OpenAI 兼容接口），模型 `deepseek/deepseek-v4-flash:free`
- 使用 Notion 作为内容存储后端
- 使用 feedparser 解析 RSS，不引入 Scrapy 等重型框架
- 推送通知使用 Server酱（sctapi.ftqq.com），不是 PushPlus

## 待办
1. ~~修复或替换联合早报 RSS 源 URL~~ ✅ 已替换为纽约时报中文
2. ~~添加日志模块，替换 print 为 logging~~ ✅ 已完成
3. ~~添加更多高质量 RSS 源~~ ✅ 已新增 FT中文网、量子位，共5个源
4. ~~将仓库推送到 GitHub 并配置 Secrets~~ ✅ 已推送至 https://github.com/Ksoyal/AI-Daily-News，Secrets 全部配置完毕
