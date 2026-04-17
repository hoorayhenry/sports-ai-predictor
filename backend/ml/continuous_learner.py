"""
Continuous Learning Pipeline.

Every week:
  1. Pulls all resolved matches from the DB (2-year rolling window)
  2. Builds feature matrix using the same engineering pipeline
  3. Retrains XGBoost/LightGBM ensemble for each sport
  4. Compares new accuracy vs previous 4-week rolling average (drift detection)
  5. Saves the new model, replacing the old one

Drift detection:
  If a sport's log_loss degrades by more than DRIFT_THRESHOLD vs the rolling
  average of the last 4 training runs, the model is flagged as degraded.
  The system widens the PLAY thresholds for that sport and logs a warning.
  This prevents the engine from issuing confident PLAY decisions when the
  underlying model is no longer reliable.
"""
from __future__ import annotations
import json
from datetime import datetime
from loguru import logger

# Log-loss increase that triggers a drift warning (e.g. 0.05 = 5% worse)
DRIFT_THRESHOLD = 0.05


def retrain_sport(db, sport_key: str) -> dict:
    """
    Retrain model for one sport using the 2-year rolling training window.
    Returns a dict with training stats and drift assessment.
    """
    from features.engineering import build_training_matrix
    from ml.models.sport_model import SportModel

    logger.info(f"[ContinuousLearner] Building training matrix for {sport_key}...")
    df = build_training_matrix(db, sport_key)

    if df.empty or len(df) < 100:
        logger.warning(f"[ContinuousLearner] {sport_key}: only {len(df)} rows — skipping")
        return {"sport": sport_key, "status": "skipped", "rows": len(df)}

    logger.info(f"[ContinuousLearner] {sport_key}: {len(df)} training rows")

    model = SportModel(sport_key)
    scores = model.train(df)
    model.save()

    # ── Drift detection ───────────────────────────────────────────────
    drift_info = _check_drift(db, sport_key, scores)

    result = {
        "sport":      sport_key,
        "status":     "trained",
        "rows":       len(df),
        "accuracy":   scores,
        "drift":      drift_info,
        "trained_at": datetime.utcnow().isoformat(),
    }

    if drift_info.get("degraded"):
        logger.warning(
            f"[ContinuousLearner] {sport_key} DRIFT DETECTED — "
            f"result log_loss {drift_info.get('current_ll'):.4f} vs "
            f"rolling avg {drift_info.get('rolling_avg_ll'):.4f} "
            f"(+{drift_info.get('delta'):.4f}). Thresholds widened."
        )
        _apply_drift_penalty(db, sport_key)
    else:
        _clear_drift_penalty(db, sport_key)

    logger.info(f"[ContinuousLearner] {sport_key} done — accuracy: {scores}")
    return result


def _check_drift(db, sport_key: str, new_scores: dict) -> dict:
    """
    Compare new result log_loss vs rolling average of last 4 training runs.
    Returns a dict with drift assessment.
    """
    from data.db_models.models import ModelTrainingLog

    current_ll = new_scores.get("result")
    if current_ll is None:
        return {"degraded": False, "reason": "no result market scores"}

    # Fetch last 4 training runs for this sport
    try:
        recent_logs = (
            db.query(ModelTrainingLog)
            .filter(
                ModelTrainingLog.sport_key == sport_key,
                ModelTrainingLog.status == "trained",
            )
            .order_by(ModelTrainingLog.trained_at.desc())
            .limit(4)
            .all()
        )
    except Exception:
        return {"degraded": False, "reason": "no training history"}

    if len(recent_logs) < 2:
        return {"degraded": False, "reason": "insufficient history (need 2+ runs)"}

    # Extract result log_loss from each historical run
    past_lls = []
    for log in recent_logs:
        try:
            acc = json.loads(log.accuracy_json) if log.accuracy_json else {}
            ll  = acc.get("result")
            if ll is not None:
                past_lls.append(ll)
        except Exception:
            continue

    if not past_lls:
        return {"degraded": False, "reason": "no historical log_loss data"}

    rolling_avg = sum(past_lls) / len(past_lls)
    delta       = current_ll - rolling_avg  # positive = worse (higher loss)
    degraded    = delta > DRIFT_THRESHOLD

    return {
        "degraded":       degraded,
        "current_ll":     round(current_ll, 4),
        "rolling_avg_ll": round(rolling_avg, 4),
        "delta":          round(delta, 4),
        "history_size":   len(past_lls),
    }


def _apply_drift_penalty(db, sport_key: str):
    """
    When drift is detected, reduce the optimization weight for this sport
    to dampen PLAY decisions until accuracy recovers.
    A negative weight reduces the confidence score, making it harder to PLAY.
    """
    from data.db_models.models import OptimizationWeight

    try:
        row = db.query(OptimizationWeight).filter_by(scope_key=sport_key).first()
        if not row:
            row = OptimizationWeight(scope_key=sport_key, scope_type="sport")
            db.add(row)
        # Apply a -5 penalty — shrinks confidence score by 5 pts for this sport
        row.weight     = max(-10.0, (row.weight or 0.0) - 5.0)
        row.updated_at = datetime.utcnow()
        db.commit()
        logger.info(f"[DriftPenalty] {sport_key}: optimization weight set to {row.weight}")
    except Exception as e:
        logger.warning(f"[DriftPenalty] Failed to apply penalty for {sport_key}: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def _clear_drift_penalty(db, sport_key: str):
    """
    After a clean retrain, nudge the optimization weight back toward neutral
    if it was previously penalised. Gradual recovery (+2 per clean run).
    """
    from data.db_models.models import OptimizationWeight

    try:
        row = db.query(OptimizationWeight).filter_by(scope_key=sport_key).first()
        if row and row.weight < -2.0:
            row.weight     = min(0.0, row.weight + 2.0)
            row.updated_at = datetime.utcnow()
            db.commit()
            logger.info(f"[DriftRecovery] {sport_key}: weight nudged to {row.weight}")
    except Exception as e:
        logger.warning(f"[DriftRecovery] {sport_key}: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def run_full_retrain(db) -> list[dict]:
    """
    Retrain all sports that have saved models.
    Called by the scheduler weekly (Sunday 03:00 UTC).
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

        accuracy = result.get("accuracy", {})
        drift    = result.get("drift", {})

        # Store drift info alongside accuracy
        accuracy_with_drift = {**accuracy, "_drift": drift}

        log = ModelTrainingLog(
            sport_key     = result["sport"],
            status        = result["status"],
            training_rows = result.get("rows", 0),
            accuracy_json = json.dumps(accuracy_with_drift),
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.warning(f"[ContinuousLearner] Failed to log training: {e}")
        try:
            db.rollback()
        except Exception:
            pass
