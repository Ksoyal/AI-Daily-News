import logging
import os
import sys
import traceback
import requests
from datetime import datetime
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

load_dotenv()

from fetcher import fetch_news
from summarizer import generate_report
from publisher import push_to_notion

logger = logging.getLogger(__name__)

PUSH_KEY = os.getenv("PUSH_KEY")
SC_URL = f"https://sctapi.ftqq.com/{PUSH_KEY}.send" if PUSH_KEY else None


def notify(title, desp=""):
    """Send push notification via Server酱."""
    if not SC_URL:
        logger.info("PUSH_KEY not set, skipping notification")
        return
    try:
        resp = requests.post(SC_URL, data={"title": title, "desp": desp})
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

        # 2. Summarize
        logger.info("[2/3] Generating report...")
        report = generate_report(news)
        logger.info(f"Report generated: headline='{report['headline']}', "
                    f"tags={report['tags']}, body={len(report['content'])} chars")

        # 3. Publish
        logger.info("[3/3] Pushing to Notion...")
        push_to_notion(report)
        logger.info("Published successfully")

        # Success notification
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
