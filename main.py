import logging
import os
import sys
import traceback
import requests
from datetime import datetime

# Before any project import: config logs warnings at import time (_env_int fallbacks)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

from config import NOTIFY_TIMEOUT
from fetcher import fetch_news
from summarizer import generate_report
from publisher import push_to_notion, get_previous_report_context

logger = logging.getLogger(__name__)

PUSH_KEY = os.getenv("PUSH_KEY")
SC_URL = f"https://sctapi.ftqq.com/{PUSH_KEY}.send" if PUSH_KEY else None


def notify(title, desp=""):
    """Send push notification via Server酱."""
    if not SC_URL:
        logger.info("PUSH_KEY not set, skipping notification")
        return
    try:
        resp = requests.post(SC_URL, data={"title": title, "desp": desp}, timeout=NOTIFY_TIMEOUT)
        resp.raise_for_status()
        logger.info(f"Push sent: {title}")
    except requests.RequestException as e:
        logger.warning(f"Push failed: {e}")


def main():
    logger.info(f"=== AI-Daily-News {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

    try:
        # 1. Fetch
        logger.info("[1/3] Fetching news...")
        news = fetch_news()
        logger.info(f"Got {len(news)} entries")
        if not news:
            raise RuntimeError(
                "所有 RSS 源均未返回可用新闻，中止生成（否则模型会凭空编造日报）"
            )

        # 2. Summarize (with yesterday's report as continuity context, best-effort)
        logger.info("[2/3] Generating report...")
        prev_context = get_previous_report_context()
        if prev_context:
            logger.info("Loaded previous report context for cross-day continuity")
        report = generate_report(news, previous_context=prev_context)
        logger.info(f"Report generated: headline='{report['headline']}', "
                    f"tags={report['tags']}, body={len(report['content'])} chars")

        # 3. Publish
        logger.info("[3/3] Pushing to Notion...")
        result = push_to_notion(report)
        if result.get("skipped"):
            # A page for today already exists; this run's report was NOT published.
            logger.info("Today's page already exists — nothing published")
            notify("⏭️ 今日日报已存在，跳过发布", result.get("url", ""))
        else:
            logger.info("Published successfully")
            notify(f"✅ {report['headline']}",
                   f"共 {len(news)} 条新闻 | 标签 {'/'.join(report['tags'])}\n\n{report['content'][:500]}")
        logger.info("=== All done ===")

    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}\n\n```\n{traceback.format_exc()}\n```"
        logger.error(f"Pipeline failed: {err_msg}")
        notify("❌ AI晨报运行失败", err_msg)
        sys.exit(1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
