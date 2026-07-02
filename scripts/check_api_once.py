#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.api.smoke import (
    all_api_smoke_checks_passed,
    format_api_smoke_results,
    run_api_smoke_checks,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a running Suversal AI Radar API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    results = run_api_smoke_checks(args.base_url, report_date=args.date)
    print(format_api_smoke_results(results))
    return 0 if all_api_smoke_checks_passed(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
