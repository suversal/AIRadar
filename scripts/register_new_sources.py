#!/usr/bin/env python3
"""One-off tool: push any default_sources() entry that is missing from the
DB into it. Does not touch sources that already exist (so it never
resurrects a source an admin deliberately deleted), and does not run
automatically as part of the pipeline - run it by hand after adding new
entries to app/data/default_sources.py."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.config import load_env_file
from app.data.default_sources import default_sources


def main() -> int:
    load_env_file(ROOT / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set - nothing to do (file-mode deployments "
              "pick up new default_sources() automatically).")
        return 0

    from app.db.session import build_session_factory
    from app.repositories.radar_repository import RadarRepository

    session = build_session_factory(database_url)()
    try:
        repository = RadarRepository(session)
        existing_ids = {source.id for source in repository.get_all_sources()}
        missing = [
            source for source in default_sources() if source.id not in existing_ids
        ]
        if not missing:
            print("No new sources to register.")
            return 0
        repository.upsert_sources(missing)
        session.commit()
        print(f"Registered {len(missing)} new source(s): "
              f"{', '.join(s.id for s in missing)}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
