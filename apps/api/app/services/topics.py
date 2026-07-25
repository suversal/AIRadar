"""Topic registry powering the /topics page and the events topic filter.

Topics are a separate discovery axis from the four primary focus categories.
ASCII keywords match on word boundaries so e.g. "meta" never matches
"metadata"; CJK keywords match by substring.
"""

from __future__ import annotations

import re
from typing import Any

def _topic(topic_id: str, name: str, keywords: list[str]) -> dict[str, Any]:
    return {"id": topic_id, "name": name, "keywords": keywords}


TOPIC_GROUPS: list[dict[str, Any]] = [
    {
        "id": "models",
        "name": "模型",
        "description": "追踪主要模型系列",
        "topics": [
            _topic("gpt", "GPT", ["gpt", "o1", "o3", "o4"]),
            _topic("claude", "Claude", ["claude"]),
            _topic("gemini", "Gemini", ["gemini"]),
            _topic("llama", "Llama", ["llama"]),
            _topic("grok", "Grok", ["grok"]),
            _topic("deepseek", "DeepSeek", ["deepseek"]),
            _topic("qwen", "Qwen / 通义", ["qwen", "通义"]),
            _topic("mistral", "Mistral", ["mistral"]),
            _topic(
                "cn_models",
                "国产模型",
                ["kimi", "moonshot", "智谱", "glm", "minimax", "豆包", "文心", "混元"],
            ),
        ],
    },
    {
        "id": "products",
        "name": "产品与工具",
        "description": "追踪常用 AI 产品和开发工具",
        "topics": [
            _topic("chatgpt", "ChatGPT", ["chatgpt"]),
            _topic("claude_code", "Claude Code", ["claude code"]),
            _topic("copilot", "GitHub Copilot", ["github copilot", "copilot"]),
            _topic("cursor", "Cursor", ["cursor"]),
            _topic("perplexity", "Perplexity", ["perplexity"]),
            _topic("huggingface", "Hugging Face", ["hugging face", "huggingface"]),
            _topic("sora", "Sora", ["sora"]),
            _topic("ai_search", "AI 搜索", ["ai search", "ai 搜索", "智能搜索"]),
        ],
    },
    {
        "id": "directions",
        "name": "技术方向",
        "description": "按技术领域深挖",
        "topics": [
            _topic("agents", "Agent 智能体", ["agent", "agents", "智能体", "mcp"]),
            _topic("coding", "AI 编码", ["coding", "code", "编码", "编程", "程序员"]),
            _topic(
                "multimodal",
                "多模态",
                ["multimodal", "vision", "多模态", "图像", "视频生成", "文生图", "文生视频"],
            ),
            _topic("reasoning", "推理能力", ["reasoning", "推理"]),
            _topic("opensource", "开源生态", ["open source", "open-source", "开源"]),
            _topic("robotics", "机器人具身", ["robot", "robotics", "机器人", "具身"]),
            _topic("voice", "语音", ["voice", "speech", "audio", "语音"]),
            _topic(
                "safety", "安全对齐", ["safety", "alignment", "安全", "对齐", "红队", "red team"]
            ),
        ],
    },
    {
        "id": "companies",
        "name": "公司与行业",
        "description": "追踪公司和产业参与者",
        "topics": [
            _topic("openai", "OpenAI", ["openai", "chatgpt", "gpt", "sora"]),
            _topic("anthropic", "Anthropic", ["anthropic", "claude"]),
            _topic("google", "Google / DeepMind", ["google", "deepmind", "谷歌", "gemini"]),
            _topic("meta", "Meta", ["meta", "llama"]),
            _topic("xai", "xAI", ["xai", "grok"]),
            _topic("microsoft", "Microsoft", ["microsoft", "微软", "azure"]),
            _topic("nvidia", "NVIDIA", ["nvidia", "英伟达", "cuda"]),
            _topic("alibaba", "阿里巴巴", ["alibaba", "阿里"]),
            _topic("bytedance", "字节跳动", ["bytedance", "字节"]),
            _topic("baidu", "百度", ["baidu", "百度"]),
            _topic("tencent", "腾讯", ["tencent", "腾讯"]),
        ],
    },
]

_TOPICS_BY_ID = {
    topic["id"]: topic for group in TOPIC_GROUPS for topic in group["topics"]
}


def topic_by_id(topic_id: str) -> dict[str, Any] | None:
    return _TOPICS_BY_ID.get(topic_id)


def _keyword_matches(text: str, keyword: str) -> bool:
    if keyword.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None
    return keyword in text


def _item_text(item: dict[str, Any]) -> str:
    parts = [
        str(item.get("title") or ""),
        str(item.get("one_line_summary") or ""),
        str(item.get("summary") or ""),
        " ".join(str(tag) for tag in item.get("tags") or []),
    ]
    return " ".join(parts).lower()


def item_matches_topic(item: dict[str, Any], topic: dict[str, Any] | None) -> bool:
    if topic is None:
        return False
    text = _item_text(item)
    return any(_keyword_matches(text, keyword) for keyword in topic["keywords"])


def build_topics_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    groups = []
    for group in TOPIC_GROUPS:
        topics = []
        for topic in group["topics"]:
            count = sum(1 for item in items if item_matches_topic(item, topic))
            topics.append({"id": topic["id"], "name": topic["name"], "count": count})
        groups.append(
            {
                "id": group["id"],
                "name": group["name"],
                "description": group["description"],
                "topics": topics,
            }
        )
    return {"groups": groups, "article_count": len(items)}
