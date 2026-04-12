#!/usr/bin/env python
"""Train ML models for all sports."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from data.database import get_sync_session
from features.engineering import build_training_matrix
from ml.models.sport_model import SportModel

SPORTS = ["football", "basketball", "tennis"]


def main():
    for sport_key in SPORTS:
        logger.info(f"Building training matrix for {sport_key}...")
        with get_sync_session() as db:
            df = build_training_matrix(db, sport_key)

        if df.empty:
            logger.warning(f"No data for {sport_key} — skipping.")
            continue

        logger.info(f"{sport_key}: {len(df)} training samples, columns: {list(df.columns)}")
        model = SportModel(sport_key)
        scores = model.train(df)
        model.save()
        logger.info(f"{sport_key} training done. Scores: {scores}")

    logger.info("All models trained.")


if __name__ == "__main__":
    main()
