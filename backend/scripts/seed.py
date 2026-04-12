#!/usr/bin/env python
"""Seed demo data and rebuild ELO ratings."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from data.database import init_db_sync
from data.pipeline import seed_demo_data
from features.elo import rebuild_elo
from data.database import get_sync_session


def main():
    init_db_sync()
    logger.info("Seeding demo data...")
    seed_demo_data()

    logger.info("Rebuilding ELO ratings...")
    with get_sync_session() as db:
        for sport_key in ["football", "basketball", "tennis"]:
            rebuild_elo(db, sport_key)

    logger.info("Done.")


if __name__ == "__main__":
    main()
