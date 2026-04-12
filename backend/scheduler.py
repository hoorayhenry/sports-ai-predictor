"""
APScheduler daily automation jobs.

Jobs:
  • Every 6 hours  — refresh odds + run predictions
  • Daily at 08:00 — run decision engine + generate smart sets + send email
  • Every 2 hours  — resolve finished matches + update perf logs
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from loguru import logger

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import get_settings

settings = get_settings()
_scheduler: BackgroundScheduler | None = None


# ── Helper: build picks + sets dicts for email ────────────────────────

def _get_daily_picks_dicts(db) -> list[dict]:
    from data.db_models.models import Match, MatchDecision, Prediction, Competition, Sport
    from sqlalchemy.orm import joinedload

    cutoff = datetime.utcnow() + timedelta(days=7)

    rows = (
        db.query(Match)
        .join(MatchDecision, Match.id == MatchDecision.match_id)
        .join(Prediction, Match.id == Prediction.match_id)
        .join(Competition)
        .join(Sport)
        .options(
            joinedload(Match.home),
            joinedload(Match.away),
            joinedload(Match.competition).joinedload(Competition.sport),
            joinedload(Match.predictions),
        )
        .filter(
            Match.status == "scheduled",
            Match.match_date >= datetime.utcnow(),
            Match.match_date <= cutoff,
            MatchDecision.ai_decision == "PLAY",
        )
        .order_by(MatchDecision.confidence_score.desc())
        .limit(10)
        .all()
    )

    result = []
    for m in rows:
        md   = db.query(MatchDecision).filter_by(match_id=m.id).first()
        pred = m.predictions[0] if m.predictions else None
        if not md:
            continue
        result.append({
            "match_id":          m.id,
            "home_team":         m.home.name if m.home else "TBD",
            "away_team":         m.away.name if m.away else "TBD",
            "competition":       m.competition.name if m.competition else "",
            "sport_icon":        m.competition.sport.icon if m.competition and m.competition.sport else "🏆",
            "match_date":        m.match_date.isoformat(),
            "ai_decision":       md.ai_decision,
            "confidence_score":  md.confidence_score,
            "prob_tag":          md.prob_tag,
            "predicted_outcome": md.predicted_outcome,
            "top_prob":          md.top_prob,
            "home_win_prob":     pred.home_win_prob if pred else None,
            "draw_prob":         pred.draw_prob if pred else None,
            "away_win_prob":     pred.away_win_prob if pred else None,
        })
    return result


def _get_smart_sets_dicts(db) -> list[dict]:
    from data.db_models.models import SmartSet

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sets  = (
        db.query(SmartSet)
        .filter(SmartSet.generated_date >= today)
        .order_by(SmartSet.set_number)
        .all()
    )
    result = []
    for ss in sets:
        matches = json.loads(ss.matches_json) if ss.matches_json else []
        result.append({
            "set_number":          ss.set_number,
            "match_count":         ss.match_count,
            "overall_confidence":  ss.overall_confidence,
            "combined_probability": ss.combined_probability,
            "risk_level":          ss.risk_level,
            "matches":             matches,
        })
    return result


# ── Individual job functions ──────────────────────────────────────────

def job_run_predictions():
    """Run ML predictions for all upcoming scheduled matches."""
    logger.info("[SCHEDULER] Running predictions for upcoming matches...")
    try:
        from data.database import get_sync_session
        from data.db_models.models import Match, Competition, Sport
        from sqlalchemy.orm import joinedload
        from ml.models.sport_model import SportModel, MODEL_DIR
        from features.engineering import build_inference_row
        from betting.value_engine import evaluate_match, save_predictions

        with get_sync_session() as db:
            matches = (
                db.query(Match)
                .join(Competition).join(Sport)
                .options(
                    joinedload(Match.home),
                    joinedload(Match.away),
                    joinedload(Match.competition).joinedload(Competition.sport),
                )
                .filter(Match.status == "scheduled")
                .all()
            )
            for m in matches:
                try:
                    sk = m.competition.sport.key if m.competition and m.competition.sport else None
                    if not sk:
                        continue
                    model_path = MODEL_DIR / f"{sk}_model.pkl"
                    if not model_path.exists():
                        continue
                    model = SportModel.load(sk)
                    X     = build_inference_row(db, m, sk)
                    if X.empty:
                        continue
                    pred_probs = model.predict(X)
                    vbs        = evaluate_match(db, m.id, pred_probs)
                    save_predictions(db, m, pred_probs, vbs)
                except Exception as e:
                    logger.debug(f"Prediction job error match {m.id}: {e}")
        logger.info("[SCHEDULER] Predictions complete")
    except Exception as e:
        logger.error(f"[SCHEDULER] Predictions job failed: {e}")


def job_daily_decisions():
    """Run decision engine + smart sets + send email."""
    logger.info("[SCHEDULER] Running daily decision job...")
    try:
        from data.database import get_sync_session
        from betting.decision_engine import process_decisions, generate_smart_sets
        from mailer.daily_email import send_daily_email

        with get_sync_session() as db:
            play_count = process_decisions(db)
            sets       = generate_smart_sets(db)
            picks      = _get_daily_picks_dicts(db)
            sets_data  = _get_smart_sets_dicts(db)

        send_daily_email(picks, sets_data)
        logger.info(f"[SCHEDULER] Daily job done: {play_count} PLAY, {len(sets)} sets generated")
    except Exception as e:
        logger.error(f"[SCHEDULER] Daily decisions job failed: {e}")


def job_resolve_matches():
    """Check finished matches and log performance."""
    logger.info("[SCHEDULER] Resolving finished matches...")
    try:
        from data.database import get_sync_session
        from betting.decision_engine import resolve_finished_matches

        with get_sync_session() as db:
            n = resolve_finished_matches(db)
        logger.info(f"[SCHEDULER] Resolved {n} matches")
    except Exception as e:
        logger.error(f"[SCHEDULER] Resolve job failed: {e}")


def job_fetch_odds():
    """Fetch live odds from Sportybet + Odds API."""
    logger.info("[SCHEDULER] Fetching live odds...")
    try:
        from data.pipeline import run_live_fetch
        run_live_fetch()
    except Exception as e:
        logger.error(f"[SCHEDULER] Odds fetch failed: {e}")


# ── Scheduler lifecycle ───────────────────────────────────────────────

def start_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")

    # Fetch odds every 6 hours
    _scheduler.add_job(
        job_fetch_odds,
        IntervalTrigger(hours=6),
        id="fetch_odds",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Predictions every 3 hours (so new fixtures get predictions quickly)
    _scheduler.add_job(
        job_run_predictions,
        IntervalTrigger(hours=3),
        id="run_predictions",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Daily decision + email at configured UTC hour
    _scheduler.add_job(
        job_daily_decisions,
        CronTrigger(hour=settings.daily_email_hour, minute=0),
        id="daily_decisions",
        replace_existing=True,
    )

    # Resolve finished matches every 2 hours
    _scheduler.add_job(
        job_resolve_matches,
        IntervalTrigger(hours=2),
        id="resolve_matches",
        replace_existing=True,
        misfire_grace_time=300,
    )

    _scheduler.start()
    logger.info(
        f"Scheduler started — daily email at {settings.daily_email_hour:02d}:00 UTC"
    )


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
