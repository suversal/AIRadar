#!/usr/bin/env python3
"""同步 SourcePilot 的 X 推文进本地 x_tweets 表（接入方案 Phase 4）。

独立于 crawl/pipeline：推文不进 LLM 管线，失败也不该影响日报生成，
所以 run_scheduled_refresh.sh 里以「允许失败」的方式调用本脚本。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.config import load_env_file


def main() -> int:
    load_env_file(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Sync X tweets from SourcePilot.")
    parser.add_argument("--report", default="data/x_tweets_sync_report.json")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("SKIP x tweets sync: DATABASE_URL not set")
        return 0

    from app.db.session import build_session_factory, session_scope
    from app.repositories.radar_repository import RadarRepository
    from app.services.ai_service import FakeAIProvider, provider_from_env
    from app.services.x_tweets_sync import sync_x_tweets
    from app.services.x_tweets_translate import translate_x_tweets

    session_factory = build_session_factory(database_url)
    with session_scope(session_factory) as session:
        report = sync_x_tweets(RadarRepository(session))

    # 翻译独立于同步提交：翻译挂了不影响已入库的推文
    provider = provider_from_env()
    if isinstance(provider, FakeAIProvider):
        # 没配 AI Key 时跳过而不是写「译文：xxx」的假翻译进库
        report["translation"] = {"skipped": "no ai provider configured"}
    else:
        with session_scope(session_factory) as session:
            report["translation"] = translate_x_tweets(
                RadarRepository(session), provider
            )

    report_path = ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"X tweets sync: inserted={report['inserted']} updated={report['updated']} "
        f"handles={list(report['handles'])} translation={report.get('translation')}"
    )
    failed = [h for h, e in report["handles"].items() if e.get("error")]
    if failed:
        print(f"WARN failed handles: {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
