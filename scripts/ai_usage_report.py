#!/usr/bin/env python3
"""AI 用量与成本报表：读 ai_usage_stats，按天/环节算钱。

用法：
    python scripts/ai_usage_report.py               # 最近 7 天
    python scripts/ai_usage_report.py --days 1      # 只看今天
    python scripts/ai_usage_report.py --by-run      # 按刷新轮次拆开

表里只存 token 数不存金额，因为单价会变（DeepSeek 2026-08-16 起还分了峰谷），
把定价放在读取端，历史数据才不会因为改价而失真。单价见下方 PRICES，改价时
只需要动这一处。
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.config import load_env_file  # noqa: E402

# 元 / 百万 token。来源为各厂商官方定价页，括号内为核对日期。
PRICES = {
    # 百炼 qwen3.7-flash（2026-08-13）：显式缓存命中按输入价 10% 计
    "qwen3.7-flash": {"hit": 0.02, "miss": 0.2, "out": 0.8},
    # DeepSeek v4-flash 现价（2026-08-13）。2026-08-17 00:00 起改峰谷计价：
    # 空闲 0.05/1.5/4.5，高峰 0.10/3.0/9.0（北京 9-12、14-18 点为高峰）
    "deepseek-v4-flash": {"hit": 0.02, "miss": 1.0, "out": 2.0},
}
DEFAULT_PRICE = {"hit": 0.02, "miss": 1.0, "out": 2.0}
SHANGHAI = ZoneInfo("Asia/Shanghai")


def money(usage: dict, model: str) -> float:
    p = PRICES.get(model, DEFAULT_PRICE)
    return (
        usage["cache_hit_tokens"] * p["hit"]
        + usage["cache_miss_tokens"] * p["miss"]
        + usage["completion_tokens"] * p["out"]
    ) / 1_000_000


def fetch(days: int):
    import psycopg

    dsn = os.environ["DATABASE_URL"].replace("postgresql+psycopg", "postgresql")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            select recorded_at, pipeline_run_id, provider, model, operation,
                   calls, prompt_tokens, cache_hit_tokens, cache_miss_tokens,
                   completion_tokens, reasoning_tokens
            from ai_usage_stats where recorded_at >= %s order by recorded_at
            """,
            (since,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def expected_runs_per_day() -> int | None:
    """按 refresh_schedule 的间隔算出一天应有多少轮，用于外推不完整的样本。"""
    import psycopg

    dsn = os.environ["DATABASE_URL"].replace("postgresql+psycopg", "postgresql")
    try:
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            cur = conn.cursor()
            cur.execute("select enabled, interval_minutes from refresh_schedule limit 1")
            row = cur.fetchone()
    except Exception:
        return None
    if not row or not row[0] or not row[1]:
        return None
    return max(1, round(24 * 60 / int(row[1])))


def blank() -> dict:
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "cache_hit_tokens": 0,
        "cache_miss_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
    }


def add(into: dict, row: dict) -> None:
    for key in into:
        into[key] += int(row[key] or 0)


def render(title: str, groups: dict, model_of: dict) -> float:
    width = max([len(str(k)) for k in groups] + [10]) + 2
    print(f"\n=== {title}")
    print(f"{'环节':<{width}}{'调用':>6}{'输入':>10}{'命中率':>8}{'输出':>9}{'思考':>8}{'成本':>10}")
    print("-" * (width + 51))
    total = 0.0
    for key in sorted(groups, key=lambda k: -money(groups[k], model_of[k])):
        u = groups[key]
        cost = money(u, model_of[key])
        total += cost
        hit = 100 * u["cache_hit_tokens"] / u["prompt_tokens"] if u["prompt_tokens"] else 0
        print(
            f"{str(key):<{width}}{u['calls']:>6}{u['prompt_tokens']:>10}{hit:>7.0f}%"
            f"{u['completion_tokens']:>9}{u['reasoning_tokens']:>8}  ¥{cost:>7.4f}"
        )
    print(f"{'合计':<{width}}{'':>6}{'':>10}{'':>8}{'':>9}{'':>8}  ¥{total:>7.4f}")
    return total


def main() -> int:
    load_env_file(ROOT / ".env")
    parser = argparse.ArgumentParser(description="AI token 用量与成本报表")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--by-run", action="store_true", help="按刷新轮次拆开")
    args = parser.parse_args()

    rows = fetch(args.days)
    if not rows:
        print(f"最近 {args.days} 天没有用量记录。"
              "\n埋点在每轮刷新结束时落库，若刚部署请等下一轮刷新。")
        return 0

    by_model_op: dict = defaultdict(blank)
    model_of: dict = {}
    by_day: dict = defaultdict(blank)
    day_model: dict = {}
    for row in rows:
        key = f"{row['model']} / {row['operation']}"
        add(by_model_op[key], row)
        model_of[key] = row["model"]
        day = row["recorded_at"].astimezone(SHANGHAI).date().isoformat()
        add(by_day[f"{day} {row['model']}"], row)
        day_model[f"{day} {row['model']}"] = row["model"]

    render(f"最近 {args.days} 天 · 按模型与环节", by_model_op, model_of)
    total = render(f"最近 {args.days} 天 · 按天", by_day, day_model)

    days_seen = len({r["recorded_at"].astimezone(SHANGHAI).date() for r in rows})
    runs = len({r["pipeline_run_id"] for r in rows if r["pipeline_run_id"]})
    if days_seen and runs:
        print(f"\n覆盖 {days_seen} 天 / {runs} 轮刷新，每轮均值 ¥{total / runs:.4f}")
        # 刚部署时通常只有一两轮数据，直接除以天数会严重低估全天开销，
        # 所以按调度间隔推算"如果这样跑满一天"的花费
        expected = expected_runs_per_day()
        if expected and runs < expected * days_seen:
            print(f"  ⚠ 数据不足一整天（调度为每天 {expected} 轮）。"
                  f"按每轮均值外推：约 ¥{expected * total / runs:.2f}/天、"
                  f"¥{30 * expected * total / runs:.1f}/月")
        else:
            print(f"  日均 ¥{total / days_seen:.4f}，折合每月约 ¥{30 * total / days_seen:.2f}")

    if args.by_run:
        by_run: dict = defaultdict(blank)
        run_model: dict = {}
        for row in rows:
            key = f"run {row['pipeline_run_id']} / {row['model']}"
            add(by_run[key], row)
            run_model[key] = row["model"]
        render("按刷新轮次", by_run, run_model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
