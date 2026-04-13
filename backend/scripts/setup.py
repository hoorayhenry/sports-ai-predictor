#!/usr/bin/env python
"""
Production setup script — run once before launching the server.

What it does:
  1. Initialises the database schema
  2. Downloads real football history (football-data.co.uk — 11 leagues × 4 seasons)
  3. Downloads real tennis history (ATP + WTA via Jeff Sackmann GitHub)
  4. Downloads real NBA history (NBA Stats API — 2021-22 through 2024-25)
  5. Fetches current season full schedule from API-Football (requires API_FOOTBALL_KEY)
  6. Fetches live upcoming fixtures from Sportybet + Odds API
  7. Rebuilds ELO ratings for all sports
  8. Trains ML models (football, basketball, tennis)

Usage:
  cd /path/to/backend
  PYTHONPATH=. python scripts/setup.py [--skip-historical] [--skip-train]

Flags:
  --skip-historical   Skip CSV/NBA/ATP download (use if already loaded)
  --skip-train        Skip ML model training
  --skip-live         Skip live fixture fetch
"""
from __future__ import annotations
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger


def main():
    parser = argparse.ArgumentParser(description="Sports AI production setup")
    parser.add_argument("--skip-historical", action="store_true", help="Skip historical CSV/NBA/ATP download")
    parser.add_argument("--skip-train",      action="store_true", help="Skip ML model training")
    parser.add_argument("--skip-live",       action="store_true", help="Skip live fixture fetch")
    parser.add_argument("--skip-season",     action="store_true", help="Skip API-Football full season fetch")
    args = parser.parse_args()

    # ── 1. Init DB ────────────────────────────────────────────────────
    logger.info("━━━ Step 1: Initialising database ━━━")
    from data.database import init_db_sync
    init_db_sync()
    logger.info("Database schema ready.")

    # ── 2. Historical data ────────────────────────────────────────────
    if not args.skip_historical:
        logger.info("━━━ Step 2: Loading historical match data ━━━")
        logger.info("This downloads ~4 seasons of real match results from free public sources.")
        from data.pipeline import run_historical_load
        total = run_historical_load()
        logger.info(f"Historical load complete — {total} new records inserted.")
    else:
        logger.info("━━━ Step 2: Skipped (--skip-historical) ━━━")

    # ── 3. Current season from API-Football ──────────────────────────
    if not args.skip_season:
        logger.info("━━━ Step 3: Fetching full current season from API-Football ━━━")
        from data.pipeline import run_full_season_fetch
        run_full_season_fetch()
    else:
        logger.info("━━━ Step 3: Skipped (--skip-season) ━━━")

    # ── 4. Live upcoming fixtures ─────────────────────────────────────
    if not args.skip_live:
        logger.info("━━━ Step 4: Fetching live upcoming fixtures ━━━")
        from data.pipeline import run_live_fetch
        run_live_fetch()
    else:
        logger.info("━━━ Step 4: Skipped (--skip-live) ━━━")

    # ── 5. Rebuild ELO ───────────────────────────────────────────────
    logger.info("━━━ Step 5: Rebuilding ELO ratings ━━━")
    from data.database import get_sync_session
    from features.elo import rebuild_elo
    with get_sync_session() as db:
        for sport_key in ["football", "basketball", "tennis"]:
            logger.info(f"  ELO → {sport_key}...")
            rebuild_elo(db, sport_key)
    logger.info("ELO ratings rebuilt.")

    # ── 6. Train ML models ────────────────────────────────────────────
    if not args.skip_train:
        logger.info("━━━ Step 6: Training ML models ━━━")
        from ml.models.sport_model import SportModel, MODEL_DIR
        from features.engineering import build_training_matrix

        for sport_key in ["football", "basketball", "tennis"]:
            logger.info(f"  Training model for {sport_key}...")
            with get_sync_session() as db:
                df = build_training_matrix(db, sport_key)

            if df.empty or len(df) < 50:
                logger.warning(f"  Not enough training data for {sport_key} ({len(df)} rows) — skipping")
                continue

            model = SportModel(sport_key)
            model.train(df)
            model.save()
            logger.info(f"  ✓ Model trained for {sport_key} ({len(df)} training rows)")
    else:
        logger.info("━━━ Step 6: Skipped (--skip-train) ━━━")

    # ── 7. Run initial predictions + decisions ────────────────────────
    logger.info("━━━ Step 7: Running initial predictions + AI decisions ━━━")
    from data.db_models.models import Match, Competition, Sport as SportModel2
    from sqlalchemy.orm import joinedload
    from ml.models.sport_model import SportModel, MODEL_DIR
    from features.engineering import build_inference_row
    from betting.value_engine import evaluate_match, save_predictions
    from betting.decision_engine import process_decisions, generate_smart_sets

    with get_sync_session() as db:
        matches = (
            db.query(Match)
            .join(Competition).join(SportModel2)
            .options(
                joinedload(Match.home),
                joinedload(Match.away),
                joinedload(Match.competition).joinedload(Competition.sport),
            )
            .filter(Match.status == "scheduled")
            .all()
        )
        logger.info(f"  Predicting {len(matches)} scheduled matches...")
        for m in matches:
            try:
                sk = m.competition.sport.key if m.competition and m.competition.sport else None
                if not sk:
                    continue
                model_path = MODEL_DIR / f"{sk}_model.pkl"
                if not model_path.exists():
                    continue
                model      = SportModel.load(sk)
                X          = build_inference_row(db, m, sk)
                if X.empty:
                    continue
                pred_probs = model.predict(X)
                vbs        = evaluate_match(db, m.id, pred_probs)
                save_predictions(db, m, pred_probs, vbs)
            except Exception as e:
                logger.debug(f"Prediction error match {m.id}: {e}")

        play_count = process_decisions(db)
        generate_smart_sets(db)
        logger.info(f"  ✓ {play_count} PLAY decisions generated")

    logger.info("")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  Setup complete. You can now start the server:")
    logger.info("  PYTHONPATH=. uvicorn api.main:app --host 0.0.0.0 --port 8000")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


if __name__ == "__main__":
    main()
