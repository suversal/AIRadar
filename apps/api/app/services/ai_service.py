from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from app.models.domain import AIFocus, ContentValueDimensions, PrefilterResult, ScoringResult
from app.services.daily_summary_service import parse_daily_summary_payload
from app.services.period_summary_service import parse_period_summary_payload
from app.services.taxonomy import resolve_focus_category

logger = logging.getLogger(__name__)

#: Per-request wall clock for ordinary short-output calls (scoring, prefilter,
#: same-event verification).
DEFAULT_TIMEOUT_SECONDS = 60

#: For calls that must produce several hundred characters of prose in one shot.
#: 60s was enough while period summaries were short, but the monthly prompt asks
#: for 360-440 characters over a 40-event input, and 2026-W33/2026-08 both timed
#: out into the deterministic fallback (「本期 AI 综述生成失败」).
LONG_FORM_TIMEOUT_SECONDS = 180

#: Last-resort cut on the serialized summary input. Cutting a JSON string at a
#: character boundary sends the model malformed JSON, so the real sizing lives
#: upstream in period_summary_service (SUMMARY_INPUT_CHAR_BUDGET drops whole
#: items instead). This sits above that budget precisely so it never fires in
#: normal operation - it only bounds a request that somehow escaped the budget.
SUMMARY_INPUT_CHAR_LIMIT = 16000

#: Extra attempts after the first, for transport-level failures only.
NETWORK_RETRY_ATTEMPTS = 2

RETRY_BACKOFF_SECONDS = 2.0


def provider_model_name(provider: Any) -> str | None:
    """The chat model a provider scores with, for lineage stamping.

    OpenAIProvider separates its scoring model from its embedding model, the
    rest carry a single ``model``; both spellings are read so a provider swap
    cannot silently start recording nothing.
    """
    for attribute in ("scoring_model", "model"):
        name = getattr(provider, attribute, None)
        if isinstance(name, str) and name:
            return name
    return None


def _is_retryable_transport_error(error: Exception) -> bool:
    """Only retry failures where the very same request could still succeed.

    A 4xx means the request itself is wrong - retrying burns tokens and wall
    clock for the same answer. Malformed JSON is deliberately not handled here:
    that is the model producing something unusable, a prompt problem rather
    than a transport one, and asking again tends to fail the same way.
    """
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= 500 or error.code == 429
    return isinstance(error, (urllib.error.URLError, socket.timeout, TimeoutError))


def urlopen_json_with_retry(
    request: urllib.request.Request,
    *,
    timeout: float,
    label: str,
) -> dict[str, Any]:
    """POST and decode JSON, retrying transport failures.

    Re-raises the final error once attempts are exhausted, so a caller that
    degrades to a deterministic fallback still surfaces the real reason.
    """
    for attempt in range(NETWORK_RETRY_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - re-raised on the last attempt
            if not _is_retryable_transport_error(exc) or attempt == NETWORK_RETRY_ATTEMPTS:
                raise
            logger.warning(
                "%s failed (attempt %d/%d): %s; retrying",
                label,
                attempt + 1,
                NETWORK_RETRY_ATTEMPTS + 1,
                exc,
            )
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise RuntimeError(f"{label} exhausted retries")  # pragma: no cover - loop always returns/raises


@dataclass(frozen=True)
class AIUsage:
    """Billed token counts for one provider call, as the API reported them.

    Only raw counts are stored, never a money amount: DeepSeek moved to
    peak/off-peak pricing on 2026-08-16, so the same token count costs a
    different amount depending on when it was spent. Pricing belongs in the
    reader, not in the ledger.
    """

    operation: str
    model: str
    calls: int = 1
    prompt_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    completion_tokens: int = 0
    # thinking-mode tokens, billed at the (expensive) output rate even though
    # they never appear in the response content
    reasoning_tokens: int = 0

    def merged_with(self, other: "AIUsage") -> "AIUsage":
        return AIUsage(
            operation=self.operation,
            model=self.model,
            calls=self.calls + other.calls,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            cache_hit_tokens=self.cache_hit_tokens + other.cache_hit_tokens,
            cache_miss_tokens=self.cache_miss_tokens + other.cache_miss_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )


def usage_from_response(
    response: dict[str, Any], *, operation: str, model: str
) -> AIUsage | None:
    """Read the usage block of a chat/embedding response.

    Handles both the DeepSeek/Kimi spelling (``prompt_cache_hit_tokens``) and
    the OpenAI one (``prompt_tokens_details.cached_tokens``); a provider that
    reports neither still yields correct totals, just no cache split.
    """
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    completion_details = usage.get("completion_tokens_details") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    cache_hit = usage.get("prompt_cache_hit_tokens")
    if cache_hit is None:
        cache_hit = prompt_details.get("cached_tokens")
    cache_hit_tokens = int(cache_hit or 0)
    cache_miss = usage.get("prompt_cache_miss_tokens")
    cache_miss_tokens = (
        int(cache_miss) if cache_miss is not None else max(0, prompt_tokens - cache_hit_tokens)
    )
    return AIUsage(
        operation=operation,
        model=model,
        prompt_tokens=prompt_tokens,
        cache_hit_tokens=cache_hit_tokens,
        cache_miss_tokens=cache_miss_tokens,
        completion_tokens=int(usage.get("completion_tokens") or 0),
        reasoning_tokens=int(completion_details.get("reasoning_tokens") or 0),
    )


class UsageCollector:
    """Thread-safe token ledger keyed by (model, operation).

    Providers are called from the pipeline's ThreadPoolExecutor, so every
    update takes the lock. Whoever owns a run drains the totals and decides
    where they go, which keeps this module free of any database dependency.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._totals: dict[tuple[str, str], AIUsage] = {}

    def record(self, usage: AIUsage | None) -> None:
        if usage is None:
            return
        key = (usage.model, usage.operation)
        with self._lock:
            existing = self._totals.get(key)
            self._totals[key] = existing.merged_with(usage) if existing else usage

    def snapshot(self) -> list[AIUsage]:
        with self._lock:
            return sorted(
                self._totals.values(),
                key=lambda item: item.completion_tokens + item.reasoning_tokens,
                reverse=True,
            )

    def drain(self) -> list[AIUsage]:
        """Return the accumulated totals and reset, so a caller that persists
        one refresh's usage cannot double-count it into the next one."""
        with self._lock:
            totals = list(self._totals.values())
            self._totals.clear()
        return sorted(
            totals,
            key=lambda item: item.completion_tokens + item.reasoning_tokens,
            reverse=True,
        )


# Process-wide default so ad-hoc scripts and the manual-article path also
# accumulate; refresh runs drain this between pipeline runs.
USAGE_COLLECTOR = UsageCollector()


class _UsageReportingProvider:
    """Shared usage bookkeeping for the remote providers."""

    usage_collector: UsageCollector | None = None

    def _record_usage(self, operation: str, response: dict[str, Any], *, model: str) -> None:
        collector = self.usage_collector
        if collector is None:
            return
        usage = usage_from_response(response, operation=operation, model=model)
        if usage is None:
            return
        collector.record(usage)
        logger.debug(
            "ai_usage operation=%s model=%s prompt=%d cache_hit=%d completion=%d reasoning=%d",
            usage.operation,
            usage.model,
            usage.prompt_tokens,
            usage.cache_hit_tokens,
            usage.completion_tokens,
            usage.reasoning_tokens,
        )


@dataclass(frozen=True)
class EventMatchDecision:
    """Structured second-stage evidence for semantic event aggregation."""

    same_event: bool
    confidence: float
    reason: str

    @property
    def confirmed(self) -> bool:
        # Ambiguous model output must fail closed: a false split is reversible,
        # while a false merge corrupts source counts, ranking and event detail.
        return self.same_event and self.confidence >= 0.8


def parse_event_match_payload(payload: dict[str, Any]) -> EventMatchDecision:
    required = {"same_event", "confidence", "reason"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"event match payload missing fields: {sorted(missing)}")
    if not isinstance(payload["same_event"], bool):
        raise ValueError("event match payload same_event must be a boolean")
    reason = str(payload["reason"] or "").strip()
    if not reason:
        raise ValueError("event match payload reason must not be empty")
    return EventMatchDecision(
        same_event=payload["same_event"],
        confidence=_clamp_confidence(payload["confidence"]),
        reason=reason,
    )


def event_match_system_prompt() -> str:
    return """
You decide whether two news reports describe the SAME concrete real-world event.
Return strict JSON only:
{"same_event": true|false, "confidence": 0.0-1.0, "reason": "brief explanation"}

SAME requires the same principal actor, same concrete action/announcement,
same object/result, and compatible event time. Similar topic, company, product
category, security theme, research field, or generic AI wording is NOT enough.
A partnership, funding, product launch, policy proposal, research paper, and
industry alliance are different events even if they share companies or themes.
When evidence is incomplete, contradictory, or merely similar, return false.
""".strip()


def event_match_user_content(left: dict[str, Any], right: dict[str, Any]) -> str:
    def compact(document: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(document.get("id") or ""),
            "source": str(document.get("source") or ""),
            "published_at": str(document.get("published_at") or ""),
            "title": str(document.get("title") or "")[:500],
            "content": str(document.get("content") or "")[:1800],
        }

    return json.dumps(
        {"left": compact(left), "right": compact(right)},
        ensure_ascii=False,
    )


def build_same_event_verifier(
    ai_provider: Any,
) -> Callable[[dict[str, Any], dict[str, Any]], bool] | None:
    """Return a cached fail-closed verifier when the real provider supports it."""

    method = getattr(ai_provider, "verify_same_event", None)
    if not callable(method):
        return None
    cache: dict[tuple[str, str], bool] = {}

    def verify(left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_id = str(left.get("id") or "")
        right_id = str(right.get("id") or "")
        key = tuple(sorted((left_id, right_id)))
        if key in cache:
            return cache[key]
        try:
            decision = method(left, right)
            confirmed = (
                decision.confirmed
                if isinstance(decision, EventMatchDecision)
                else bool(decision)
            )
        except Exception:
            logger.exception(
                "same-event verifier failed for %s and %s; keeping events separate",
                left_id,
                right_id,
            )
            confirmed = False
        cache[key] = confirmed
        return confirmed

    return verify


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


AI_FOCUS_VALUES: tuple[AIFocus, ...] = ("primary", "contributing", "tangential")


def _parse_ai_focus(value: Any) -> AIFocus:
    normalized = str(value or "").strip().lower()
    if normalized not in AI_FOCUS_VALUES:
        raise ValueError(f"scoring payload ai_focus must be one of {AI_FOCUS_VALUES}, got {value!r}")
    return normalized  # type: ignore[return-value]


def parse_scoring_payload(payload: dict[str, Any]) -> ScoringResult:
    required = {
        "ai_focus",
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
    ai_focus = _parse_ai_focus(payload["ai_focus"])
    dimensions = payload["dimensions"]
    for key in ("impact", "novelty", "substance"):
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
        ai_focus=ai_focus,
        dimensions=ContentValueDimensions(
            impact=_clamp_dimension(dimensions["impact"]),
            novelty=_clamp_dimension(dimensions["novelty"]),
            substance=_clamp_dimension(dimensions["substance"]),
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
        "ai_focus": "primary",
        "dimensions": asdict(ContentValueDimensions(0, 0, 0)),
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


def _ai_focus_rubric() -> str:
    return (
        "ai_focus（AI主体性分类，从三个离散类别里选一个，不是打分，不允许输出"
        "中间值或第四种取值）："
        "primary=AI技术、模型、产品或研究本身就是文章报道的主体事件；"
        "contributing=AI是文章重要组成部分之一，但文章主体还涉及其他行业事件"
        "（如'某公司发布财报，其中AI业务收入增长30%'——AI只是财报的一个板块，"
        "不是财报本身）；"
        "tangential=AI/智能化只是顺带提及的功能、卖点或修饰词，文章主体是其他"
        "行业的事件。自检法：把文章里AI相关的字眼全部去掉，剩下的内容是否仍能"
        "独立成立一篇完整、有意义的报道？如果是，判tangential，不要因为出现了"
        "'智能''AI''智驾'这类字面词就顺势判高。"
        "重要豁免——AI 工具链的使用与排障：当文章讨论的对象本身就是 AI 产品、"
        "模型或工具（如 Codex、Claude、Cursor、ChatGPT、某模型 API 或 SDK），"
        "且内容是它的使用方法、配置、故障排查、踩坑复盘或能力实测时，AI 不属于"
        "'顺带提及'——把 AI 相关字眼去掉后这篇文章根本不存在（'某工具首包卡死的"
        "排查'离开了它是 AI 编程工具这个前提就没有意义），因此应判 primary 或"
        "contributing，不得判 tangential。与之相对：如果文章主体是一套通用工程"
        "实践（如代码审查流程、分支管理、项目管理方法、团队协作规范），AI 只是"
        "触发该实践的背景原因或素材来源（如'因为 AI 生成的代码变更太大，所以要"
        "用堆叠式 PR 拆解'），那么去掉 AI 之后这套实践本身仍然完整成立，仍判为"
        "tangential。判断分界：AI 是这篇文章的讨论对象，还是只是引出话题的背景。"
        "典型误判陷阱——车企/智能座舱类通稿：某车企OTA更新稿列举了多项车辆功能"
        "（智驾领航、城区/园区巡航、车外语音播报、车载K歌、胎压提醒、悬架灯光"
        "等），即使'智驾领航''自动泊车'字面像AI/自动驾驶术语，只要文章主体是"
        "罗列一次OTA推送里的多项车辆功能更新（尤其还夹杂大量与AI完全无关的舒适"
        "性/娱乐性配置），且没有具体讲述智驾感知或决策算法本身的技术进展，就应"
        "判tangential，不得因为几个高频关键词就判到contributing或更高；只有当"
        "文章是聚焦讲述智驾算法/模型能力本身的技术突破（如接管率、感知范围、"
        "训练方法的具体变化）时，才可能是contributing甚至primary。"
    )


def _value_dimension_rubric() -> str:
    return (
        "内容价值三维评分标准（0-10分，请严格对照锚点打分，只在ai_focus为"
        "primary或contributing时才需要打这三维；不要凭感觉自由发挥）："
        "impact（影响力）：9-10分=可能改变行业格局或大量用户/开发者的工作方式；"
        "6-8分=对某个细分领域或产品线有明确影响；3-5分=影响范围有限，多为个案"
        "或局部优化；0-2分=几乎没有实际影响。"
        "novelty（新颖度）：9-10分=首次实现某项能力、刷新SOTA、行业首创；6-8分"
        "=在已有能力基础上的明显改进或新组合；3-5分=现有能力的常规增量迭代或版"
        "本更新；0-2分=没有实质技术新意，纯营销通稿或重复报道。"
        "substance（信息含金量）：回答'这篇文章给读者提供的具体、可核实、可利"
        "用的信息有多少'——9-10分=包含具体数据、参数、benchmark、复现细节或明"
        "确的下一步行动；6-8分=有一定具体信息但不够完整；3-5分=以描述性语言为"
        "主，具体细节较少，或虽然细节很多但都是与AI/技术能力无关的功能罗列；"
        "0-2分=几乎是空洞的公关辞令，没有可验证的信息。"
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
        "tutorial 与 product_release 的边界（最常见的误判）：判断依据是文章在"
        "回答'怎么用'还是'出了什么新东西'。'手把手教你用 X 搭建 Y''X 的配置"
        "技巧与最佳实践''我们如何用 X 把 Z 做到 N 倍'这类实操指南、操作步骤或"
        "案例复盘，一律判 tutorial——即使通篇都在讲某个具体产品的功能、即使文"
        "中大量出现产品名，只要文章的核心价值是教读者照着做，而不是宣布该产品"
        "有了什么新版本或新能力，就不判 product_release。反过来，'X 发布新版"
        "本，新增 Y 功能'即使附带了使用说明，主体仍是产品进展，判 "
        "product_release。同一条原则也适用于 tutorial 与 model_release、"
        "technology 的边界：形式（教读者怎么做）压过主体（讲的是什么东西）。"
    )


def _focus_taxonomy_guide() -> str:
    return (
        "用户主关注分类（focus_category 必须从5个枚举值中选择其一，并与category"
        "独立判断）："
        "model=模型动态，核心变化是模型发布、版本、能力、参数、权重或模型本身；"
        "product=产品工具，核心变化是用户或开发者可以直接使用的产品、功能、平台、"
        "工具或应用；"
        "technology=技术研究，核心价值是方法、论文、实验、评测、数据集或通用工程"
        "实践；"
        "industry=行业动态，核心变化是公司经营、资本、合作、人事、市场、政策、监管"
        "或安全环境；"
        "tutorial=教程实践，核心是手把手教程、操作指南、最佳实践或案例复盘——即使"
        "同时涉及某个具体模型、产品或技术方法，只要文章的核心价值是教读者怎么做，"
        "而不是该模型/产品/技术本身的进展，就优先归为tutorial而非model/product/"
        "technology（这与category轴上open_source优先于model_release是同一种"
        "判断原则：形式压过主体）。"
        "focus_category 判断文章主要对象，不等同于内容形式：开源模型可为"
        "category=open_source、focus_category=model；开源开发框架可为"
        "open_source+product；论文实验代码可为open_source+technology；Claude Code"
        "使用教程属于tutorial+product（category是产品应用，focus是教程实践）；"
        "LoRA微调教程属于tutorial+technology（category是研究评测，focus是教程"
        "实践）；模型路线观点可为opinion+model；融资报道可为funding+industry。"
    )


def scoring_system_prompt() -> str:
    schema_hint = _scoring_schema_hint()
    return (
        _ai_focus_rubric() + " "
        + _value_dimension_rubric() + " "
        + _category_taxonomy_guide() + " "
        + _focus_taxonomy_guide() + " "
        + "Score the AI news item for a Chinese AI intelligence daily report. "
        "Return strict JSON matching this example: "
        f"{json.dumps(schema_hint, ensure_ascii=False)}. "
        f"ai_focus MUST be exactly one of: {', '.join(AI_FOCUS_VALUES)}. "
        f"category MUST be exactly one of: {', '.join(SCORING_CATEGORIES)}. "
        "focus_category MUST be exactly one of: model, product, technology, industry, tutorial. "
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
    # 这里只有标题+截断摘要，用来做一次省成本的粗筛；判断标准必须跟
    # scoring阶段_ai_focus_rubric()里的tangential定义完全一致——is_ai_related
    # =false 等价于全文级判断会得到tangential，否则prefilter通过的文章到了
    # scoring阶段又被判tangential，会显得两次判断标准不一致。
    return (
        "Return JSON with is_ai_related, confidence, reason. "
        "Only mark true for AI technology, products, research, industry, tooling. "
        "判断标准是文章的核心主题，而不是是否提到AI相关字眼：只有当AI技术、模"
        "型、产品或研究本身是文章报道的主体事件时才判定为相关；如果文章的主体"
        "事件属于其他行业（如产品发布、销量、财报、人事变动等），AI只是作为其"
        "中一项功能或卖点被顺带提及，判定为不相关，无论所属行业是什么。自检方"
        "法：这篇文章如果去掉AI相关的字眼，还剩下一个完整、独立成立的非AI新闻"
        "吗？如果是，判不相关。典型陷阱：车企OTA/智能座舱类通稿即使包含'智驾"
        "领航''自动泊车'这类字面像AI术语的词，只要文章主体是罗列多项车辆功能"
        "更新（尤其还夹杂大量与AI无关的娱乐/舒适性配置），判不相关。"
    )


def period_summary_prompt(kind: str, range_label: str) -> str:
    """周报和月报刻意不是同一个 prompt：周报和日报同构（主线+分类概述，
    读者从日切到周理解模型不用换），月报换结构（一段定调总述+2-3条趋势线，
    每条趋势必须回填 event_id 作证据——月尺度上按分类组织没有信息量，
    「这个月什么在变」只有跨分类的趋势抓得住）。"""
    if kind == "weekly":
        return (
            f"You are the editor of a Chinese AI intelligence weekly report covering {range_label}. "
            "The input has two parts: \"mainline_events\" are this week's selected events that "
            "multiple independent sources reported (source_count) or that stayed in the news for "
            "several days (days_covered); \"categories\" lists each focus category's selected "
            "items for the week (titles only). "
            "Return strict JSON: {\"mainline_title\": \"一句话概括本周主线（20字内）\", "
            "\"mainline_body\": \"总长度严格在360-440字之间（不少于360字，不超过440字，两者都视为不合格），"
            "只写 mainline_events 里的事，归纳2-3条真实主线（挑最重要的几条，其余舍弃），"
            "每条主线独立成一段、控制在150-190字、用2-3句话点出关键事件、数据或参数、"
            "以及为什么重要，多信源且连报多天的事优先。不要写背景铺垫或空泛总结，"
            "引用具体事件名和公司/项目名。写完后自行数字数并调整，确保总字数落在360-440字区间。"
            "段落之间用换行符 \\n\\n 分隔，返回的 JSON 字符串里必须包含真实换行\", "
            "\"category_notes\": [{\"category\": \"原样回填输入里的 category 值\", "
            "\"note\": \"60-90字，概括该分类本周的整体动向，点到具体名字。"
            "不要复述 mainline_body 已经讲过的事——主线负责本周最大的新闻，这里负责这一类的全貌\"}]}. "
            "categories 里出现的每个 category 都要在 category_notes 里出现且只出现一次。"
            "Base every claim on the provided items only; no speculation."
        )
    return (
        f"You are the editor of a Chinese AI intelligence monthly report covering {range_label}. "
        "The input is \"events\": the month's selected events, each with an event_id, how many "
        "independent sources reported it (source_count) and how many days it stayed in the news "
        "(days_covered). "
        "Return strict JSON: {\"mainline_title\": \"一句话概括本月主线（20字内）\", "
        "\"mainline_body\": \"150-250字的定调总述：这个月什么在变、往哪个方向变。"
        "点出2-3个具体事件名与关键数据，不要罗列、不要背景铺垫\", "
        "\"trends\": [{\"label\": \"趋势名（12字内，如：智能体落地加速）\", "
        "\"note\": \"120-180字论述这条趋势：发生了什么、为什么重要、和上月比变化在哪，"
        "引用具体公司/项目名与数据\", "
        "\"event_ids\": [\"支撑这条趋势的3-5个事件，必须原样引用输入里的 event_id，禁止编造\"]}]}. "
        "trends 给2-3条，跨 category 归纳——趋势是跨分类的（一条趋势可以同时横跨产品、技术、"
        "行业），不要按输入的 category 字段分组。每个入选 trends 的判断都必须有 event_ids 支撑。"
        "Base every claim on the provided events only; no speculation."
    )


def daily_summary_prompt(date_label: str) -> str:
    """One call, two deliberately different scopes.

    mainline_events are the day's multi-source events - what several outlets
    independently thought worth reporting. categories carry each focus
    category's whole day. Asking for both in one request is what lets the
    model keep the notes off the mainline's topics; five separate calls
    could not see each other and would repeat it five times.
    """
    return (
        f"You are the editor of a Chinese AI daily brief for {date_label}. "
        "The input has two parts: \"mainline_events\" are the events at least two "
        "independent sources reported today; \"categories\" lists every focus "
        "category's full set of today's items (titles only). "
        "Return strict JSON: "
        "{\"mainline_title\": \"一句话概括今天的主线（25字内）\", "
        "\"mainline_body\": \"120-200字，2-3句。只写 mainline_events 里的事，挑最重要的1-2件，"
        "点出具体公司/项目名与关键数据，并说清为什么重要。不要背景铺垫、不要空泛总结、"
        "不要罗列所有事件\", "
        "\"category_notes\": [{\"category\": \"原样回填输入里的 category 值\", "
        "\"note\": \"50-70字，概括该分类今天的整体动向，点到具体名字。"
        "不要复述 mainline_body 已经讲过的事——主线负责今天最大的新闻，这里负责这一类的全貌\"}]}. "
        "categories 里出现的每个 category 都要在 category_notes 里出现且只出现一次。"
        "Base every claim on the provided items only; no speculation."
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
        dimensions = ContentValueDimensions(
            impact=8,
            novelty=8,
            substance=7,
        )
        title_zh = title if any("\u4e00" <= char <= "\u9fff" for char in title) else f"{title}"
        return ScoringResult(
            ai_focus="primary",
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
        self, summary_input: dict[str, Any], kind: str, range_label: str
    ) -> dict[str, Any]:
        if kind == "weekly":
            events = summary_input.get("mainline_events") or []
            top = events[0]["title"] if events else "AI 动态"
            return {
                "mainline_title": f"本周主线：{top[:16]}",
                "mainline_body": (
                    f"本周（{range_label}）有 {len(events)} 件事被多家信源报道，"
                    f"主线围绕「{top}」等事件展开。（fake 确定性综述）"
                ),
                "category_notes": [
                    {"category": group["category"], "note": f"{group['item_count']} 条动态（fake）"}
                    for group in summary_input.get("categories") or []
                ],
            }
        events = summary_input.get("events") or []
        top = events[0]["title"] if events else "AI 动态"
        return {
            "mainline_title": f"本月主线：{top[:16]}",
            "mainline_body": (
                f"本月（{range_label}）共 {len(events)} 条重点动态，围绕「{top}」等事件展开。"
                "（fake 确定性综述）"
            ),
            "trends": [
                {
                    "label": "模型动态",
                    "note": "多家模型更新（fake 趋势论述）",
                    "event_ids": [event["event_id"] for event in events[:3]],
                }
            ],
        }

    def summarize_daily(self, summary_input: dict[str, Any], date_label: str) -> dict[str, Any]:
        events = summary_input.get("mainline_events") or []
        top = events[0]["title"] if events else "AI 动态"
        return {
            "mainline_title": f"今日主线：{top[:16]}",
            "mainline_body": (
                f"{date_label} 有 {len(events)} 件事被多家信源同时报道，其中「{top}」最受关注。"
                "（fake 确定性主线）"
            ),
            "category_notes": [
                {"category": group["category"], "note": f"{group['item_count']} 条动态（fake）"}
                for group in summary_input.get("categories") or []
            ],
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
    _model_key: tuple[str, str] | None = None
    _model_load_error: Exception | None = None
    _model_lock = threading.Lock()

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-zh-v1.5",
        *,
        cache_dir: str | Path | None = None,
    ):
        self.model_name = model_name
        configured_cache = cache_dir or os.getenv("FASTEMBED_CACHE_DIR")
        if configured_cache is None:
            configured_cache = (
                Path(__file__).resolve().parents[4] / "data" / "model_cache" / "fastembed"
            )
        configured_path = Path(configured_cache).expanduser()
        if not configured_path.is_absolute():
            configured_path = Path(__file__).resolve().parents[4] / configured_path
        self.cache_dir = configured_path.resolve()

    def _get_model(self):
        model_key = (self.model_name, str(self.cache_dir))
        if (
            LocalEmbeddingProvider._model is not None
            and LocalEmbeddingProvider._model_key == model_key
        ):
            return LocalEmbeddingProvider._model
        with LocalEmbeddingProvider._model_lock:
            if (
                LocalEmbeddingProvider._model is not None
                and LocalEmbeddingProvider._model_key == model_key
            ):
                return LocalEmbeddingProvider._model
            if (
                LocalEmbeddingProvider._model_load_error is not None
                and LocalEmbeddingProvider._model_key == model_key
            ):
                raise RuntimeError(
                    f"local embedding model failed to load from {self.cache_dir}"
                ) from LocalEmbeddingProvider._model_load_error

            from fastembed import TextEmbedding

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            LocalEmbeddingProvider._model_key = model_key
            try:
                LocalEmbeddingProvider._model = TextEmbedding(
                    model_name=self.model_name,
                    cache_dir=str(self.cache_dir),
                )
                LocalEmbeddingProvider._model_load_error = None
            except Exception as exc:
                LocalEmbeddingProvider._model = None
                LocalEmbeddingProvider._model_load_error = exc
                logger.exception(
                    "Failed to load local embedding model %s from stable cache %s",
                    self.model_name,
                    self.cache_dir,
                )
                raise
        return LocalEmbeddingProvider._model

    def embed_text(self, text: str, dimensions: int | None = None) -> list[float]:
        model = self._get_model()
        vector = next(iter(model.embed([text])))
        return [float(value) for value in vector]


class OpenAIProvider(_UsageReportingProvider):
    def __init__(
        self,
        api_key: str,
        *,
        scoring_model: str = "gpt-4.1-mini",
        embedding_model: str = "text-embedding-3-small",
        usage_collector: UsageCollector | None = None,
    ):
        self.api_key = api_key
        self.scoring_model = scoring_model
        self.embedding_model = embedding_model
        self.usage_collector = usage_collector

    def _chat_content(
        self,
        payload: dict[str, Any],
        operation: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> str:
        response = self._post_json(
            "https://api.openai.com/v1/chat/completions", payload, timeout=timeout
        )
        self._record_usage(operation, response, model=self.scoring_model)
        return response["choices"][0]["message"]["content"]

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
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
            return urlopen_json_with_retry(request, timeout=timeout, label="OpenAI request")
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
        content = self._chat_content(payload, "prefilter")
        return parse_prefilter_payload(parse_chat_json(content))

    def verify_same_event(
        self, left: dict[str, Any], right: dict[str, Any]
    ) -> EventMatchDecision:
        payload = {
            "model": self.scoring_model,
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "messages": [
                {"role": "system", "content": event_match_system_prompt()},
                {"role": "user", "content": event_match_user_content(left, right)},
            ],
        }
        content = self._chat_content(payload, "verify_same_event")
        return parse_event_match_payload(parse_chat_json(content))

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
        content = self._chat_content(payload, "score_article")
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
        content = self._chat_content(payload, "translate_paragraphs")
        return parse_translation_payload(parse_chat_json(content))

    def summarize_period(
        self, summary_input: dict[str, Any], kind: str, range_label: str
    ) -> dict[str, Any]:
        payload = {
            "model": self.scoring_model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": period_summary_prompt(kind, range_label)},
                {
                    "role": "user",
                    "content": json.dumps(summary_input, ensure_ascii=False)[:SUMMARY_INPUT_CHAR_LIMIT],
                },
            ],
        }
        content = self._chat_content(
            payload, "summarize_period", timeout=LONG_FORM_TIMEOUT_SECONDS
        )
        return parse_period_summary_payload(parse_chat_json(content), kind)

    def summarize_daily(self, summary_input: dict[str, Any], date_label: str) -> dict[str, Any]:
        payload = {
            "model": self.scoring_model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": daily_summary_prompt(date_label)},
                {
                    "role": "user",
                    "content": json.dumps(summary_input, ensure_ascii=False)[:SUMMARY_INPUT_CHAR_LIMIT],
                },
            ],
        }
        content = self._chat_content(
            payload, "summarize_daily", timeout=LONG_FORM_TIMEOUT_SECONDS
        )
        return parse_daily_summary_payload(parse_chat_json(content))


class KimiProvider(_UsageReportingProvider):
    """Kimi/Moonshot chat provider with local real (bge-small-zh) embeddings."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "kimi-k2.7-code",
        base_url: str = "https://api.moonshot.cn/v1",
        usage_collector: UsageCollector | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.usage_collector = usage_collector
        self._embedding_provider = LocalEmbeddingProvider()

    def _chat_content(
        self,
        payload: dict[str, Any],
        operation: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> str:
        response = self._post_json(
            f"{self.base_url}/chat/completions", payload, timeout=timeout
        )
        self._record_usage(operation, response, model=self.model)
        return response["choices"][0]["message"]["content"]

    @property
    def embedding_model(self) -> str:
        # chat runs remotely but vectors come from the local bge model; the
        # persisted embedding_model label must name the vector model
        return self._embedding_provider.model_name

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
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
            return urlopen_json_with_retry(request, timeout=timeout, label="Kimi request")
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
        content = self._chat_content(payload, "prefilter")
        return parse_prefilter_payload(parse_chat_json(content))

    def verify_same_event(
        self, left: dict[str, Any], right: dict[str, Any]
    ) -> EventMatchDecision:
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "messages": [
                {"role": "system", "content": event_match_system_prompt()},
                {"role": "user", "content": event_match_user_content(left, right)},
            ],
        }
        content = self._chat_content(payload, "verify_same_event")
        return parse_event_match_payload(parse_chat_json(content))

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
        content = self._chat_content(payload, "score_article")
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
        content = self._chat_content(payload, "translate_paragraphs")
        return parse_translation_payload(parse_chat_json(content))

    def summarize_period(
        self, summary_input: dict[str, Any], kind: str, range_label: str
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": period_summary_prompt(kind, range_label)},
                {
                    "role": "user",
                    "content": json.dumps(summary_input, ensure_ascii=False)[:SUMMARY_INPUT_CHAR_LIMIT],
                },
            ],
        }
        content = self._chat_content(
            payload, "summarize_period", timeout=LONG_FORM_TIMEOUT_SECONDS
        )
        return parse_period_summary_payload(parse_chat_json(content), kind)

    def summarize_daily(self, summary_input: dict[str, Any], date_label: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": daily_summary_prompt(date_label)},
                {
                    "role": "user",
                    "content": json.dumps(summary_input, ensure_ascii=False)[:SUMMARY_INPUT_CHAR_LIMIT],
                },
            ],
        }
        content = self._chat_content(
            payload, "summarize_daily", timeout=LONG_FORM_TIMEOUT_SECONDS
        )
        return parse_daily_summary_payload(parse_chat_json(content))


SCORING_REASONING_EFFORTS = ("off", "low", "high", "max")


# How much deliberation one call is worth. Thinking tokens bill at the output
# rate on every vendor here, and prefilter/verification/translation each want
# one determinate structured answer, where deliberation buys nothing but
# tokens. Only scoring and the period synthesis get to think.
THINKING_OFF = "off"
THINKING_SCORING = "scoring"  # subject to the per-provider budget/effort knob
THINKING_FULL = "full"  # weekly/monthly synthesis, runs once per period


class _OpenAICompatibleProvider(_UsageReportingProvider):
    """Chat plumbing shared by every OpenAI-format endpoint.

    DeepSeek and Alibaba Bailian both speak `/chat/completions` with the same
    request and response shape, so the pipeline logic lives here once.
    Subclasses declare only their dialect: how thinking is switched off (the
    field names differ and are silently ignored across vendors) and whether
    the system prompt needs an explicit cache marker.
    """

    vendor = "AI"

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        base_url: str,
        max_tokens: int = 4096,
        usage_collector: UsageCollector | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.usage_collector = usage_collector
        self._embedding_provider = LocalEmbeddingProvider()

    @property
    def embedding_model(self) -> str:
        # chat runs remotely but vectors come from the local bge model; the
        # persisted embedding_model label must name the vector model
        return self._embedding_provider.model_name

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
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
            return urlopen_json_with_retry(
                request, timeout=timeout, label=f"{self.vendor} request"
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.vendor} request failed: {exc.code} {body}") from exc

    # --- dialect hooks -------------------------------------------------

    def _apply_thinking(self, payload: dict[str, Any], mode: str) -> None:
        """Write this vendor's thinking-control fields into the payload."""
        raise NotImplementedError

    def _prepare_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Hook for vendors whose caching needs the messages reshaped."""
        return messages

    def _vendor_payload(self) -> dict[str, Any]:
        return {}

    # --- shared request building ---------------------------------------

    def _chat_payload(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        thinking: str = THINKING_OFF,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": self._prepare_messages(messages),
            "max_tokens": max_tokens or self.max_tokens,
        }
        self._apply_thinking(payload, thinking)
        if temperature is not None:
            payload["temperature"] = temperature
        payload.update(self._vendor_payload())
        return payload

    def _chat_content(
        self,
        payload: dict[str, Any],
        operation: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> str:
        response = self._post_json(
            f"{self.base_url}/chat/completions", payload, timeout=timeout
        )
        self._record_usage(operation, response, model=self.model)
        return response["choices"][0]["message"]["content"]

    # --- pipeline operations -------------------------------------------

    def embed_text(self, text: str, dimensions: int = 64) -> list[float]:
        return self._embedding_provider.embed_text(text, dimensions=dimensions)

    def prefilter(self, text: str) -> PrefilterResult:
        payload = self._chat_payload(
            [
                {"role": "system", "content": prefilter_system_prompt()},
                {"role": "user", "content": text[:2000]},
            ],
            temperature=0.2,
        )
        return parse_prefilter_payload(parse_chat_json(self._chat_content(payload, "prefilter")))

    def verify_same_event(
        self, left: dict[str, Any], right: dict[str, Any]
    ) -> EventMatchDecision:
        payload = self._chat_payload(
            [
                {"role": "system", "content": event_match_system_prompt()},
                {"role": "user", "content": event_match_user_content(left, right)},
            ],
            max_tokens=1024,
            temperature=0,
        )
        content = self._chat_content(payload, "verify_same_event")
        return parse_event_match_payload(parse_chat_json(content))

    def score_article(self, title: str, content: str) -> ScoringResult:
        messages = [
            {"role": "system", "content": scoring_system_prompt()},
            {"role": "user", "content": f"Title: {title}\n\nContent: {content[:4000]}"},
        ]
        # A thinking model counts hidden reasoning against its output budget.
        # With the old 2048-token default it could start a valid JSON object
        # and then stop halfway through a tag or summary, so a truncated first
        # attempt is retried once with a bigger budget and a terser prompt.
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
            payload = self._chat_payload(
                retry_messages,
                max_tokens=budget,
                temperature=0.2,
                thinking=THINKING_SCORING,
            )
            response = self._post_json(f"{self.base_url}/chat/completions", payload)
            self._record_usage("score_article", response, model=self.model)
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
        content = self._chat_content(payload, "translate_paragraphs")
        return parse_translation_payload(parse_chat_json(content))

    def summarize_period(
        self, summary_input: dict[str, Any], kind: str, range_label: str
    ) -> dict[str, Any]:
        # the one call that keeps full thinking: it runs once per week/month,
        # so its share of the bill is noise, while it is the only task here
        # that genuinely synthesizes across dozens of events rather than
        # classifying or translating one. Its budget is also raised, because
        # reasoning alone can exhaust a scoring-sized budget and return empty
        # content with finish_reason=length.
        payload = self._chat_payload(
            [
                {"role": "system", "content": period_summary_prompt(kind, range_label)},
                {
                    "role": "user",
                    "content": json.dumps(summary_input, ensure_ascii=False)[:SUMMARY_INPUT_CHAR_LIMIT],
                },
            ],
            max_tokens=max(self.max_tokens, 8192),
            thinking=THINKING_FULL,
        )
        content = self._chat_content(
            payload, "summarize_period", timeout=LONG_FORM_TIMEOUT_SECONDS
        )
        return parse_period_summary_payload(parse_chat_json(content), kind)

    def summarize_daily(self, summary_input: dict[str, Any], date_label: str) -> dict[str, Any]:
        # Same full-thinking treatment as summarize_period: this is the other
        # task that synthesizes across events instead of classifying one. It
        # would run 12-14 times a day at pipeline cadence, which is why
        # daily_summary_service fingerprints the material and only calls when
        # the day's events actually changed.
        payload = self._chat_payload(
            [
                {"role": "system", "content": daily_summary_prompt(date_label)},
                {
                    "role": "user",
                    "content": json.dumps(summary_input, ensure_ascii=False)[:SUMMARY_INPUT_CHAR_LIMIT],
                },
            ],
            max_tokens=max(self.max_tokens, 4096),
            thinking=THINKING_FULL,
        )
        content = self._chat_content(
            payload, "summarize_daily", timeout=LONG_FORM_TIMEOUT_SECONDS
        )
        return parse_daily_summary_payload(parse_chat_json(content))


class DeepSeekProvider(_OpenAICompatibleProvider):
    """DeepSeek OpenAI-compatible chat provider with local real (bge-small-zh) embeddings."""

    vendor = "DeepSeek"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        user_id: str | None = None,
        max_tokens: int = 4096,
        scoring_reasoning_effort: str = "low",
        usage_collector: UsageCollector | None = None,
    ):
        super().__init__(
            api_key,
            model=model,
            base_url=base_url,
            max_tokens=max_tokens,
            usage_collector=usage_collector,
        )
        self.user_id = user_id
        effort = str(scoring_reasoning_effort or "low").strip().lower()
        if effort not in SCORING_REASONING_EFFORTS:
            raise ValueError(
                f"scoring_reasoning_effort must be one of {SCORING_REASONING_EFFORTS}, got {effort!r}"
            )
        self.scoring_reasoning_effort = effort

    def _apply_thinking(self, payload: dict[str, Any], mode: str) -> None:
        # DeepSeek defaults to thinking=enabled + reasoning_effort=high, and
        # bills every thinking token at the output rate - 2x the cache-miss
        # input rate and 100x the cache-hit one.
        if mode == THINKING_FULL:
            payload["thinking"] = {"type": "enabled"}
            return
        if mode == THINKING_SCORING and self.scoring_reasoning_effort != "off":
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = self.scoring_reasoning_effort
            return
        payload["thinking"] = {"type": "disabled"}

    def _vendor_payload(self) -> dict[str, Any]:
        return {"user_id": self.user_id} if self.user_id else {}


# Bailian only creates an explicit cache block for prefixes of at least 1024
# tokens. Chinese runs roughly 0.6 tokens per character, so a system prompt
# needs ~1700 characters to qualify; below that the marker is pointless (only
# the scoring rubric clears it - prefilter and verification are far shorter).
QWEN_CACHEABLE_PROMPT_CHARS = 1700


class QwenProvider(_OpenAICompatibleProvider):
    """Alibaba Bailian (qwen) via its OpenAI-compatible endpoint.

    Two vendor differences are load-bearing, both found by measurement:

    - `reasoning_effort` is silently ignored by qwen3.7 (it only applies to
      glm-5.x / deepseek-v4 / kimi-k3 on Bailian). Sending DeepSeek-shaped
      thinking fields leaves the model at full reasoning strength, which cost
      53% *more* than DeepSeek in the first measured run. qwen's own knobs are
      `enable_thinking` and `thinking_budget`.
    - Caching is not automatic. The implicit cache never hit in testing, so
      the long scoring prefix carries an explicit `cache_control` marker,
      which measured a 67% input-cache hit rate (the theoretical maximum,
      since the rest of each request is per-article body).
    """

    vendor = "Bailian"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "qwen3.7-flash",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        max_tokens: int = 4096,
        thinking_budget: int = 50,
        usage_collector: UsageCollector | None = None,
    ):
        super().__init__(
            api_key,
            model=model,
            base_url=base_url,
            max_tokens=max_tokens,
            usage_collector=usage_collector,
        )
        if thinking_budget < 0:
            raise ValueError(f"thinking_budget must not be negative, got {thinking_budget}")
        self.thinking_budget = thinking_budget

    def _apply_thinking(self, payload: dict[str, Any], mode: str) -> None:
        if mode == THINKING_FULL:
            payload["enable_thinking"] = True
            return
        if mode == THINKING_SCORING and self.thinking_budget > 0:
            payload["enable_thinking"] = True
            payload["thinking_budget"] = self.thinking_budget
            return
        payload["enable_thinking"] = False

    def _prepare_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            content = message.get("content")
            if (
                index == 0
                and message.get("role") == "system"
                and isinstance(content, str)
                and len(content) >= QWEN_CACHEABLE_PROMPT_CHARS
            ):
                prepared.append(
                    {
                        "role": "system",
                        "content": [
                            {
                                "type": "text",
                                "text": content,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                )
            else:
                prepared.append(message)
        return prepared


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def provider_from_env(
    *,
    fake_ai: bool = False,
    usage_collector: UsageCollector | None = USAGE_COLLECTOR,
):
    if fake_ai:
        return FakeAIProvider()

    ali_api_key = os.getenv("ALI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    kimi_api_key = os.getenv("KIMI_API_KEY") or os.getenv("MOONSHOT_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    provider_name = os.getenv("AI_PROVIDER", "").strip().lower()
    if not provider_name:
        if ali_api_key:
            provider_name = "qwen"
        elif deepseek_api_key:
            provider_name = "deepseek"
        elif kimi_api_key:
            provider_name = "kimi"
        elif openai_api_key:
            provider_name = "openai"
        else:
            provider_name = "fake"

    if provider_name in {"fake", "local"}:
        return FakeAIProvider()
    if provider_name in {"qwen", "bailian", "dashscope", "ali", "aliyun"}:
        if not ali_api_key:
            raise ValueError("ALI_API_KEY or DASHSCOPE_API_KEY is required when AI_PROVIDER=qwen")
        return QwenProvider(
            ali_api_key,
            model=os.getenv("QWEN_MODEL", "qwen3.7-flash"),
            base_url=os.getenv(
                "ALI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            max_tokens=_env_int("QWEN_MAX_TOKENS", 4096),
            thinking_budget=_env_int("QWEN_THINKING_BUDGET", 50),
            usage_collector=usage_collector,
        )
    if provider_name in {"kimi", "moonshot"}:
        if not kimi_api_key:
            raise ValueError("KIMI_API_KEY or MOONSHOT_API_KEY is required when AI_PROVIDER=kimi")
        return KimiProvider(
            kimi_api_key,
            model=os.getenv("KIMI_MODEL", "kimi-k2.7-code"),
            base_url=os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1"),
            usage_collector=usage_collector,
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
            scoring_reasoning_effort=os.getenv("DEEPSEEK_SCORING_REASONING_EFFORT", "low"),
            usage_collector=usage_collector,
        )
    if provider_name == "openai":
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when AI_PROVIDER=openai")
        return OpenAIProvider(
            openai_api_key,
            scoring_model=os.getenv("DEFAULT_SCORING_MODEL", "gpt-4.1-mini"),
            embedding_model=os.getenv("DEFAULT_EMBEDDING_MODEL", "text-embedding-3-small"),
            usage_collector=usage_collector,
        )
    raise ValueError(f"unsupported AI_PROVIDER: {provider_name}")
