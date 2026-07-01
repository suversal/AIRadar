from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any

from app.models.domain import PrefilterResult, ScoreDimensions, ScoringResult

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


def parse_prefilter_payload(payload: dict[str, Any]) -> PrefilterResult:
    required = {"is_ai_related", "confidence", "reason"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"prefilter payload missing fields: {sorted(missing)}")
    confidence = max(0.0, min(1.0, float(payload["confidence"])))
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
    return ScoringResult(
        dimensions=ScoreDimensions(
            ai_relevance=_clamp_dimension(dimensions["ai_relevance"]),
            novelty=_clamp_dimension(dimensions["novelty"]),
            impact=_clamp_dimension(dimensions["impact"]),
            information_density=_clamp_dimension(dimensions["information_density"]),
            actionability=_clamp_dimension(dimensions["actionability"]),
            creator_value=_clamp_dimension(dimensions["creator_value"]),
        ),
        category=str(payload["category"]),
        tags=tags[:5],
        title_zh=str(payload["title_zh"]),
        one_line_summary=str(payload["one_line_summary"]),
        summary_zh=str(payload["summary_zh"]),
        reason_zh=str(payload["reason_zh"]),
        action_zh=str(payload["action_zh"]),
    )


class FakeAIProvider:
    """Deterministic provider for local tests and no-key dry runs."""

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
        )

    def embed_text(self, text: str, dimensions: int = 64) -> list[float]:
        digest = hashlib.sha256(text.lower().encode("utf-8")).digest()
        values = []
        while len(values) < dimensions:
            for byte in digest:
                values.append((byte / 255.0) * 2 - 1)
                if len(values) == dimensions:
                    break
            digest = hashlib.sha256(digest).digest()
        return values


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
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return JSON with is_ai_related, confidence, reason. "
                        "Only mark true for AI technology, products, research, industry, tooling."
                    ),
                },
                {"role": "user", "content": text[:2000]},
            ],
        }
        response = self._post_json("https://api.openai.com/v1/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_prefilter_payload(json.loads(content))

    def score_article(self, title: str, content: str) -> ScoringResult:
        schema_hint = {
            "dimensions": asdict(ScoreDimensions(0, 0, 0, 0, 0, 0)),
            "category": "model_release",
            "tags": ["Agent"],
            "title_zh": "中文标题",
            "one_line_summary": "一句话摘要",
            "summary_zh": "核心摘要",
            "reason_zh": "推荐理由",
            "action_zh": "下一步动作",
        }
        payload = {
            "model": self.scoring_model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Score the AI news item. Return strict JSON matching this example: "
                        f"{json.dumps(schema_hint, ensure_ascii=False)}"
                    ),
                },
                {"role": "user", "content": f"Title: {title}\n\nContent: {content[:4000]}"},
            ],
        }
        response = self._post_json("https://api.openai.com/v1/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_scoring_payload(json.loads(content))

