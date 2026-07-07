from __future__ import annotations

import hashlib
import json
import os
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


def _scoring_schema_hint() -> dict[str, Any]:
    return {
        "dimensions": asdict(ScoreDimensions(0, 0, 0, 0, 0, 0)),
        "category": "model_release",
        "tags": ["Agent"],
        "title_zh": "中文标题",
        "one_line_summary": "一句话摘要",
        "summary_zh": "核心摘要",
        "reason_zh": "推荐理由",
        "action_zh": "下一步动作",
    }


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
        schema_hint = _scoring_schema_hint()
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


class KimiProvider:
    """Kimi/Moonshot chat provider with local deterministic embeddings."""

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
        self._embedding_provider = FakeAIProvider()

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
        response = self._post_json(f"{self.base_url}/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_prefilter_payload(json.loads(content))

    def score_article(self, title: str, content: str) -> ScoringResult:
        schema_hint = _scoring_schema_hint()
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Score the AI news item for a Chinese AI intelligence daily report. "
                        "Return strict JSON matching this example: "
                        f"{json.dumps(schema_hint, ensure_ascii=False)}"
                    ),
                },
                {"role": "user", "content": f"Title: {title}\n\nContent: {content[:4000]}"},
            ],
        }
        response = self._post_json(f"{self.base_url}/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_scoring_payload(json.loads(content))


class DeepSeekProvider:
    """DeepSeek OpenAI-compatible chat provider with local deterministic embeddings."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        user_id: str | None = None,
        max_tokens: int = 2048,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id
        self.max_tokens = max_tokens
        self._embedding_provider = FakeAIProvider()

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

    def _chat_payload(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": messages,
            "max_tokens": self.max_tokens,
        }
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
                    "content": (
                        "Return JSON with is_ai_related, confidence, reason. "
                        "Only mark true for AI technology, products, research, industry, tooling."
                    ),
                },
                {"role": "user", "content": text[:2000]},
            ]
        )
        response = self._post_json(f"{self.base_url}/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_prefilter_payload(json.loads(content))

    def score_article(self, title: str, content: str) -> ScoringResult:
        schema_hint = _scoring_schema_hint()
        payload = self._chat_payload(
            [
                {
                    "role": "system",
                    "content": (
                        "Score the AI news item for a Chinese AI intelligence daily report. "
                        "Return strict JSON matching this example: "
                        f"{json.dumps(schema_hint, ensure_ascii=False)}"
                    ),
                },
                {"role": "user", "content": f"Title: {title}\n\nContent: {content[:4000]}"},
            ]
        )
        response = self._post_json(f"{self.base_url}/chat/completions", payload)
        content = response["choices"][0]["message"]["content"]
        return parse_scoring_payload(json.loads(content))


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
            max_tokens=_env_int("DEEPSEEK_MAX_TOKENS", 2048),
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
