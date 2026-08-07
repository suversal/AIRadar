from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.crawlers.base import (
    BaseCrawler,
    canonicalize_url,
    fetch_url_text,
    normalize_article,
    stable_hash,
)
from app.models.domain import RawArticle, Source

logger = logging.getLogger(__name__)

SOURCEPILOT_DEFAULT_BASE_URL = "http://127.0.0.1:8420"
SP_ARTICLE_CACHE_DIR = Path("data") / "sourcepilot" / "article_cache"

_PAGE_SIZE = 100  # /wechat/feed 的 limit 上限(契约 §4)
_MAX_PAGES = 6  # 硬顶,防翻页失控
_DEFAULT_ARTICLE_LIMIT = 20
#: 正文缓存格式版本。**改了提取逻辑就要升它**——缓存存的是整个提取结果，
#: 不升的话新代码根本不会执行，重抓拿到的还是旧块（2026-08-07 踩过：修完
#: 颜色/居中/视频，重抓出来一模一样，查了半天发现是命中旧缓存）。
#:
#:   v1  SourcePilot /article 返回的 markdown 字符串
#:   v2  改用 AIRADAR 自己的提取器，存完整结果（含 original_blocks）
#:   v3  提取器补了 text-align、丢弃主题中性色、识别微信 iframe 视频
_CACHE_VERSION = 3

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _base_url() -> str:
    return os.getenv("SOURCEPILOT_BASE_URL", SOURCEPILOT_DEFAULT_BASE_URL).rstrip("/")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _recent_cutoff(source: Source) -> date | None:
    """recent_days 剪枝阈值(上海时区日期,与 pipeline 的
    filter_articles_published_on 同一语义)。0 = 不剪。剪枝必须发生在正文
    enrich 之前——SP 限流恢复后会补投旧文,不剪的话它们会先耗掉 /article
    调用预算,再被 refresh_service 的日期过滤丢弃,纯浪费。"""
    value = (source.config or {}).get("recent_days", 1)
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = 1
    if days <= 0:
        return None
    today = datetime.now(_SHANGHAI).date()
    return today - timedelta(days=days - 1)


def parse_sourcepilot_items(
    items: list[dict],
    source: Source,
    limit: int | None = None,
) -> list[RawArticle]:
    """SourcePilot Item → RawArticle。纯函数,可直接喂 dict 单测。

    契约红线:不读 item["raw"] 做任何逻辑(结构不稳定,只把 score 放进
    raw_score 作展示参考);published_at 为 null 时不伪造——normalize 回填
    now() 是 AIRADAR 的既有行为,真实依据记在 metadata.time_basis。"""
    cutoff = _recent_cutoff(source)
    articles: list[RawArticle] = []
    for item in items:
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        if not title or not url:
            continue
        published_at = _parse_iso(item.get("published_at"))
        if cutoff is not None and published_at is not None:
            if published_at.astimezone(_SHANGHAI).date() < cutoff:
                continue
        summary = (item.get("summary") or "").strip()
        metadata = {
            "sp_item_id": item.get("id"),
            "sp_platform": (item.get("source") or {}).get("platform"),
            "time_basis": item.get("time_basis"),
            "categories": item.get("categories") or [],
            "media": item.get("media") or [],
            # 复用 upsert 的既有约定:published_at 只在该键为 False 时才允许
            # 回写已有行——后续轮次拿到真实发布时间时才能纠正
            "rss_pubdate_missing": item.get("published_at") is None,
            # 未 enrich 前的兜底来源标注;enrich 成功后覆盖为 sourcepilot_article
            "content_origin": "sourcepilot_summary",
        }
        articles.append(
            normalize_article(
                source=source,
                source_url=url,
                title=title,
                content=summary or title,
                author=item.get("author"),
                published_at=published_at,
                language=item.get("lang") or source.language,
                raw_score={"sp_score": item.get("score")},
                metadata=metadata,
            )
        )
    return articles[:limit] if limit is not None else articles


def _check_contract_version(meta: dict) -> None:
    version = str(meta.get("contract_version") or "")
    if version and not version.startswith("1."):
        logger.error(
            "sourcepilot contract major version changed: %s - "
            "breaking changes possible, review the integration",
            version,
        )


def fetch_sourcepilot_article(
    url: str,
    *,
    cache_dir: Path,
) -> dict | None:
    """取正文，用 AIRADAR 自己那套（草稿管理同款），按 url_hash 做本地缓存。

    **为什么不调 SourcePilot 的 `/api/v1/article`**（第一版是那么写的）：
    AIRADAR 本来就有能抓公众号的提取器——`article_content.py` 里配着
    `wechat-article-v1` profile（`#js_content` 容器），草稿管理天天在用。
    实测同一篇文章两边覆盖度一致（都是 2 个小标题 + 7 张图），绕去 SP 只是
    多一跳网络、多一处要跟着微信改版维护的代码，正文还平白依赖 SP 在不在线。

    注意 `mp.weixin.qq.com` 在 `UNFETCHABLE_ARTICLE_DOMAINS` 里，但那道检查在
    **爬虫路径**（`page_content.py`）上；`fetch_manual_article` 不查那个名单
    （实测 0 处引用），所以这条路是通的——AIRADAR 对公众号的「抓不了」是早期
    策略遗留，不是技术上做不到。

    失败不写缓存（下轮重试，受 per-run 预算约束）。返回 None = 拿不到。
    """
    from app.services.manual_article_fetcher import fetch_manual_article

    cache_path = Path(cache_dir) / f"{stable_hash(canonicalize_url(url))}.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            # v2 起缓存的是整个提取结果；v1 只存了 SP 返回的 markdown 字符串，
            # 形状对不上，当未命中重取即可（数量有限，一次性）。
            if cached.get("v") == _CACHE_VERSION and cached.get("extracted"):
                return cached["extracted"]
        except (json.JSONDecodeError, OSError):
            pass  # 缓存损坏当未命中
    try:
        extracted = fetch_manual_article(url)
    except Exception as exc:
        logger.warning("article extraction failed for %s: %s", url, exc)
        return None
    if not (extracted.get("original_blocks") or extracted.get("content")):
        return None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"url": url, "v": _CACHE_VERSION, "extracted": extracted},
                   ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return extracted


class SourcePilotCrawler(BaseCrawler):
    """把 SourcePilot 当聚合上游:每个 Source 对应 SP 的一个过滤视图
    (config.sp_platform → GET /items?platform=)。

    正文必须在这里 eager 取:mp.weixin.qq.com 在 UNFETCHABLE_ARTICLE_DOMAINS,
    管线的 deferred 路径(page_content.py)对它直接放弃,所以本 crawler 绝不
    设置 body_fetch=deferred,content 给什么就是什么。"""

    def __init__(
        self,
        source: Source,
        *,
        article_cache_dir: Path | None = None,
    ):
        super().__init__(source)
        self.article_cache_dir = Path(article_cache_dir or SP_ARTICLE_CACHE_DIR)

    # ── 为什么这里没有增量水位 ────────────────────────────────
    #
    # 第一版在 fetch() 里存过一个 since 水位,那是**错的**:`BaseCrawler.fetch()`
    # 没有「已成功落库」这个信号——crawl_sources() 只负责抓,落库在后面的 pipeline
    # 里。水位在 fetch 时就推进,一旦后续任何一步没走完(进程挂了、pipeline 报错、
    # 有人单独调 crawl_sources),抓到的文章被丢弃而水位已经跨过它们,**永久漏掉**。
    # 实测踩过一次:一轮 47 篇全丢,下一轮拉回 0 条。
    #
    # 这正是 we-mp-rss issue #440 那个 bug(「游标在采集成功前推进，导致永久漏文章」),
    # 我们在诊断微信那次故障时引用过它,不该自己再写一遍。
    #
    # 现在改为**无状态**:`recent_days` 限定时间窗,重复条目由入库时的 url_hash
    # 去重挡掉(radar_repository.upsert_raw_articles 本来就按 url_hash 判重)。
    # 代价是每轮重复拉一次窗口内的列表——SP 是本机毫秒级读库,而真正贵的正文
    # 抓取由 article_cache 兜住,所以这个代价可以忽略。

    def _window(self) -> str:
        """recent_days → 契约 window 枚举,取能覆盖住的最小档。window 与
        recent_days 剪枝看的都是发布时间(SP 侧 effective_at = published
        取不到退 discovered),服务端先截一刀,客户端剪枝再对齐到上海时区
        日界。0 = 不限。"""
        config = self.source.config or {}
        try:
            days = int(config.get("recent_days", 1))
        except (TypeError, ValueError):
            days = 1
        if days <= 0:
            return "all"
        if days <= 1:
            return "24h"
        if days <= 7:
            return "7d"
        if days <= 30:
            return "30d"
        return "all"

    # ── 拉取 ──

    def fetch(self, limit: int | None = None) -> list[RawArticle]:
        items = self._fetch_pages()
        articles = parse_sourcepilot_items(items, self.source, limit=limit)
        self._enrich_articles(articles)
        return articles

    def _fetch_pages(self) -> list[dict]:
        """按公众号拉 /api/v1/wechat/feed。注意不能走 /items?platform=:
        那边的 platform 白名单只认信源配置名(wechat 整体是一个),不认
        具体公众号名——按号过滤只有这个端点能做(实测 2026-08-04)。"""
        config = self.source.config or {}
        base_params = {
            "account": config.get("sp_platform") or self.source.name,
            "window": self._window(),
            "limit": _PAGE_SIZE,
        }
        items: list[dict] = []
        cursor: str | None = None
        for _ in range(_MAX_PAGES):
            params = dict(base_params)
            # cursor 不透明,原样透传(契约红线:消费方不得解析)
            if cursor:
                params["cursor"] = cursor
            text = fetch_url_text(
                f"{_base_url()}/api/v1/wechat/feed?{urlencode(params)}",
                accept="application/json",
                timeout=15,
            )
            payload = json.loads(text)
            meta = payload.get("meta") or {}
            _check_contract_version(meta)
            if not payload.get("ok"):
                error = payload.get("error") or {}
                code = error.get("code")
                if code == "RATE_LIMITED":
                    # SP 的正常冷却态,它自己有冷却状态机,不叠加重试也不记
                    # fetch_failed;带着已收集的条目收工
                    logger.warning(
                        "sourcepilot rate limited for %s, keeping %d items",
                        self.source.id,
                        len(items),
                    )
                    return items
                raise RuntimeError(
                    f"sourcepilot {code}: {error.get('message')}"
                )
            page_items = (payload.get("data") or {}).get("items") or []
            items.extend(page_items)
            cursor = meta.get("next_cursor")
            if not meta.get("has_more") or not cursor:
                return items
        logger.warning(
            "sourcepilot pagination hit %d-page cap for %s", _MAX_PAGES, self.source.id
        )
        return items

    # ── 正文 enrich ──

    def _enrich_articles(self, articles: list[RawArticle]) -> None:
        config = self.source.config or {}
        try:
            budget = int(config.get("sp_article_limit", _DEFAULT_ARTICLE_LIMIT))
        except (TypeError, ValueError):
            budget = _DEFAULT_ARTICLE_LIMIT
        for article in articles:
            cache_path = self.article_cache_dir / f"{article.url_hash}.json"
            if not cache_path.exists():
                if budget <= 0:
                    # 超预算降级入库(summary/title 已是 content),水位过后
                    # 该条不会再来,属可接受的首轮损耗
                    article.metadata["sp_body"] = "missing"
                    continue
                budget -= 1  # 只有真实网络调用消耗预算,缓存命中不算
            extracted = fetch_sourcepilot_article(
                article.source_url, cache_dir=self.article_cache_dir
            )
            if not extracted:
                article.metadata["sp_body"] = "missing"
                continue
            body = (extracted.get("content") or "").strip()
            if body:
                article.content = body
            # `original_blocks` / `original_paragraphs` 已在事件 metadata 白名单里
            # (radar_repository._EVENT_CONTENT_METADATA_KEYS),前端原生就渲染它们,
            # 展示侧零改动。
            for key in ("original_blocks", "original_paragraphs", "original_images"):
                value = extracted.get(key)
                if value:
                    article.metadata[key] = value
            # 不能留成 aihot_item_page_link_only —— 那个值会让前端整块跳过原文渲染
            article.metadata["content_origin"] = (
                extracted.get("content_origin") or "manual_url_fetch"
            )
