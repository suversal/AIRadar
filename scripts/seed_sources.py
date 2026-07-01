#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.data.default_sources import default_sources
from app.storage.json_store import save_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed default source configuration.")
    parser.add_argument("--output", default="data/sources.json")
    args = parser.parse_args()

    output = ROOT / args.output
    save_sources(output, default_sources())
    print(f"Seeded {len(default_sources())} sources to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

