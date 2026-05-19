import logging
import os
import sys
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个资深的全球资讯主编。请将输入的新闻列表进行去重、提炼，并严格按照以下 Markdown 格式输出日报。
【输出格式要求】
1. 必须使用标准的 Markdown 语法（只使用 #, ##, -, **）。
2. 不要输出任何开场白或结尾语，直接输出正文。
3. 严格按照以下板块组织内容，如果某个板块没有相关新闻，则直接省略该板块：

## 🌟 一句话晨报
（用一句话总结今天全球最重要的一件事）

## 🌍 全球时政
- **[新闻标题]**：精简的一句话摘要。（来源：XXX）

## 💻 科技与 AI
- **[新闻标题]**：精简的一句话摘要。（来源：XXX）

## 📈 财经与市场
- **[新闻标题]**：精简的一句话摘要。（来源：XXX）

## 🔥 社会热点
- **[新闻标题]**：精简的一句话摘要。（来源：XXX）"""


def generate_report(news_list):
    """Send news list to LLM and return a formatted Markdown daily report."""
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )

    news_text = "\n\n".join(
        f"[{i + 1}] 标题：{item['title']}\n链接：{item['link']}\n来源：{item['source']}"
        for i, item in enumerate(news_list)
    )

    resp = client.chat.completions.create(
        model="deepseek/deepseek-v4-flash:free",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"以下是今日新闻列表，请生成日报：\n\n{news_text}"},
        ],
        temperature=0.3,
    )

    choice = resp.choices[0]
    finish_reason = choice.finish_reason
    content = choice.message.content

    logger.info(f"OpenRouter response: model={resp.model}, finish_reason={finish_reason}, "
                f"content_length={len(content) if content else 0}, "
                f"usage={resp.usage}")

    if content is None:
        logger.error(f"Empty content from OpenRouter. finish_reason={finish_reason}, "
                     f"message={choice.message}")
        raise RuntimeError(
            f"OpenRouter returned empty content (finish_reason={finish_reason}). "
            "The free model may be overloaded — try switching to a paid model."
        )

    return content


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    # Fake data for testing the prompt output
    fake_news = [
        {
            "title": "联合国通过首个全球AI治理决议",
            "link": "https://example.com/ai-governance",
            "source": "联合早报",
        },
        {
            "title": "OpenAI发布GPT-6，推理能力再次突破",
            "link": "https://example.com/gpt6",
            "source": "36氪",
        },
        {
            "title": "美股三大指数集体收涨，科技股领涨",
            "link": "https://example.com/us-stock",
            "source": "BBC中文",
        },
        {
            "title": "北京持续高温，多地气温突破40℃",
            "link": "https://example.com/heatwave",
            "source": "联合早报",
        },
        {
            "title": "欧盟通过新AI法案，严格监管高风险应用",
            "link": "https://example.com/eu-ai-act",
            "source": "BBC中文",
        },
    ]

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    report = generate_report(fake_news)
    print(report)  # output the actual report content, not a log
