import logging
import os
import re
import sys
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

NOTION_VERSION = "2022-06-28"


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


def _get_title_property_name(token, database_id):
    """Fetch database schema and return the name of the title column."""
    url = f"https://api.notion.com/v1/databases/{database_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    for name, prop in resp.json().get("properties", {}).items():
        if prop.get("type") == "title":
            return name
    raise ValueError("Database schema has no 'title' property — check NOTION_DATABASE_ID")


def push_to_notion(markdown_content):
    """Create a new page in the Notion database with the daily report.

    Page title is set to e.g. '2026-05-19 AI 晨报'.
    The markdown body is converted to Notion blocks and written as page children.
    """
    token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")
    if not token or not database_id:
        raise ValueError("NOTION_TOKEN and NOTION_DATABASE_ID must be set in .env")

    today = datetime.now().strftime("%Y-%m-%d")
    title_name = _get_title_property_name(token, database_id)
    blocks = _md_to_notion_blocks(markdown_content)

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    body = {
        "parent": {"database_id": database_id},
        "properties": {
            title_name: {
                "title": [{"text": {"content": f"{today} AI 晨报"}}]
            }
        },
        "children": blocks,
    }

    try:
        resp = requests.post(url, headers=headers, json=body)
        resp.raise_for_status()
        page = resp.json()
        logger.info(f"Notion page created: {page.get('url', page.get('id'))}")
        return page
    except requests.exceptions.RequestException as e:
        logger.error(f"Notion API request failed: {e}")
        if e.response is not None:
            logger.error(f"Status: {e.response.status_code}")
            logger.error(f"Body: {e.response.text}")
        raise


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
