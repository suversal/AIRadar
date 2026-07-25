from __future__ import annotations

import hashlib
import json
import logging
import re
import os
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any

from app.models.domain import PrefilterResult, ScoreDimensions, ScoringResult
from app.services.period_summary_service import parse_period_summary_payload
from app.services.taxonomy import resolve_focus_category

logger = logging.getLogger(__name__)

AI_KEYWORDS = {
    "ai",
    "agent",
    "agents",
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "deepseek",
    "llm",
    "model",
    "models",
    "machine learning",
    "neural",
    "transformer",
    "diffusion",
    "hugging face",
    "arxiv",
}


def _clamp_dimension(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return max(0.0, min(10.0, numeric))


def _clamp_confidence(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return max(0.0, min(1.0, numeric))


def parse_prefilter_payload(payload: dict[str, Any]) -> PrefilterResult:
    required = {"is_ai_related", "confidence", "reason"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"prefilter payload missing fields: {sorted(missing)}")
    confidence = _clamp_confidence(payload["confidence"])
    return PrefilterResult(
        is_ai_related=bool(payload["is_ai_related"]),
        confidence=confidence,
        reason=str(payload["reason"]),
    )


def parse_scoring_payload(payload: dict[str, Any]) -> ScoringResult:
    required = {
        "dimensions",
        "category",
        "tags",
        "title_zh",
        "one_line_summary",
        "summary_zh",
        "reason_zh",
        "action_zh",
    }
    missing = required - set(payload)
    if missing:
        raise ValueError(f"scoring payload missing fields: {sorted(missing)}")
    dimensions = payload["dimensions"]
    for key in (
        "ai_relevance",
        "novelty",
        "impact",
        "information_density",
        "actionability",
        "creator_value",
    ):
        if key not in dimensions:
            raise ValueError(f"scoring dimensions missing field: {key}")
    tags = [str(tag) for tag in payload.get("tags", []) if str(tag).strip()]
    category = str(payload["category"])
    if category not in SCORING_CATEGORIES:
        logger.warning(
            "scoring payload category %r is off-enum (expected one of %s); "
            "falling back to keyword/default mapping for title=%r",
            category,
            SCORING_CATEGORIES,
            str(payload.get("title_zh", ""))[:80],
        )
    focus_category = resolve_focus_category(
        str(payload.get("focus_category") or ""),
        category,
        text=" ".join(
            [
                str(payload.get("title_zh") or ""),
                str(payload.get("one_line_summary") or ""),
                str(payload.get("summary_zh") or ""),
                " ".join(tags),
            ]
        ),
    )
    return ScoringResult(
        dimensions=ScoreDimensions(
            ai_relevance=_clamp_dimension(dimensions["ai_relevance"]),
            novelty=_clamp_dimension(dimensions["novelty"]),
            impact=_clamp_dimension(dimensions["impact"]),
            information_density=_clamp_dimension(dimensions["information_density"]),
            actionability=_clamp_dimension(dimensions["actionability"]),
            creator_value=_clamp_dimension(dimensions["creator_value"]),
        ),
        category=category,
        tags=tags[:5],
        title_zh=str(payload["title_zh"]),
        one_line_summary=str(payload["one_line_summary"]),
        summary_zh=str(payload["summary_zh"]),
        reason_zh=str(payload["reason_zh"]),
        action_zh=str(payload["action_zh"]),
        focus_category=focus_category,
    )


def parse_translation_payload(payload: dict[str, Any]) -> list[str]:
    paragraphs = payload.get("paragraphs_zh") or payload.get("translated_paragraphs")
    if not isinstance(paragraphs, list):
        raise ValueError("translation payload missing paragraphs_zh")
    cleaned = [str(paragraph).strip() for paragraph in paragraphs if str(paragraph).strip()]
    if not cleaned:
        raise ValueError("translation payload has no usable paragraphs")
    return cleaned


def _scoring_schema_hint() -> dict[str, Any]:
    return {
        "dimensions": asdict(ScoreDimensions(0, 0, 0, 0, 0, 0)),
        "category": "model_release",
        "focus_category": "model",
        "tags": ["Agent"],
        "title_zh": "中文标题",
        "one_line_summary": "一句话摘要",
        "summary_zh": "按核心事件→关键细节→结果→限制组织的180-260字事实摘要",
        "reason_zh": "指出具体变化、影响对象与现实影响的60-100字推荐理由",
        "action_zh": "下一步动作",
    }


def _translation_schema_hint() -> dict[str, Any]:
    return {
        "paragraphs_zh": [
            "第一段中文译文",
            "第二段中文译文",
        ]
    }


SCORING_CATEGORIES = [
    "model_release",
    "product_release",
    "open_source",
    "research",
    "industry",
    "funding",
    "opinion",
    "tutorial",
]

SUGGESTED_TAGS = [
    "Agent",
    "多模态",
    "推理",
    "开源",
    "编码",
    "语音",
    "机器人",
    "安全对齐",
    "评测",
    "融资",
]


def _dimension_rubric() -> str:
    return (
        "六维评分标准（0-10分，请严格对照锚点打分，不要凭感觉自由发挥）："
        "ai_relevance（AI相关度）：9-10分=文章报道的主体事件就是AI技术、模型、"
        "产品或研究本身；6-8分=AI是文章的重要组成部分之一，但夹杂其他行业内容；"
        "3-5分=AI只是被顺带提及的功能或修饰词，文章主体是其他行业事件；0-2分="
        "几乎不提AI或AI只是无关紧要的背景词。"
        "novelty（新颖度）：9-10分=首次实现某项能力、刷新SOTA、行业首创；6-8分"
        "=在已有能力基础上的明显改进或新组合；3-5分=现有能力的常规增量迭代或版"
        "本更新；0-2分=没有实质技术新意，纯营销通稿或重复报道。"
        "impact（影响力）：9-10分=可能改变行业格局或大量用户/开发者的工作方式；"
        "6-8分=对某个细分领域或产品线有明确影响；3-5分=影响范围有限，多为个案"
        "或局部优化；0-2分=几乎没有实际影响。"
        "information_density（信息密度）：9-10分=包含具体数据、参数、"
        "benchmark、技术细节或限制条件；6-8分=有一定具体信息但不够完整；3-5分"
        "=以描述性语言为主，具体细节较少；0-2分=几乎是空洞的公关辞令，没有可验"
        "证的信息。"
        "actionability（可操作性）：9-10分=读者能据此立即采取具体行动（试用、"
        "复现、决策参考）；6-8分=有明确的下一步方向但需要额外查证；3-5分=仅供"
        "了解，无直接行动价值；0-2分=与读者的实际行动完全无关。"
        "creator_value（创作者价值）：9-10分=对内容创作者/开发者的选题、产品决"
        "策有直接参考价值；6-8分=有一定参考价值但不是核心信息源；3-5分=价值有"
        "限，仅作背景了解；0-2分=对创作者/开发者几乎没有参考价值。"
        "以上维度必须基于原文实际内容打分，不得因为想输出'完整'的高分而编造原文"
        "没有提到的技术细节、数据或结论；原文信息不足以支撑判断时，给出偏保守、"
        "居中的分数，如实反映不确定性，不得瞎猜。"
    )


def _category_taxonomy_guide() -> str:
    return (
        "分类定义与边界规则（category 从8个枚举值中选择其一）："
        "model_release（模型进展）=首次发布或更新基础模型、版本或模型能力本身；"
        "product_release（产品应用）=基于已有模型包装的产品、应用、功能、服务或"
        "明确的企业应用案例，不强调"
        "开源或模型本身的技术突破；"
        "open_source（开源项目）=开源了模型权重、代码库、工具、框架或数据集，"
        "即使同时是模型发布，只要"
        "强调开源属性就优先归此类而非model_release；"
        "research（研究评测）=学术论文、研究成果、技术报告、Benchmark或评测，"
        "重点是研究方法、实验过程或结论本身；"
        "industry（行业事件）=公司合作、人事、组织变化、政策法规、监管或安全"
        "事件等非资本类行业新闻；"
        "funding（资本动态）=涉及具体金额、轮次的融资、并购、上市或重大投资；"
        "opinion（观点分析）=作者个人观点、预测、评论性文章，核心是主观判断而非客观事件报"
        "道；"
        "tutorial（教程实践）=教程、使用方法、最佳实践或案例复盘类内容。"
        "边界示例：'某公司发布新一代基础模型，推理能力较上一代提升30%'→"
        "model_release（核心是模型能力本身的进展）；'某公司基于自家大模型推出"
        "新的办公助手App'→product_release（核心是产品包装，不是模型本身的技术"
        "突破）；'某实验室开源了70B参数模型的权重和训练代码'→open_source（强调"
        "开源属性，即使同时是模型发布）；'某AI公司完成B轮融资，金额为2亿美元'"
        "→funding（具体金额和轮次）；'某分析师撰文预测生成式AI下一步的发展方"
        "向'→opinion（核心是主观判断和预测，不是客观事件）；'某AI公司创始人离"
        "职，另有高管加入'→industry（人事变动类行业新闻，非融资）。"
    )


def _focus_taxonomy_guide() -> str:
    return (
        "用户主关注分类（focus_category 必须从4个枚举值中选择其一，并与category"
        "独立判断）："
        "model=模型动态，核心变化是模型发布、版本、能力、参数、权重或模型本身；"
        "product=产品工具，核心变化是用户或开发者可以直接使用的产品、功能、平台、"
        "工具或应用；"
        "technology=技术研究，核心价值是方法、论文、实验、评测、数据集或通用工程"
        "实践；"
        "industry=行业动态，核心变化是公司经营、资本、合作、人事、市场、政策、监管"
        "或安全环境。"
        "focus_category 判断文章主要对象，不等同于内容形式：开源模型可为"
        "category=open_source、focus_category=model；开源开发框架可为"
        "open_source+product；论文实验代码可为open_source+technology；Claude Code"
        "使用教程可为tutorial+product；LoRA微调教程可为tutorial+technology；模型"
        "路线观点可为opinion+model；融资报道可为funding+industry。"
    )


def scoring_system_prompt() -> str:
    schema_hint = _scoring_schema_hint()
    return (
        _dimension_rubric() + " "
        + _category_taxonomy_guide() + " "
        + _focus_taxonomy_guide() + " "
        + "Score the AI news item for a Chinese AI intelligence daily report. "
        "Return strict JSON matching this example: "
        f"{json.dumps(schema_hint, ensure_ascii=False)}. "
        f"category MUST be exactly one of: {', '.join(SCORING_CATEGORIES)}. "
        "focus_category MUST be exactly one of: model, product, technology, industry. "
        "tags: up to 5 short Chinese or product-name tags; prefer this vocabulary "
        f"when applicable: {', '.join(SUGGESTED_TAGS)}; add company/model names as needed. "
        "title_zh（中文标题，12-30字）：必须忠实于原文标题与正文事实，"
        "准确概括这篇文章报道的具体事件（谁、做了什么），"
        "须包含原文中出现的关键公司、产品或模型名称；"
        "禁止编造原文没有的结论、数字或因果关系，"
        "禁止使用“震惊”“重磅”“彻底改变”“史诗级”这类夸张渲染词；"
        "原文标题本身已经准确的，直接翻译即可，不必强行改写出新说法。"
        "reason_zh（推荐理由，60-100字）：回答“这件事为什么值得被读者关注”——"
        "必须指出具体变化、影响对象和现实影响，"
        "优先使用文章中的数字、能力变化、行业位置或风险；"
        "禁止“值得关注”“可能产生深远影响”“对开发者有价值”这类空泛套话；"
        "不得重复摘要内容，不介绍文章写了什么。"
        "summary_zh（核心摘要，180-260字）：回答“谁做了什么、怎么做、结果如何、有什么限制或后续影响”，"
        "按“核心事件→关键细节→结果/结论→限制或背景”组织；"
        "保留关键名称、产品、时间、数字、结论和限制条件；"
        "只概括原文事实，不评价、不推荐、不推测；"
        "原文信息不足时宁可缩短，严禁补写或编造原文没有的内容。"
    )


def prefilter_system_prompt() -> str:
    return (
        "Return JSON with is_ai_related, confidence, reason. "
        "Only mark true for AI technology, products, research, industry, tooling. "
        "判断标准是文章的核心主题，而不是是否提到AI相关字眼：只有当AI技术、模"
        "型、产品或研究本身是文章报道的主体事件时才判定为相关；如果文章的主体"
        "事件属于其他行业（如产品发布、销量、财报、人事变动等），AI只是作为其"
        "中一项功能或卖点被顺带提及，判定为不相关，无论所属行业是什么。自检方"
        "法：这篇文章如果去掉AI相关的字眼，还剩下一个完整、独立成立的非AI新闻"
        "吗？如果是，判不相关。"
    )


def period_summary_prompt(kind: str, range_label: str) -> str:
    label = "周" if kind == "weekly" else "月"
    return (
        f"You are the editor of a Chinese AI intelligence {kind} report covering {range_label}. "
        "Given the interval's top AI events, write the mainline narrative. "
        "Return strict JSON: {\"mainline_title\": \"一句话概括本" + label + "主线（20字内）\", "
        "\"mainline_body\": \"总长度严格在360-440字之间（不少于360字，不超过440字，两者都视为不合格），"
        "归纳2-3条真实主线（如模型迭代/智能体落地/安全事件/融资基建/开源生态等，挑最重要的几条，"
        "其余舍弃），每条主线独立成一段、控制在150-190字、用2-3句话点出关键事件、数据或参数、"
        "以及为什么重要，不要写背景铺垫或空泛总结，引用具体事件名和公司/项目名。写完后自行数字数并调整，"
        "确保总字数落在360-440字区间。段落之间用换行符 \\n\\n 分隔，返回的 JSON 字符串里必须包含真实换行\", "
        "\"theme_notes\": [{\"label\": \"主题名\", \"note\": \"30字内该主题动向\"}]}. "
        "Base every claim on the provided events only; no speculation."
    )


_JSON_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)


def parse_chat_json(content: str) -> Any:
    """Parse chat-completion content that should be JSON but may be wrapped.

    Providers occasionally wrap the object in markdown fences or surround it
    with prose even when json response_format is requested.
    """
    text = (content or "").strip()
    if not text:
        raise ValueError("Chat response content is empty")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    unfenced = _JSON_FENCE_RE.sub("", text).strip()
    try:
        return json.loads(unfenced)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Chat response was not valid JSON: {text[:200]}")


def embedding_input(title: str, content: str) -> str:
    """The exact text an article's embedding is computed from. The persisted
    source_hash must hash this same string, or a title change would leave the
    stored hash claiming the embedding is still current.

    The title is repeated so it carries more weight than a straight
    title+content concatenation would give it. Short wire-style articles
    (200-450 chars) often open with a near-identical dateline/attribution
    sentence ("IT之家 X月X日消息，据XXX报道，今日，XXX透露，...") when the
    same spokesperson covers two different topics on the same day - that
    boilerplate can dominate a short article's embedding and make two
    genuinely different stories look like duplicates, even though their
    titles (which usually do carry the actual distinguishing fact) differ
    clearly."""
    return f"{title}\n{title}\n{content}"


class FakeAIProvider:
    """Deterministic provider for local tests and no-key dry runs."""

    embedding_model = "fake-embedding"

    def prefilter(self, text: str) -> PrefilterResult:
        normalized = text.lower()
        is_related = any(keyword in normalized for keyword in AI_KEYWORDS)
        return PrefilterResult(
            is_ai_related=is_related,
            confidence=0.9 if is_related else 0.8,
            reason="matched AI keywords" if is_related else "no AI signal found",
        )

    def score_article(self, title: str, content: str) -> ScoringResult:
        text = f"{title}\n{content}".lower()
        if "paper" in text or "arxiv" in text:
            category = "research"
            tags = ["Research", "AI"]
        elif "github" in text or "open source" in text:
            category = "open_source"
            tags = ["Open Source", "AI"]
        elif "product" in text or "launch" in text or "release" in text:
            category = "model_release" if "model" in text else "product_release"
            tags = ["Agent", "AI"]
        else:
            category = "industry"
            tags = ["AI"]
        dimensions = ScoreDimensions(
            ai_relevance=9,
            novelty=8,
            impact=8,
            information_density=7,
            actionability=7,
            creator_value=6,
        )
        title_zh = title if any("\u4e00" <= char <= "\u9fff" for char in title) else f"{title}"
        return ScoringResult(
            dimensions=dimensions,
            category=category,
            tags=tags,
            title_zh=title_zh,
            one_line_summary=f"{title}。",
            summary_zh=f"{title}。{content[:120]}",
            reason_zh="该事件来自高价值 AI 信号源，可能影响开发者、产品或内容选题。",
            action_zh="阅读原文，判断是否需要试用、跟进或收藏。",
            focus_category=resolve_focus_category(None, category, text=text),
        )

    def translate_paragraphs(self, paragraphs: list[str]) -> list[str]:
        return [
            paragraph if any("\u4e00" <= char <= "\u9fff" for char in paragraph) else f"译文：{paragraph}"
            for paragraph in paragraphs
        ]

    def summarize_period(
        self, items: list[dict[str, Any]], kind: str, range_label: str
    ) -> dict[str, Any]:
        label = "本周" if kind == "weekly" else "本月"
        top = items[0]["title"] if items else "AI 动态"
        return {
            "mainline_title": f"{label}主线：{top[:16]}",
            "mainline_body": (
                f"{label}（{range_label}）共 {len(items)} 条重点动态，主线围绕「{top}」等事件展开，"
                "模型能力迭代与智能体落地并进。（fake 确定性综述）"
            ),
            "theme_notes": [{"label": "模型", "note": "多家模型更新"}],
        }

    # 512 matches article_embeddings' vector(512), so fake-AI runs can
    # persist to a real Postgres just like the local bge model's output
    def embed_text(self, text: str, dimensions: int = 512) -> list[float]:
        digest = hashlib.sha256(text.lower().encode("utf-8")).digest()
        values = []
        while len(values) < dimensions:
            for byte in digest:
                values.append((byte / 255.0) * 2 - 1)
                if len(values) == dimensions:
                    break
            digest = hashlib.sha256(digest).digest()
        return values


class LocalEmbeddingProvider:
    """Real semantic embeddings via a local BAAI/bge-small-zh-v1.5 ONNX model
    (fastembed). Runs on-machine with no external API calls or per-call cost;
    replaces the SHA-256 hash pseudo-vectors FakeAIProvider produces, which
    carry no semantic information and cannot detect same-event articles
    reported with different wording."""

    _model = None  # class-level singleton: loading is the expensive part

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5"):
        self.model_name = model_name

    def _get_model(self):
        if LocalEmbeddingProvider._model is None:
            from fastembed import TextEmbedding

            LocalEmbeddingProvider._model = TextEmbedding(model_name=self.model_name)
        return LocalEmbeddingProvider._model

    def embed_text(self, text: str, dimensions: int | None = None) -> list[float]:
        model = self._get_model()
        vector = next(iter(model.embed([text])))
        return [float(value) for value in vector]


class OpenAIProvider:
    def __init__(
        self,
        api_key: str,
        *,
        scoring_model: str = "gpt-4.1-mini",
        embedding_model: str = "text-embedding-3-small",
    ):
        self.api_key = api_key
        self.scoring_model = scoring_model
        self.embedding_model = embedding_model

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI request failed: {exc.code} {body}") from exc

    def embed_text(self, text: str, dimensions: int | None = None) -> list[float]:
        payload: dict[str, Any] = {
            "model": self.embedding_model,
            "input": text[:8000],
        }
        if dimensions is not None:
            payload["dimensions"] = dimensions
        response = self._post_json("https://api.openai.com/v1/embeddings", payload)
        return [float(value) for value in response["data"][0]["embedding"]]

    def prefilter(self, text: str) -> PrefilterResult:
        payload = {
            "model": self.scoring_model,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": prefilter_system_prompt(),
                },
                {"role": "user", "content": text[:2000]},
            ],
        }
        response = self._post_json("https://api.openai.com/v1/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_prefilter_payload(parse_chat_json(content))

    def score_article(self, title: str, content: str) -> ScoringResult:
        payload = {
            "model": self.scoring_model,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": scoring_system_prompt(),
                },
                {"role": "user", "content": f"Title: {title}\n\nContent: {content[:4000]}"},
            ],
        }
        response = self._post_json("https://api.openai.com/v1/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_scoring_payload(parse_chat_json(content))

    def translate_paragraphs(self, paragraphs: list[str]) -> list[str]:
        schema_hint = _translation_schema_hint()
        payload = {
            "model": self.scoring_model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Translate each input paragraph into natural Simplified Chinese. "
                        "Preserve paragraph order and return strict JSON matching this example: "
                        f"{json.dumps(schema_hint, ensure_ascii=False)}"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"paragraphs": paragraphs}, ensure_ascii=False)[:6000],
                },
            ],
        }
        response = self._post_json("https://api.openai.com/v1/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_translation_payload(parse_chat_json(content))

    def summarize_period(
        self, items: list[dict[str, Any]], kind: str, range_label: str
    ) -> dict[str, Any]:
        payload = {
            "model": self.scoring_model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": period_summary_prompt(kind, range_label)},
                {
                    "role": "user",
                    "content": json.dumps({"events": items}, ensure_ascii=False)[:8000],
                },
            ],
        }
        response = self._post_json("https://api.openai.com/v1/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_period_summary_payload(parse_chat_json(content))


class KimiProvider:
    """Kimi/Moonshot chat provider with local real (bge-small-zh) embeddings."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "kimi-k2.7-code",
        base_url: str = "https://api.moonshot.cn/v1",
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._embedding_provider = LocalEmbeddingProvider()

    @property
    def embedding_model(self) -> str:
        # chat runs remotely but vectors come from the local bge model; the
        # persisted embedding_model label must name the vector model
        return self._embedding_provider.model_name

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Kimi request failed: {exc.code} {body}") from exc

    def embed_text(self, text: str, dimensions: int = 64) -> list[float]:
        return self._embedding_provider.embed_text(text, dimensions=dimensions)

    def prefilter(self, text: str) -> PrefilterResult:
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": prefilter_system_prompt(),
                },
                {"role": "user", "content": text[:2000]},
            ],
        }
        response = self._post_json(f"{self.base_url}/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_prefilter_payload(parse_chat_json(content))

    def score_article(self, title: str, content: str) -> ScoringResult:
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": scoring_system_prompt(),
                },
                {"role": "user", "content": f"Title: {title}\n\nContent: {content[:4000]}"},
            ],
        }
        response = self._post_json(f"{self.base_url}/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_scoring_payload(parse_chat_json(content))

    def translate_paragraphs(self, paragraphs: list[str]) -> list[str]:
        schema_hint = _translation_schema_hint()
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Translate each input paragraph into natural Simplified Chinese. "
                        "Preserve paragraph order and return strict JSON matching this example: "
                        f"{json.dumps(schema_hint, ensure_ascii=False)}"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"paragraphs": paragraphs}, ensure_ascii=False)[:6000],
                },
            ],
        }
        response = self._post_json(f"{self.base_url}/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_translation_payload(parse_chat_json(content))

    def summarize_period(
        self, items: list[dict[str, Any]], kind: str, range_label: str
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": period_summary_prompt(kind, range_label)},
                {
                    "role": "user",
                    "content": json.dumps({"events": items}, ensure_ascii=False)[:8000],
                },
            ],
        }
        response = self._post_json(f"{self.base_url}/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_period_summary_payload(parse_chat_json(content))


class DeepSeekProvider:
    """DeepSeek OpenAI-compatible chat provider with local real (bge-small-zh) embeddings."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        user_id: str | None = None,
        max_tokens: int = 4096,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id
        self.max_tokens = max_tokens
        self._embedding_provider = LocalEmbeddingProvider()

    @property
    def embedding_model(self) -> str:
        # chat runs remotely but vectors come from the local bge model; the
        # persisted embedding_model label must name the vector model
        return self._embedding_provider.model_name

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek request failed: {exc.code} {body}") from exc

    def _chat_payload(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": messages,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if self.user_id:
            payload["user_id"] = self.user_id
        return payload

    def embed_text(self, text: str, dimensions: int = 64) -> list[float]:
        return self._embedding_provider.embed_text(text, dimensions=dimensions)

    def prefilter(self, text: str) -> PrefilterResult:
        payload = self._chat_payload(
            [
                {
                    "role": "system",
                    "content": prefilter_system_prompt(),
                },
                {"role": "user", "content": text[:2000]},
            ],
            temperature=0.2,
        )
        response = self._post_json(f"{self.base_url}/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_prefilter_payload(parse_chat_json(content))

    def score_article(self, title: str, content: str) -> ScoringResult:
        messages = [
            {
                "role": "system",
                "content": scoring_system_prompt(),
            },
            {"role": "user", "content": f"Title: {title}\n\nContent: {content[:4000]}"},
        ]
        # Reasoning-capable DeepSeek models count hidden reasoning against
        # max_tokens. With the old 2048-token default they could start a valid
        # JSON object and then stop halfway through a tag or summary.
        budgets = (max(self.max_tokens, 4096), max(self.max_tokens * 2, 8192))
        last_error: ValueError | None = None
        choice: dict[str, Any] = {}
        for attempt, budget in enumerate(budgets):
            retry_messages = messages
            if attempt:
                retry_messages = [
                    {
                        "role": "system",
                        "content": (
                            scoring_system_prompt()
                            + " Return the JSON object directly and concisely. Do not include reasoning."
                        ),
                    },
                    messages[1],
                ]
            payload = self._chat_payload(retry_messages, max_tokens=budget, temperature=0.2)
            response = self._post_json(f"{self.base_url}/chat/completions", payload)
            choice = response["choices"][0]
            response_content = choice.get("message", {}).get("content") or ""
            try:
                return parse_scoring_payload(parse_chat_json(response_content))
            except ValueError as exc:
                last_error = exc
                if attempt == len(budgets) - 1:
                    break
        finish_reason = str(choice.get("finish_reason") or "unknown")
        raise ValueError(
            f"AI scoring response was incomplete (finish_reason={finish_reason}); please retry"
        ) from last_error

    def translate_paragraphs(self, paragraphs: list[str]) -> list[str]:
        schema_hint = _translation_schema_hint()
        payload = self._chat_payload(
            [
                {
                    "role": "system",
                    "content": (
                        "Translate each input paragraph into natural Simplified Chinese. "
                        "Preserve paragraph order and return strict JSON matching this example: "
                        f"{json.dumps(schema_hint, ensure_ascii=False)}"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"paragraphs": paragraphs}, ensure_ascii=False)[:6000],
                },
            ]
        )
        response = self._post_json(f"{self.base_url}/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_translation_payload(parse_chat_json(content))

    def summarize_period(
        self, items: list[dict[str, Any]], kind: str, range_label: str
    ) -> dict[str, Any]:
        # this model spends hidden reasoning_tokens before it emits the
        # visible JSON answer; the default max_tokens budget is tuned for
        # single-article scoring calls and is too tight for this longer
        # narrative task - it can exhaust the budget on reasoning alone and
        # return empty content with finish_reason=length
        payload = self._chat_payload(
            [
                {"role": "system", "content": period_summary_prompt(kind, range_label)},
                {
                    "role": "user",
                    "content": json.dumps({"events": items}, ensure_ascii=False)[:8000],
                },
            ],
            max_tokens=max(self.max_tokens, 8192),
        )
        response = self._post_json(f"{self.base_url}/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_period_summary_payload(parse_chat_json(content))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def provider_from_env(*, fake_ai: bool = False):
    if fake_ai:
        return FakeAIProvider()

    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    kimi_api_key = os.getenv("KIMI_API_KEY") or os.getenv("MOONSHOT_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    provider_name = os.getenv("AI_PROVIDER", "").strip().lower()
    if not provider_name:
        if deepseek_api_key:
            provider_name = "deepseek"
        elif kimi_api_key:
            provider_name = "kimi"
        elif openai_api_key:
            provider_name = "openai"
        else:
            provider_name = "fake"

    if provider_name in {"fake", "local"}:
        return FakeAIProvider()
    if provider_name in {"kimi", "moonshot"}:
        if not kimi_api_key:
            raise ValueError("KIMI_API_KEY or MOONSHOT_API_KEY is required when AI_PROVIDER=kimi")
        return KimiProvider(
            kimi_api_key,
            model=os.getenv("KIMI_MODEL", "kimi-k2.7-code"),
            base_url=os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1"),
        )
    if provider_name in {"deepseek", "deekseek"}:
        if not deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required when AI_PROVIDER=deepseek")
        return DeepSeekProvider(
            deepseek_api_key,
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            user_id=os.getenv("DEEPSEEK_USER_ID") or None,
            max_tokens=_env_int("DEEPSEEK_MAX_TOKENS", 4096),
        )
    if provider_name == "openai":
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when AI_PROVIDER=openai")
        return OpenAIProvider(
            openai_api_key,
            scoring_model=os.getenv("DEFAULT_SCORING_MODEL", "gpt-4.1-mini"),
            embedding_model=os.getenv("DEFAULT_EMBEDDING_MODEL", "text-embedding-3-small"),
        )
    raise ValueError(f"unsupported AI_PROVIDER: {provider_name}")
