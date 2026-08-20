"""Topic registry powering /topics, /topics/[slug] and the events topic filter.

2026-08-20 改版:四组砍成两组。

- entities   公司与模型:一个主体一张卡。公司和它的模型/产品合并("Anthropic /
             Claude"),因为关键词层面根本区分不出"公司新闻"和"模型新闻",
             旧版的模型组和公司组一直是两份入口、一份内容。
- directions 技术方向:按技术领域深挖。

刻意不设"内容形态"组(模型发布/论文/教程…)——那是 focus 分类(taxonomy)
的职责,同一个轴摆两处只会互相稀释。

匹配语义:只扫 标题+一句话提要+tags,不扫全文摘要。摘要里顺嘴提一句
Claude 不代表这条"关于" Claude——旧版扫摘要导致 Agent 主题吞掉全库 26%。
这仍是关键词兜底方案;计划中的 P1 会切到入库时 AI 打标(topic_ids),
届时这里的关键词只服务无标签的存量数据。

ASCII 关键词按词边界匹配(避免 "meta" 命中 "metadata"),CJK 按子串。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _topic(topic_id: str, name: str, description: str, keywords: list[str]) -> dict[str, Any]:
    return {"id": topic_id, "name": name, "description": description, "keywords": keywords}


TOPIC_GROUPS: list[dict[str, Any]] = [
    {
        "id": "entities",
        "name": "公司与模型",
        "description": "一个主体一张卡:模型、产品和公司动态合并追踪",
        "topics": [
            _topic(
                "openai",
                "OpenAI / GPT",
                "OpenAI 的全部动态：GPT 系列模型、ChatGPT 与 Sora 产品、公司战略与人事的持续追踪。",
                ["openai", "chatgpt", "gpt", "sora", "o3", "o4"],
            ),
            _topic(
                "anthropic",
                "Anthropic / Claude",
                "Anthropic 的全部动态：Claude 系列模型、Claude Code 与安全研究路线的持续追踪。",
                ["anthropic", "claude"],
            ),
            _topic(
                "google",
                "Google / Gemini",
                "Google 与 DeepMind 的 AI 动态：Gemini 系列、Veo 视频模型、研究成果与产品生态。",
                ["google", "deepmind", "gemini", "谷歌", "veo", "notebooklm"],
            ),
            _topic(
                "deepseek",
                "DeepSeek",
                "DeepSeek（深度求索）的模型发布、开源权重与技术报告——开源模型性价比之战的风向标。",
                ["deepseek", "深度求索"],
            ),
            _topic(
                "qwen",
                "通义 Qwen / 阿里",
                "阿里的 AI 生态：通义千问 Qwen 全谱系开源发布、百炼平台与阿里云的模型布局。",
                ["qwen", "通义", "千问", "阿里", "alibaba"],
            ),
            _topic(
                "kimi",
                "Kimi / 月之暗面",
                "月之暗面 Kimi 的模型与产品：K 系列开源模型、长上下文技术与产品演进。",
                ["kimi", "moonshot", "月之暗面"],
            ),
            _topic(
                "zhipu",
                "智谱 GLM",
                "智谱 GLM 系列的开源发布、代码与推理能力迭代、商业化与生态进展。",
                ["智谱", "glm", "zhipu"],
            ),
            _topic(
                "minimax",
                "MiniMax",
                "MiniMax 的模型与产品动态：M 系列大模型、语音与多模态能力、开源进展。",
                ["minimax", "海螺"],
            ),
            _topic(
                "bytedance",
                "字节 / 豆包",
                "字节跳动的 AI 布局：豆包大模型、火山引擎与消费级 AI 产品矩阵。",
                ["bytedance", "字节", "豆包", "doubao", "火山引擎", "即梦"],
            ),
            _topic(
                "tencent",
                "腾讯 / 混元",
                "腾讯的 AI 动态：混元大模型、微信生态的 AI 化与开源策略。",
                ["tencent", "腾讯", "混元", "hunyuan"],
            ),
            _topic(
                "baidu",
                "百度 / 文心",
                "百度的 AI 动态：文心大模型、搜索的 AI 重构与自动驾驶进展。",
                ["baidu", "百度", "文心", "ernie"],
            ),
            _topic(
                "xai",
                "xAI / Grok",
                "马斯克 xAI 与 Grok 系列的动态：模型迭代、算力扩张与 X 平台整合。",
                ["xai", "grok"],
            ),
            _topic(
                "meta",
                "Meta / Llama",
                "Meta 的 AI 动态：Llama 开源模型系列与超级智能实验室的进展。",
                ["meta", "llama"],
            ),
            _topic(
                "microsoft",
                "Microsoft / Copilot",
                "微软的 AI 布局：Copilot 全家桶、Azure AI 基础设施与 OpenAI 合作关系。",
                ["microsoft", "微软", "azure", "copilot"],
            ),
            _topic(
                "nvidia",
                "NVIDIA 英伟达",
                "英伟达的 AI 芯片与生态：GPU 新品、CUDA 生态与 AI 算力市场的风向。",
                ["nvidia", "英伟达", "cuda"],
            ),
            _topic(
                "huggingface",
                "Hugging Face",
                "Hugging Face 社区动态：热门模型与数据集、排行榜变化——开源生态的晴雨表。",
                ["hugging face", "huggingface"],
            ),
            _topic(
                "cursor",
                "Cursor",
                "Cursor 编辑器的产品迭代与生态动态——AI 编码工具竞争中最受关注的玩家之一。",
                ["cursor"],
            ),
        ],
    },
    {
        "id": "directions",
        "name": "技术方向",
        "description": "按技术领域深挖：Agent、多模态、具身智能……",
        "topics": [
            _topic(
                "agents",
                "Agent 智能体",
                "让模型自主规划、调用工具、完成多步任务：Agent 框架、MCP 生态与评测基准的动态。",
                ["agent", "agents", "智能体", "mcp", "多智能体"],
            ),
            _topic(
                "coding",
                "AI 编码",
                "AI 写代码的一切：编码助手、Vibe Coding、代码模型评测与开发工作流变革。",
                ["coding", "code", "编码", "编程", "程序员", "vibe coding"],
            ),
            _topic(
                "reasoning",
                "推理能力",
                "思维链与推理模型的进展：数学、逻辑与科学推理基准的突破与争议。",
                ["reasoning", "推理"],
            ),
            _topic(
                "multimodal",
                "多模态",
                "文本之外的能力：视觉理解、图像与视频生成、创作工具生态的模型与产品进展。",
                [
                    "multimodal",
                    "vision",
                    "多模态",
                    "文生图",
                    "文生视频",
                    "图像生成",
                    "视频生成",
                    "图像编辑",
                ],
            ),
            _topic(
                "voice",
                "语音与音频",
                "AI 语音与音频的进展：语音合成、实时对话、音乐生成与音频理解。",
                ["voice", "speech", "audio", "语音", "音频", "音乐生成"],
            ),
            _topic(
                "embodied",
                "机器人具身",
                "AI 走进物理世界：人形机器人、具身基础模型与真实环境操作能力的进展。",
                ["robot", "robotics", "机器人", "具身", "人形"],
            ),
            _topic(
                "opensource",
                "开源生态",
                "权重开放、社区项目与开源工具链：开源与闭源的力量消长。",
                ["open source", "open-source", "开源"],
            ),
            _topic(
                "safety",
                "安全对齐",
                "AI 安全与对齐：越狱与防御、模型行为研究、安全评测与治理框架的进展。",
                ["safety", "alignment", "安全", "对齐", "红队", "red team", "越狱", "jailbreak"],
            ),
        ],
    },
]

# 旧版(四组时代)的主题 id → 新 id。/all?topic= 的旧链接可能被外部收藏,
# 静默失效会变成"筛选结果为空"的假象,所以这里显式重定向。
# 旧的 cn_models / mistral / perplexity / ai_search 没有语义等价的新主题,
# 不映射——topic_by_id 返回 None,行为等同筛一个不存在的主题。
_LEGACY_ALIASES: dict[str, str] = {
    "gpt": "openai",
    "chatgpt": "openai",
    "sora": "openai",
    "claude": "anthropic",
    "claude_code": "anthropic",
    "gemini": "google",
    "llama": "meta",
    "grok": "xai",
    "copilot": "microsoft",
    "alibaba": "qwen",
    "robotics": "embodied",
}

_TOPICS_BY_ID = {
    topic["id"]: topic for group in TOPIC_GROUPS for topic in group["topics"]
}

_GROUP_BY_TOPIC_ID = {
    topic["id"]: group for group in TOPIC_GROUPS for topic in group["topics"]
}


def topic_by_id(topic_id: str) -> dict[str, Any] | None:
    resolved = _LEGACY_ALIASES.get(topic_id, topic_id)
    return _TOPICS_BY_ID.get(resolved)


def group_of_topic(topic_id: str) -> dict[str, Any] | None:
    resolved = _LEGACY_ALIASES.get(topic_id, topic_id)
    return _GROUP_BY_TOPIC_ID.get(resolved)


def _keyword_matches(text: str, keyword: str) -> bool:
    if keyword.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None
    return keyword in text


def _item_text(item: dict[str, Any]) -> str:
    # 刻意不含 summary(全文摘要):主题成员的语义是"关于 X",
    # 标题/提要/标签才承载"这条主要在讲什么"。
    parts = [
        str(item.get("title") or ""),
        str(item.get("one_line_summary") or ""),
        " ".join(str(tag) for tag in item.get("tags") or []),
    ]
    return " ".join(parts).lower()


def item_matches_topic(item: dict[str, Any], topic: dict[str, Any] | None) -> bool:
    if topic is None:
        return False
    text = _item_text(item)
    return any(_keyword_matches(text, keyword) for keyword in topic["keywords"])


def _item_date(item: dict[str, Any]) -> date | None:
    """条目的上海时区日期,周环比窗口按它切。published_at 在仓库层是
    datetime,进了 FastAPI 序列化后是 ISO 字符串,两种都要接。"""
    value = item.get("published_at")
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(_SHANGHAI).date()
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_SHANGHAI).date()


def _published_sort_key(item: dict[str, Any]) -> str:
    return str(item.get("published_at") or "")


def build_topics_payload(items: list[dict[str, Any]], *, today: date) -> dict[str, Any]:
    """索引页 payload。计数一律用精选口径(selected=True):索引页卡片写的是
    "精选 N 条",拿全量收录数冒充会虚一倍以上。week/prev_week 给前端做
    周环比信号(异动箭头),latest_published_at 给"最近更新"。"""
    selected_items = [item for item in items if item.get("selected")]
    week_start = today - timedelta(days=6)
    prev_week_start = today - timedelta(days=13)

    groups = []
    for group in TOPIC_GROUPS:
        topics = []
        for topic in group["topics"]:
            matched = [item for item in selected_items if item_matches_topic(item, topic)]
            week_count = 0
            prev_week_count = 0
            latest: date | None = None
            for item in matched:
                item_date = _item_date(item)
                if item_date is None:
                    continue
                if item_date >= week_start:
                    week_count += 1
                elif item_date >= prev_week_start:
                    prev_week_count += 1
                if latest is None or item_date > latest:
                    latest = item_date
            topics.append(
                {
                    "id": topic["id"],
                    "name": topic["name"],
                    "description": topic["description"],
                    "count": len(matched),
                    "week_count": week_count,
                    "prev_week_count": prev_week_count,
                    "latest_published_at": latest.isoformat() if latest else None,
                }
            )
        groups.append(
            {
                "id": group["id"],
                "name": group["name"],
                "description": group["description"],
                "topics": topics,
            }
        )
    return {"groups": groups, "article_count": len(selected_items)}


FOCUS_WINDOW_DAYS = 14
FOCUS_LIMIT = 5


def build_topic_detail_payload(
    topic_id: str,
    items: list[dict[str, Any]],
    *,
    today: date,
    limit: int = 60,
    offset: int = 0,
) -> dict[str, Any] | None:
    """详情页 payload:页头元信息 + 近期焦点 + 精选时间线(分页)。

    items 应是"全量收录"(含未精选)——页头的 收录/精选 双计数需要两个口径。
    时间线只放精选;未精选的出口是页面底部指回 /all?topic= 的链接。
    近期焦点 = 近 FOCUS_WINDOW_DAYS 天、多源(source_count≥2)、事件代表条
    (is_main,避免同一事件的成员刷满榜单),按 信源数、时间 排序取前几条。
    """
    topic = topic_by_id(topic_id)
    if topic is None:
        return None
    group = group_of_topic(topic_id)

    matched = [item for item in items if item_matches_topic(item, topic)]
    selected = [item for item in matched if item.get("selected")]
    selected.sort(key=_published_sort_key, reverse=True)

    focus_start = today - timedelta(days=FOCUS_WINDOW_DAYS - 1)
    focus_candidates = [
        item
        for item in selected
        if item.get("is_main")
        and (item.get("source_count") or 1) >= 2
        and (_item_date(item) or date.min) >= focus_start
    ]
    focus_candidates.sort(
        key=lambda item: ((item.get("source_count") or 1), _published_sort_key(item)),
        reverse=True,
    )

    latest = _item_date(selected[0]) if selected else None
    return {
        "topic": {
            "id": topic["id"],
            "name": topic["name"],
            "description": topic["description"],
            "group_id": group["id"] if group else None,
            "group_name": group["name"] if group else None,
        },
        "total_count": len(matched),
        "selected_count": len(selected),
        "latest_published_at": latest.isoformat() if latest else None,
        "focus": focus_candidates[:FOCUS_LIMIT],
        "items": selected[offset : offset + limit],
        "limit": limit,
        "offset": offset,
    }
