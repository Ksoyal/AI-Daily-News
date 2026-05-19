import logging
import os
import re
import sys
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

from config import NOTION_VERSION, HTTP_TIMEOUT, HTTP_RETRIES, HTTP_RETRY_BACKOFF

load_dotenv()

logger = logging.getLogger(__name__)


def _retry_request(method, url, **kwargs):
    """Wrapper around requests.request with retry on 429/5xx."""
    last_exc = None
    for attempt in range(HTTP_RETRIES + 1):
        try:
            resp = requests.request(method, url, timeout=HTTP_TIMEOUT, **kwargs)
            if resp.status_code in (429, 502, 503, 504) and attempt < HTTP_RETRIES:
                delay = HTTP_RETRY_BACKOFF[attempt]
                logger.warning(f"{method} {url} → {resp.status_code}, retrying in {delay}s (attempt {attempt + 1}/{HTTP_RETRIES})")
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_exc = e
            if attempt < HTTP_RETRIES:
                delay = HTTP_RETRY_BACKOFF[attempt]
                logger.warning(f"{method} {url} → {e}, retrying in {delay}s (attempt {attempt + 1}/{HTTP_RETRIES})")
                time.sleep(delay)
            else:
                raise last_exc


def _parse_rich_text(text):
    """Parse `**bold**` markers into Notion rich_text annotations array."""
    parts = re.split(r"\*\*(.*?)\*\*", text)
    rich_text = []
    for i, part in enumerate(parts):
        if not part:
            continue
        rich_text.append({
            "type": "text",
            "text": {"content": part},
            "annotations": {"bold": (i % 2 == 1)},
        })
    return rich_text


def _md_to_notion_blocks(md_text):
    """Convert the daily-report Markdown into Notion block objects."""
    blocks = []
    for line in md_text.strip().split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            blocks.append({
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": stripped[3:]}}]
                },
            })
        elif stripped.startswith("- "):
            blocks.append({
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": _parse_rich_text(stripped[2:])
                },
            })
        else:
            blocks.append({
                "type": "paragraph",
                "paragraph": {
                    "rich_text": _parse_rich_text(stripped)
                },
            })
    return blocks


def _get_database_properties(token, database_id):
    """Fetch database schema and return (title_col, date_col, multi_select_col).

    title_col is mandatory — raises ValueError if missing.
    date_col and multi_select_col are optional — returns None if no matching column.
    """
    url = f"https://api.notion.com/v1/databases/{database_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }
    resp = _retry_request("GET", url, headers=headers)
    title_col = None
    date_col = None
    multi_select_col = None
    for name, prop in resp.json().get("properties", {}).items():
        ptype = prop.get("type")
        if ptype == "title" and title_col is None:
            title_col = name
        elif ptype == "date" and date_col is None:
            date_col = name
        elif ptype == "multi_select" and multi_select_col is None:
            multi_select_col = name
    if title_col is None:
        raise ValueError("Database schema has no 'title' property — check NOTION_DATABASE_ID")
    return title_col, date_col, multi_select_col


def _find_today_page(token, database_id, date_col, today):
    """Check if a page with today's date already exists in the database.

    Returns the page URL if found, None otherwise.
    """
    if not date_col:
        return None

    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    body = {
        "filter": {
            "property": date_col,
            "date": {"equals": today},
        }
    }
    resp = _retry_request("POST", url, headers=headers, json=body)
    results = resp.json().get("results", [])
    if results:
        page = results[0]
        return page.get("url", f"https://notion.so/{page['id'].replace('-', '')}")
    return None


def push_to_notion(report):
    """Create a new page in the Notion database with the daily report.

    Skips creation if a page with today's date already exists (idempotent).

    Args:
        report: dict with keys:
            - headline (str):  AI-generated page title
            - tags (list[str]):  2-3 topic tags for multi_select
            - content (str):  Markdown daily report body
    """
    token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")
    if not token or not database_id:
        raise ValueError("NOTION_TOKEN and NOTION_DATABASE_ID must be set in .env")

    today = datetime.now().strftime("%Y-%m-%d")
    title_col, date_col, tags_col = _get_database_properties(token, database_id)

    # Idempotency: skip if today's page already exists
    existing_url = _find_today_page(token, database_id, date_col, today)
    if existing_url:
        logger.info(f"Today's page already exists: {existing_url} — skipping")
        return {"url": existing_url, "skipped": True}

    blocks = _md_to_notion_blocks(report["content"])

    # Build page properties dynamically
    properties = {
        title_col: {
            "title": [{"text": {"content": report["headline"]}}]
        }
    }

    if date_col:
        properties[date_col] = {"date": {"start": today}}
    else:
        logger.info("No date property found in database — skipping 发布日期")

    if tags_col and report.get("tags"):
        properties[tags_col] = {
            "multi_select": [{"name": tag} for tag in report["tags"]]
        }
    elif not tags_col:
        logger.info("No multi_select property found in database — skipping 核心话题")

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    body = {
        "parent": {"database_id": database_id},
        "properties": properties,
        "children": blocks,
    }

    resp = _retry_request("POST", url, headers=headers, json=body)
    page = resp.json()
    logger.info(f"Notion page created: {page.get('url', page.get('id'))}")
    return page


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Fake markdown report matching the summarizer output format
    fake_md = """\
## 🌟 一句话晨报
联合国通过首个全球AI治理决议，为人工智能发展确立国际规则框架。

## 🌍 全球时政
- **联合国通过首个全球AI治理决议**：联合国大会批准首份全球人工智能治理决议。（来源：联合早报）
- **欧盟通过新AI法案**：欧盟正式通过《人工智能法案》，对高风险AI应用实施严苛监管。（来源：BBC中文）

## 💻 科技与 AI
- **OpenAI发布GPT-6**：推理能力再次突破，复杂推理和多步骤任务显著提升。（来源：36氪）

## 📈 财经与市场
- **美股三大指数集体收涨**：科技股领涨，纳斯达克指数涨幅居前。（来源：BBC中文）

## 🔥 社会热点
- **北京持续高温**：多地气温突破40℃，市民需注意防暑。（来源：联合早报）"""

    # Dry-run: show parsed blocks without calling Notion API
    print("=" * 60)
    print("Parsed Notion blocks (dry-run):")
    print("=" * 60)
    import json
    print(json.dumps(_md_to_notion_blocks(fake_md), ensure_ascii=False, indent=2))
