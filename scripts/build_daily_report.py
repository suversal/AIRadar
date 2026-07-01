#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.storage.json_store import read_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy generated daily report to requested format.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--reports-dir", default="data/reports")
    args = parser.parse_args()

    reports_dir = ROOT / args.reports_dir
    if args.format == "markdown":
        path = reports_dir / f"{args.date}.md"
        print(path.read_text(encoding="utf-8"))
    else:
        payload = read_json(reports_dir / f"{args.date}.json")
        write_json(reports_dir / f"{args.date}.json", payload)
        print(f"Wrote {reports_dir / f'{args.date}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

