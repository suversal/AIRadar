#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.db.health import all_checks_passed, format_check_results, run_database_health_checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local Docker Postgres/pgvector/Redis.")
    parser.add_argument("--compose-file", default="infra/docker-compose.yml")
    parser.add_argument("--expected-tables", type=int, default=8)
    args = parser.parse_args()

    results = run_database_health_checks(
        compose_file=args.compose_file,
        expected_tables=args.expected_tables,
    )
    print(format_check_results(results))
    return 0 if all_checks_passed(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
