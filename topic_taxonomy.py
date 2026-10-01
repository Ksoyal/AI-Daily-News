"""Reviewed topic vocabulary shared by generation and Notion publishing."""

import json
import re
import unicodedata
from pathlib import Path


def _clean_tag(value):
    value = unicodedata.normalize("NFKC", value).strip().lstrip("#").strip()
    value = re.sub(r"\s+", " ", value)
    # Normalize spacing at Latin/Chinese boundaries, not between English words.
    return re.sub(
        r"(?<=[A-Za-z0-9]) (?=[\u3400-\u9fff])|(?<=[\u3400-\u9fff]) (?=[A-Za-z0-9])",
        "", value,
    )


def _load_taxonomy(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("Unsupported topic taxonomy version")
    canonical = data["canonical_tags"]
    if not isinstance(canonical, list) or not canonical:
        raise ValueError("Topic taxonomy must contain canonical_tags")
    lookup = {}
    for tag in canonical:
        if not isinstance(tag, str) or not tag or tag != _clean_tag(tag) or "," in tag:
            raise ValueError(f"Invalid canonical topic: {tag!r}")
        key = tag.casefold()
        if key in lookup:
            raise ValueError(f"Duplicate canonical topic: {tag!r}")
        lookup[key] = tag
    for alias, target in data["aliases"].items():
        if target not in canonical:
            raise ValueError(f"Unknown alias target: {target!r}")
        key = _clean_tag(alias).casefold()
        if not key or key in lookup and lookup[key] != target:
            raise ValueError(f"Conflicting topic alias: {alias!r}")
        lookup[key] = target
    return tuple(canonical), lookup


CANONICAL_TAGS, _LOOKUP = _load_taxonomy(Path(__file__).with_name("topic_taxonomy.json"))


def normalize_tags(tags):
    """Return up to 3 unique approved tags and unrecognized review candidates.

    Unknown names are never guessed, merged semantically, or added to Notion.
    Deduplicate before applying the limit so spelling variants don't waste slots.
    """
    if tags is None:
        return [], []
    if not isinstance(tags, (list, tuple)):
        raise ValueError("Topic tags must be a list or tuple")
    accepted, rejected = [], []
    for raw in tags:
        canonical = _LOOKUP.get(_clean_tag(raw).casefold()) if isinstance(raw, str) else None
        if canonical:
            if canonical not in accepted:
                accepted.append(canonical)
        elif raw not in rejected:
            rejected.append(raw)
    return accepted[:3], rejected


def topic_prompt():
    """Inject the same allowlist even when an environment prompt overrides the file."""
    return (
        "【核心话题规范词表】\n"
        "TAGS 只选下面词表中的 2-3 个规范名称，逐字输出，不加 #，不另造同义词。"
        "优先复用已有主题；低频不代表同义。AI治理、AI监管、AI安全、AI伦理，"
        "具身智能与物理AI，中美关系、中美博弈、中美贸易分别有独立含义，不能互换。"
        "词表没有合适主题时少选或留空，不得用无关标签凑数；新闻正文仍按原规则生成。"
        "新主题只能在人工确认确有独立含义并更新词表后使用。\n"
        + "、".join(CANONICAL_TAGS)
    )
