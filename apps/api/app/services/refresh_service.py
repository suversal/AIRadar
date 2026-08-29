from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.crawlers.run import crawl_sources
from app.data.default_sources import default_sources
from app.models.domain import PipelineResult, RawArticle, Source
from app.pipeline.persistence import persist_pipeline_result_to_database
from app.pipeline.runner import run_pipeline
from app.services.ai_service import build_same_event_verifier, provider_from_env
from app.storage.json_store import (
    article_to_dict,
    cluster_to_dict,
    load_sources,
    processed_to_dict,
    report_to_dict,
    save_articles,
    save_sources,
    write_json,
)

logger = logging.getLogger(__name__)


AUTO_SEEDED_SOURCE_IDS = {
    "aihot_feed",
    "telegram_zaihuapd",
    "telegram_xhqcankao",
    "telegram_dnspodt",
    "x_tweet_account",
    "x_tweet_topic",
}


def crawl_result_url(article: RawArticle) -> str:
    """Keep public 阅读原文 URLs while linking admin AI HOT results to AI HOT."""
    return str(article.metadata.get("aihot_permalink") or article.source_url)


def ensure_auto_seeded_sources(repository: Any) -> list[Source]:
    """Return all configured sources after inserting newly shipped defaults.

    Existing rows remain authoritative so admin edits are never overwritten.
    An empty database still receives the complete default catalog; an existing
    installation receives only the small allowlist of defaults intentionally
    marked for automatic rollout.
    """
    sources = repository.get_all_sources()
    if not sources:
        missing = default_sources()
    else:
        existing_ids = {source.id for source in sources}
        missing = [
            source
            for source in default_sources()
            if source.id in AUTO_SEEDED_SOURCE_IDS and source.id not in existing_ids
        ]
    if missing:
        repository.upsert_sources(missing)
        commit = getattr(getattr(repository, "session", None), "commit", None)
        if callable(commit):
            commit()
        sources.extend(missing)
    return sources


def _raw_items_by_source(raw_articles: list[RawArticle]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for article in raw_articles:
        grouped.setdefault(article.source_id, []).append(
            {
                "source_url": article.source_url,
                "title": article.title,
                "content": article.content,
                "author": article.author,
                "published_at": article.published_at,
                "language": article.language,
                "raw_score": article.raw_score,
                "metadata": article.metadata,
            }
        )
    return grouped


def _load_or_seed_sources(sources_path: Path) -> list[Source]:
    if not sources_path.exists():
        save_sources(sources_path, default_sources())
    sources = load_sources(sources_path)
    existing_ids = {source.id for source in sources}
    missing = [
        source
        for source in default_sources()
        if source.id in AUTO_SEEDED_SOURCE_IDS and source.id not in existing_ids
    ]
    if missing:
        sources.extend(missing)
        save_sources(sources_path, sources)
    return sources


def _load_sources(database_url: str | None, sources_path: Path) -> list[Source]:
    """DB is the source of truth in database mode so admin edits take effect;
    JSON stays the fallback for file-only deployments."""
    if database_url:
        from app.db.session import build_session_factory
        from app.repositories.radar_repository import RadarRepository

        session = build_session_factory(database_url)()
        try:
            repository = RadarRepository(session)
            return ensure_auto_seeded_sources(repository)
        finally:
            session.close()
    return _load_or_seed_sources(sources_path)


def _build_auto_crawl_results(
    crawl_report: dict[str, Any],
    result: PipelineResult,
    *,
    now: datetime,
    existing_url_hashes: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build the same {origin, at, status, error, fetched_count,
    accepted_count, articles: [...]} shape the manual per-source fetch
    endpoint returns, computed from the real AI outcomes - not just the
    crawl-stage fetch count - so a full automatic sync leaves every source
    with an honest per-article saved/rejected breakdown, and the admin
    'last crawl result' column looks identical whether it came from a full
    sync or a single-source manual fetch."""
    at = now.isoformat()
    existing_url_hashes = existing_url_hashes or set()
    processed_by_raw_id = {
        processed.raw_article_id: processed for processed in result.processed_articles
    }
    articles_by_source: dict[str, list[RawArticle]] = {}
    for article in result.raw_articles:
        articles_by_source.setdefault(article.source_id, []).append(article)

    results: dict[str, dict[str, Any]] = {}
    for source_id, crawl_entry in crawl_report.get("per_source", {}).items():
        if crawl_entry.get("status") != "ok":
            results[source_id] = {
                "origin": "auto",
                "at": at,
                "status": "failed",
                "error": crawl_entry.get("error"),
                "fetched_count": 0,
                "accepted_count": 0,
                "ingested_count": 0,
                "duration_ms": crawl_entry.get("duration_ms"),
                "articles": [],
            }
            continue
        source_articles = articles_by_source.get(source_id, [])
        article_results: list[dict[str, Any]] = []
        saved_count = 0
        ingested_count = 0
        for article in source_articles:
            # 与手动抓取路径一致:库里已存在的标 duplicate,让"已存在"
            # 和"非AI丢弃"在信源明细里一眼可分;"通过"只统计本轮新入选。
            # ingested_count 口径对齐 pipeline_runs 的 new_raw_count:新文章
            # 里除 not_ai_related 之外全算入库(未达精选的也算,因为它的
            # raw_articles 行确实保留了),否则"入选"数会被误当成"新入库"数看
            existing = article.url_hash in existing_url_hashes
            processed = processed_by_raw_id.get(article.id)
            if processed is not None:
                selected = bool(processed.selected)
                if not existing:
                    ingested_count += 1
                    if selected:
                        saved_count += 1
                article_results.append(
                    {
                        "title": processed.title_zh or article.title,
                        "url": crawl_result_url(article),
                        "outcome": "duplicate"
                        if existing
                        else ("saved" if selected else "rejected"),
                        "selected": selected,
                        "final_score": processed.final_score,
                        "category": processed.category,
                        "reason": processed.selection_reason if selected else processed.rejection_reason,
                    }
                )
                continue
            skipped_reason = result.skipped_reason_by_raw_id.get(article.id)
            if not existing and skipped_reason != "not_ai_related":
                ingested_count += 1
            article_results.append(
                {
                    "title": article.title,
                    "url": crawl_result_url(article),
                    "outcome": "duplicate" if existing else "rejected",
                    "selected": False,
                    "final_score": None,
                    "category": None,
                    "reason": skipped_reason,
                }
            )
        results[source_id] = {
            "origin": "auto",
            "at": at,
            "status": "ok",
            "error": None,
            "fetched_count": len(source_articles),
            "accepted_count": saved_count,
            "ingested_count": ingested_count,
            "duration_ms": crawl_entry.get("duration_ms"),
            "articles": article_results,
        }
    return results


def _persist_auto_crawl_results(database_url: str | None, results: dict[str, dict[str, Any]]) -> None:
    if not database_url or not results:
        return
    from app.db.session import build_session_factory
    from app.repositories.radar_repository import RadarRepository

    session = build_session_factory(database_url)()
    try:
        repository = RadarRepository(session)
        for source_id, result in results.items():
            repository.set_last_crawl_result(source_id, result)
        session.commit()
    finally:
        session.close()


def _persist_source_health(database_url: str | None, per_source: dict[str, Any]) -> None:
    if not database_url:
        return
    from app.db.session import build_session_factory
    from app.repositories.radar_repository import RadarRepository

    session = build_session_factory(database_url)()
    try:
        RadarRepository(session).update_source_health(per_source)
        session.commit()
    finally:
        session.close()


#: 连续失败多少次才告警。1 次多半是对方抽风，3 次就是真出事了。
SOURCE_FAILURE_ALERT_THRESHOLD = 3


def _alert_persistently_failing_sources(database_url: str | None) -> None:
    """把连续失败的信源单独推一条 Telegram，不要淹在同步报告里。

    每次同步都会推一份包含全部信源的报告，65 行里有一两行变红是看不出来的。
    而信源静默失效的代价很实在：AR 的内容会悄悄变少，等发现时可能已经断了好几天。

    这条尤其针对 aihot_feed / aihot_all —— AIHOT 那边刚上了自动封禁策略
    （见 docs/2026-08-13-hardening-plan.md 第 3.3 节），我们一旦被划进去，
    抓取器会 best-effort 地降级而不是报错，没有告警就完全无感。

    整个函数是尽力而为的：告警失败绝不能影响同步流程本身。"""
    if not database_url:
        return
    try:
        from app.db.session import build_session_factory
        from app.repositories.radar_repository import RadarRepository
        from app.services.telegram_notifier import send_telegram_message

        session = build_session_factory(database_url)()
        try:
            failing = RadarRepository(session).list_persistently_failing_sources(
                SOURCE_FAILURE_ALERT_THRESHOLD
            )
        finally:
            session.close()

        if not failing:
            return

        lines = [f"⚠️ 信源连续失败（≥{SOURCE_FAILURE_ALERT_THRESHOLD} 次）", ""]
        for entry in sorted(failing, key=lambda item: -item["error_count"]):
            last = entry["last_success_at"]
            last_text = last.strftime("%Y-%m-%d %H:%M") if last else "从未成功"
            lines.append(
                f"· {entry['name']}（{entry['id']}）连续 {entry['error_count']} 次，"
                f"最后成功：{last_text}"
            )
        send_telegram_message("\n".join(lines))
    except Exception:  # pragma: no cover - 告警链路不允许影响同步
        logger.warning("failed to send source failure alert", exc_info=True)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def should_trigger_refresh(config: dict[str, Any], now: datetime) -> bool:
    """Pure decision function for the in-process scheduler: whether a
    refresh is due given the persisted schedule config and the current time."""
    if not config.get("enabled"):
        return False
    last_triggered_at = config.get("last_triggered_at")
    if not last_triggered_at:
        return True
    last = datetime.fromisoformat(last_triggered_at)
    interval_minutes = int(config.get("interval_minutes") or 0)
    return now - last >= timedelta(minutes=interval_minutes)


class RefreshAlreadyRunning(RuntimeError):
    """Another refresh's 'running' row is fresh - refuse to start a second
    one (manual trigger and the scheduler once ran the same batch 24s
    apart, doubling AI spend and racing persists)."""

    def __init__(self, active: dict[str, Any]):
        self.active = active
        super().__init__(
            f"refresh already running (run #{active.get('id')}, "
            f"phase={active.get('phase')}, started_at={active.get('started_at')})"
        )


def refresh_latest_report(
    *,
    data_dir: Path,
    database_url: str | None,
    report_date: date | None = None,
) -> dict[str, Any]:
    resolved_date = report_date or date.today()
    generated_at = datetime.now(timezone.utc)
    pipeline_run_id: int | None = None
    if database_url:
        from app.pipeline.persistence import (
            get_active_pipeline_run_in_database,
            start_pipeline_run_in_database,
        )

        active = get_active_pipeline_run_in_database(database_url)
        if active is not None:
            raise RefreshAlreadyRunning(active)
        # the 'running' row is what lets anyone ask the DB "is a refresh
        # in flight right now, and since when"
        pipeline_run_id = start_pipeline_run_in_database(
            database_url, started_at=generated_at, phase="crawling"
        )
    try:
        return _run_refresh(
            data_dir=data_dir,
            database_url=database_url,
            resolved_date=resolved_date,
            generated_at=generated_at,
            pipeline_run_id=pipeline_run_id,
        )
    except Exception as exc:
        # a failed run must leave a durable trace, not just an in-memory
        # job status; recording is best-effort and never masks the failure
        if database_url:
            from app.pipeline.persistence import record_failed_pipeline_run

            record_failed_pipeline_run(
                database_url,
                started_at=generated_at,
                error=str(exc),
                pipeline_run_id=pipeline_run_id,
            )
        from app.services.telegram_notifier import format_sync_report, send_telegram_message

        send_telegram_message(
            format_sync_report(
                status="failed", report_date=resolved_date.isoformat(), error=str(exc)
            )
        )
        raise


def _run_refresh(
    *,
    data_dir: Path,
    database_url: str | None,
    resolved_date: date,
    generated_at: datetime,
    pipeline_run_id: int | None = None,
) -> dict[str, Any]:
    sources_path = data_dir / "sources.json"
    sources = _load_sources(database_url, sources_path)

    raw_articles, crawl_report = crawl_sources(sources)
    x_article_report: dict[str, Any] | None = None

    # X 推文镜像同步（SourcePilot Phase 4）。挂在应用内定时 refresh 里，而不是
    # run_scheduled_refresh.sh——后者早已不是活跃入口（实测停在 2026-08-06），
    # 真正在跑的是这条 refresh_latest_report 链路。推文先走独立同步表；开启
    # 精选接入后，仅合格原创会在下方转换成 RawArticle，仍不发生第二次抓取。
    # best-effort：SP 不在线不该拦住 AR 出日报。
    if database_url:
        try:
            from app.db.session import build_session_factory, session_scope
            from app.repositories.radar_repository import RadarRepository
            from app.services.x_tweets_sync import sync_x_tweets

            session_factory = build_session_factory(database_url)
            with session_scope(session_factory) as session:
                x_report = sync_x_tweets(RadarRepository(session))
            logger.info("X tweets sync in refresh: %s", x_report)
        except Exception:
            logger.warning("X tweets sync failed during refresh", exc_info=True)

        # 中文化必须跟着同步一起跑。历史坑（2026-08-14 修）：翻译当初只挂在
        # scripts/sync_x_tweets.py 上，后来同步搬进这条 refresh 链路时没把翻译
        # 一起搬，而那个脚本早已不是活跃入口——结果线上英文推文长期零译文，
        # 且没有任何报错（同步照常成功）。两者要留在同一个入口里。
        # 独立 try：翻译挂了不该回滚已入库的推文。
        try:
            from app.db.session import build_session_factory, session_scope
            from app.repositories.radar_repository import RadarRepository
            from app.services.ai_service import FakeAIProvider
            from app.services.x_tweets_translate import translate_x_tweets

            translate_provider = provider_from_env()
            if isinstance(translate_provider, FakeAIProvider):
                # 没配 AI Key 时跳过，而不是把「译文：xxx」的假翻译写进库
                logger.info("X tweets translation skipped: no ai provider configured")
            else:
                session_factory = build_session_factory(database_url)
                with session_scope(session_factory) as session:
                    translation_report = translate_x_tweets(
                        RadarRepository(session), translate_provider
                    )
                logger.info("X tweets translation in refresh: %s", translation_report)
        except Exception:
            logger.warning("X tweets translation failed during refresh", exc_info=True)

        # Eligible originals join the ordinary pipeline only after SP mirror
        # sync + translation.  This is a database-to-domain conversion: no
        # crawler, no second SP request and no attempt to fetch the X page.
        if os.getenv("X_TWEET_ARTICLE_PIPELINE_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            try:
                from app.db.session import build_session_factory, session_scope
                from app.repositories.radar_repository import RadarRepository
                from app.services.x_tweet_articles import load_x_tweet_articles

                session_factory = build_session_factory(database_url)
                with session_scope(session_factory) as session:
                    x_articles, x_article_report = load_x_tweet_articles(
                        RadarRepository(session),
                        sources,
                        now=generated_at,
                        recent_days=_env_int("X_TWEET_ARTICLE_PIPELINE_RECENT_DAYS", 7),
                        limit=_env_int("X_TWEET_ARTICLE_PIPELINE_BATCH_LIMIT", 100),
                    )
                raw_articles.extend(x_articles)
                logger.info("X tweet article pipeline candidates: %s", x_article_report)
            except Exception:
                logger.warning("X tweet article conversion failed during refresh", exc_info=True)

    # 只处理最近 N 天发布(上海时区,2026-07-12 深夜决策,2026-07-15 从固定
    # "仅当天"改为按信源 config.recent_days 配置):feed 的陈年存量在
    # intake 之前出局,不入库、不进任何统计;标记 ingest_all_dates 的源
    # (AI HOT 全量流)豁免日期筛选,全部保留
    from app.pipeline.runner import filter_articles_published_on, source_recent_days

    raw_articles = filter_articles_published_on(
        raw_articles,
        resolved_date,
        exempt_source_ids={
            source.id for source in sources if (source.config or {}).get("ingest_all_dates")
        },
        recent_days_by_source={source.id: source_recent_days(source) for source in sources},
    )
    _persist_source_health(database_url, crawl_report.get("per_source", {}))
    # Internal X identities are observable like sources in this run, but they
    # are deliberately added only after real crawler health is persisted.
    if x_article_report is not None:
        for source_id, count in x_article_report.get("by_source", {}).items():
            crawl_report.setdefault("per_source", {})[source_id] = {
                "status": "ok",
                "article_count": count,
                "fetched_count": count,
                "duration_ms": 0,
                "error": None,
                "pipeline_candidates": x_article_report.get("candidates", 0),
                "conversion_failed": x_article_report.get("failed", 0),
            }
        crawl_report["x_article_pipeline"] = x_article_report
    # 紧跟在健康写入之后：此时 error_count 已经是本轮更新后的值
    _alert_persistently_failing_sources(database_url)
    # 缓存快照必须在 intake 之前拍:它代表"本轮开始前库里已有什么",
    # 是信源明细区分 已存在/新入选 的依据——intake 先跑会把本轮新文章
    # 全部误判成已存在(39 号运行的"入选全 0"事故)
    cached_results: dict[str, Any] = {}
    if database_url:
        from app.pipeline.persistence import load_cached_results_from_database

        cached_results = load_cached_results_from_database(
            database_url, [article.url_hash for article in raw_articles]
        )
    # 四步流程第 1 步:抓取一结束立即把新文章插入库(默认未入选),
    # 数据先于 AI 处理可见;返回的清单是台账"入库/非AI"指标的事实源
    intake_inserted_ids: list[str] | None = None
    if database_url:
        from app.pipeline.persistence import persist_raw_intake_to_database

        intake_inserted_ids = persist_raw_intake_to_database(
            database_url, raw_articles, pipeline_run_id=pipeline_run_id
        )
    _report_progress(
        database_url,
        pipeline_run_id,
        phase="scoring",
        raw_count=len(raw_articles),
        source_report=crawl_report.get("per_source", {}),
    )
    crawl_dir = data_dir / "crawl_checks"
    raw_path = crawl_dir / f"{resolved_date.isoformat()}-refresh-raw.json"
    crawl_report_path = crawl_dir / f"{resolved_date.isoformat()}-refresh-crawl-report.json"
    save_articles(raw_path, raw_articles)
    write_json(crawl_report_path, crawl_report)

    ai_provider = provider_from_env()

    # 逐条即时落库:每评完一条马上写库,数据在整轮结束前持续可见
    on_article_processed = None
    if database_url:
        from app.pipeline.persistence import persist_single_article_to_database
        from app.pipeline.runner import _embedding_model_name

        def on_article_processed(article, processed, embedding):  # noqa: ANN001
            persist_single_article_to_database(
                database_url,
                article,
                processed,
                embedding,
                embedding_model=_embedding_model_name(ai_provider),
                pipeline_run_id=pipeline_run_id,
            )

    result = run_pipeline(
        sources=sources,
        raw_items_by_source=_raw_items_by_source(raw_articles),
        ai_provider=ai_provider,
        now=generated_at,
        report_date=resolved_date,
        ai_concurrency=_env_int("AI_PIPELINE_CONCURRENCY", 1),
        cached_results=cached_results,
        on_article_processed=on_article_processed,
        # 0.85 was too low for bge-small-zh-v1.5: real-data verification
        # found unrelated AI-news articles scoring 0.79-0.89 against each
        # other, so a lower threshold merged unrelated events together.
        # 2026-07-21: recalibrated 0.93 -> 0.90 after sampling 14 days of
        # same-day zh-language pairs - see core/config.py for the numbers.
        cluster_similarity_threshold=_env_float("CLUSTER_SIMILARITY_THRESHOLD", 0.90),
        cluster_window_hours=_env_int("CLUSTER_WINDOW_HOURS", 24),
    )

    # 阶段耗时落盘:定位"AI 处理中"这个粗阶段里时间的真实去向
    try:
        timings_path = data_dir / "logs" / "stage_timings.log"
        timings_path.parent.mkdir(parents=True, exist_ok=True)
        with timings_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "run_id": pipeline_run_id,
                        "generated_at": generated_at.isoformat(),
                        "raw_count": len(result.raw_articles),
                        "processed_count": len(result.processed_articles),
                        **result.stage_timings,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except OSError:
        pass  # 观测日志不阻塞主流程

    pipeline_dir = data_dir / "crawl_checks" / f"{resolved_date.isoformat()}-refresh-pipeline"
    write_json(pipeline_dir / "raw_articles.json", [article_to_dict(item) for item in result.raw_articles])
    write_json(
        pipeline_dir / "processed_articles.json",
        [processed_to_dict(item) for item in result.processed_articles],
    )
    write_json(pipeline_dir / "event_clusters.json", [cluster_to_dict(item) for item in result.event_clusters])
    write_json(pipeline_dir / "daily_report.json", report_to_dict(result.daily_report))

    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{resolved_date.isoformat()}.md").write_text(
        result.daily_report.markdown,
        encoding="utf-8",
    )
    write_json(reports_dir / f"{resolved_date.isoformat()}.json", result.daily_report.json_data)

    # replaces the coarse crawl-stage source_report with the real per-article
    # saved/rejected breakdown, now that AI processing has actually run
    auto_crawl_results = _build_auto_crawl_results(
        crawl_report, result, now=generated_at, existing_url_hashes=set(cached_results)
    )
    _persist_auto_crawl_results(database_url, auto_crawl_results)

    _report_progress(database_url, pipeline_run_id, phase="persisting")
    persistence_summary = None
    if database_url:
        persistence_summary = persist_pipeline_result_to_database(
            database_url,
            sources,
            result,
            cluster_window_hours=_env_int("CLUSTER_WINDOW_HOURS", 24),
            similarity_threshold=_env_float("CLUSTER_SIMILARITY_THRESHOLD", 0.90),
            started_at=generated_at,
            pipeline_run_id=pipeline_run_id,
            source_report=auto_crawl_results,
            intake_inserted_ids=intake_inserted_ids,
            same_event_verifier=build_same_event_verifier(ai_provider),
        )
        _report_progress(database_url, pipeline_run_id, phase="reports")
        _regenerate_daily_summary(database_url, resolved_date, ai_provider)
        _regenerate_period_reports(database_url, resolved_date, ai_provider)

    # after the last AI call of the run (the period summaries), so the ledger
    # covers scoring, translation and reports alike
    _persist_ai_usage(database_url, pipeline_run_id, ai_provider)

    # 每次同步完成后推送完整结果到 Telegram(2026-07-12 深夜决策)。
    # 指标读自 persistence_summary(唯一事实源),不重新计算——防止和
    # 台账口径出现两处不一致
    from app.services.telegram_notifier import format_sync_report, send_telegram_message

    duplicate_count = (
        len(raw_articles) - persistence_summary.new_raw_count - persistence_summary.non_ai_dropped_count
        if persistence_summary is not None
        else 0
    )
    send_telegram_message(
        format_sync_report(
            status="succeeded",
            report_date=resolved_date.isoformat(),
            raw_count=len(raw_articles),
            duplicate_count=duplicate_count,
            non_ai_dropped_count=persistence_summary.non_ai_dropped_count if persistence_summary else 0,
            new_raw_count=persistence_summary.new_raw_count if persistence_summary else 0,
            new_selected_count=persistence_summary.new_selected_count if persistence_summary else 0,
            cluster_count=len(result.event_clusters),
            source_report=auto_crawl_results,
            source_names={source.id: source.name for source in sources},
        )
    )

    return {
        "status": "ok",
        "report_date": resolved_date.isoformat(),
        "generated_at": generated_at.isoformat(),
        "ai_provider": ai_provider.__class__.__name__,
        "ai_concurrency": _env_int("AI_PIPELINE_CONCURRENCY", 1),
        "crawled_count": len(raw_articles),
        "scored_count": len(result.processed_articles),
        "selected_count": len([item for item in result.processed_articles if item.selected]),
        "cluster_count": len(result.event_clusters),
        "article_count": result.daily_report.article_count,
        "skipped_reasons": result.skipped_reasons,
        "crawl_skipped_reasons": crawl_report.get("skipped_reasons", {}),
        "x_article_pipeline": x_article_report,
        "persisted": persistence_summary is not None,
        "raw_path": str(raw_path),
        "crawl_report_path": str(crawl_report_path),
    }


def _report_progress(
    database_url: str | None,
    pipeline_run_id: int | None,
    *,
    phase: str,
    raw_count: int | None = None,
    source_report: dict[str, Any] | None = None,
) -> None:
    """Best-effort heartbeat onto the running row so the admin dashboard can
    show which stage the refresh is in and how each source actually did."""
    if not database_url or pipeline_run_id is None:
        return
    from app.pipeline.persistence import update_pipeline_run_progress_in_database

    update_pipeline_run_progress_in_database(
        database_url,
        pipeline_run_id,
        phase=phase,
        raw_count=raw_count,
        source_report=source_report,
    )


def _persist_ai_usage(
    database_url: str | None, pipeline_run_id: int | None, ai_provider: Any
) -> None:
    """Drain this run's token ledger into ai_usage_stats.

    The collector is only drained once there is somewhere to put the counts,
    so a file-only run does not silently discard them. A run that crashes
    before reaching here leaves its counts in the collector and the next run
    persists them: daily totals stay correct, only the run attribution of
    that slice shifts forward.
    """
    if not database_url:
        return
    collector = getattr(ai_provider, "usage_collector", None)
    if collector is None:
        return
    usages = collector.drain()
    if not usages:
        return

    from app.db.session import build_session_factory
    from app.repositories.radar_repository import RadarRepository

    # cost bookkeeping must never fail a refresh that already produced a
    # report, so opening the session is inside the guard too - a database
    # that is down loses this slice of counts, not the run's actual output
    session = None
    try:
        session = build_session_factory(database_url)()
        RadarRepository(session).record_ai_usage(
            usages,
            provider=ai_provider.__class__.__name__,
            pipeline_run_id=pipeline_run_id,
        )
        session.commit()
    except Exception:
        if session is not None:
            session.rollback()
        logger.exception("failed to persist AI usage for run %s", pipeline_run_id)
    finally:
        if session is not None:
            session.close()


def _regenerate_daily_summary(database_url: str, report_date: date, ai_provider: Any) -> None:
    """Write the day's AI mainline and category notes after the masthead lands.

    Reads the resolved daily payload - the same one the page reads - rather
    than the in-run result, so the summary is written from exactly the events
    a reader will see (post redirect-dedup, post moderation).

    Skips the AI call when the day's material fingerprint is unchanged. The
    pipeline runs 12-14 times a day and most runs add nothing to an already
    settled day; without this every one of them would re-buy the same text.

    Failures degrade to leaving the previous summary in place and never block
    the refresh - same contract as the period reports below.
    """
    from app.db.session import build_session_factory
    from app.repositories.radar_repository import RadarRepository
    from app.services.daily_summary_service import build_daily_summary

    session = build_session_factory(database_url)()
    try:
        repository = RadarRepository(session)
        payload = repository.get_daily_report_payload(report_date)
        if not payload:
            return
        summary = build_daily_summary(
            report_date=report_date,
            items=payload.get("items") or [],
            ai_provider=ai_provider,
            previous_digest=repository.get_daily_summary_digest(report_date),
            previous_status=repository.get_daily_summary_status(report_date),
        )
        # None means "material unchanged" or "the call failed but a published
        # mainline is already stored" - either way, keep what is stored
        if summary is None:
            return
        repository.upsert_daily_summary(report_date, summary)
        session.commit()
    except Exception:
        session.rollback()
        logger.warning("daily summary generation failed for %s", report_date, exc_info=True)
    finally:
        session.close()


def _regenerate_period_reports(database_url: str, anchor_date: date, ai_provider: Any) -> None:
    """After the daily report lands, refresh the enclosing week/month reports
    so their AI mainline always covers the newest day. Failures degrade to
    the fallback summary inside build_period_report and never block.

    Items come from the days' actual published daily reports (same
    build_period_payload merge the public read-path fallback uses), not a
    fresh query over every scored event in the date range - a period report
    is a rollup of daily reports, not an independent re-selection. Otherwise
    events that were scored/clustered but never made any day's daily report
    would leak into the weekly/monthly snapshot.

    Each refresh considers the current period *and the one before it*
    (period_targets_for): the previous period's first post-rollover pass is
    what finalizes it from its days' settled state. A finalized report is
    skipped outright - its text and snapshot are frozen - and an unchanged
    summary input reuses the stored text instead of re-buying it, so the
    12-14 daily runs no longer rewrite the live period's prose each time."""
    from app.api.public import build_period_payload
    from app.db.session import build_session_factory
    from app.repositories.radar_repository import RadarRepository
    from app.services.period_summary_service import (
        build_period_report,
        period_range_for_key,
        period_targets_for,
    )

    session = build_session_factory(database_url)()
    try:
        repository = RadarRepository(session)
        for kind in ("weekly", "monthly"):
            for key in period_targets_for(kind, anchor_date):
                # 每个期次自己一个事务：四个目标原先共用一次 commit，任何一个
                # 环节抛错都会把前面几个已经买到的综述和上一期的封版一起回滚，
                # 下一轮再花一次钱买同样的东西。而且 except 是裸的、没有日志，
                # 确定性的脏数据会让周月报静默停更、轮轮重复付费还查不到线索。
                try:
                    stored = repository.get_period_report(kind, key)
                    if stored and stored.get("finalized_at"):
                        continue
                    range_start, range_end = period_range_for_key(kind, key)
                    daily_payloads = repository.get_daily_report_payloads_between(
                        range_start, range_end
                    )
                    if not daily_payloads and stored is None:
                        # nothing was ever published in this period; a report row
                        # here would be an empty shell with a made-up summary
                        continue
                    merged = build_period_payload(
                        daily_payloads, mode=kind, range_start=range_start, range_end=range_end
                    )
                    report = build_period_report(
                        kind=kind,
                        anchor=range_start,
                        items=merged["items"],
                        report_dates=sorted(merged["report_dates"]),
                        ai_provider=ai_provider,
                        previous=stored,
                        finalize=anchor_date > range_end,
                    )
                    repository.upsert_period_report(report)
                    session.commit()
                except Exception:
                    session.rollback()
                    logger.warning(
                        "period report generation failed for %s %s", kind, key, exc_info=True
                    )
    finally:
        session.close()
