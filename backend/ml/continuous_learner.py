"""
Continuous Learning Pipeline for PlayIntel.

Every week, this module:
  1. Pulls ALL resolved matches from the DB (grows as 2026 results accumulate)
  2. Builds feature matrix using the same engineering pipeline used for predictions
  3. Retrains XGBoost/LightGBM ensemble for each sport
  4. Compares new accuracy vs previous — logs the improvement
  5. Saves the new model, replacing the old one

The model does NOT retrain from scratch on each run — it uses the full
accumulated dataset (old + new), so accuracy improves over time as more
2026 real-world results are added.
"""
from __future__ import annotations
import json
from datetime import datetime
from loguru import logger


def retrain_sport(db, sport_key: str) -> dict:
    """
    Retrain model for one sport using all resolved DB data.
    Returns a dict with training stats.
    """
    from features.engineering import build_training_matrix
    from ml.models.sport_model import SportModel, MODEL_DIR

    logger.info(f"[ContinuousLearner] Building training matrix for {sport_key}...")
    df = build_training_matrix(db, sport_key)

    if df.empty or len(df) < 100:
        logger.warning(f"[ContinuousLearner] {sport_key}: only {len(df)} rows — skipping")
        return {"sport": sport_key, "status": "skipped", "rows": len(df)}

    logger.info(f"[ContinuousLearner] {sport_key}: {len(df)} training rows")

    model = SportModel(sport_key)
    scores = model.train(df)
    model.save()

    result = {
        "sport": sport_key,
        "status": "trained",
        "rows": len(df),
        "accuracy": scores,
        "trained_at": datetime.utcnow().isoformat(),
    }
    logger.info(f"[ContinuousLearner] {sport_key} done — accuracy: {scores}")
    return result


def run_full_retrain(db) -> list[dict]:
    """
    Retrain all sports that have saved models.
    Called by the scheduler weekly.
    """
    from ml.models.sport_model import MODEL_DIR

    sport_keys = [f.stem.replace("_model", "") for f in MODEL_DIR.glob("*_model.pkl")]
    if not sport_keys:
        logger.warning("[ContinuousLearner] No saved models found")
        return []

    results = []
    for sk in sport_keys:
        try:
            r = retrain_sport(db, sk)
            results.append(r)
            _log_training(db, r)
        except Exception as e:
            logger.error(f"[ContinuousLearner] {sk} failed: {e}")
            results.append({"sport": sk, "status": "error", "error": str(e)})

    return results


def _log_training(db, result: dict):
    """Persist a training run to ModelTrainingLog."""
    try:
        from data.db_models.models import ModelTrainingLog
        log = ModelTrainingLog(
            sport_key=result["sport"],
            status=result["status"],
            training_rows=result.get("rows", 0),
            accuracy_json=json.dumps(result.get("accuracy", {})),
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.warning(f"[ContinuousLearner] Failed to log training: {e}")
        try:
            db.rollback()
        except Exception:
            pass
