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
    """
    Fetch real match results from APIs, mark finished, log performance.
    Also backfills xG + shot stats from API-Football for recently finished matches.
    Runs every 2 hours.
    """
    logger.info("[SCHEDULER] Resolving finished matches + fetching real results...")
    try:
        from data.database import get_sync_session
        from betting.decision_engine import resolve_finished_matches

        with get_sync_session() as db:
            n = resolve_finished_matches(db)   # internally calls results_fetcher
        logger.info(f"[SCHEDULER] Resolved {n} matches")
    except Exception as e:
        logger.error(f"[SCHEDULER] Resolve job failed: {e}")

    # Backfill xG data from API-Football for enriched training features
    api_key = settings.api_football_key
    if api_key:
        try:
            from data.database import get_sync_session
            from data.loaders.xg_backfill import backfill_xg

            with get_sync_session() as db:
                enriched = backfill_xg(db, api_key, max_matches=40)
            if enriched > 0:
                logger.info(f"[SCHEDULER] xG backfill: {enriched} matches enriched")
        except Exception as e:
            logger.warning(f"[SCHEDULER] xG backfill error: {e}")


def job_fetch_intelligence():
    """
    Scrape news + extract intelligence signals for upcoming matches.
    Runs every 30 minutes so injury/lineup news is picked up quickly.
    Only processes matches without fresh signals (last 6 hours).
    """
    logger.info("[SCHEDULER] Fetching intelligence signals...")
    try:
        from data.database import get_sync_session
        from intelligence.signals import run_intelligence_for_upcoming

        api_key = settings.gemini_api_key
        if not api_key:
            logger.debug("[SCHEDULER] GEMINI_API_KEY not set — intelligence job skipped")
            return

        with get_sync_session() as db:
            n = run_intelligence_for_upcoming(db, api_key, hours_ahead=48)
        logger.info(f"[SCHEDULER] Intelligence: {n} new signals saved")
    except Exception as e:
        logger.error(f"[SCHEDULER] Intelligence job failed: {e}")


def job_retrain_models():
    """
    Weekly continuous learning: retrain all sport models on accumulated DB data.
    As 2026 match results fill in, accuracy steadily improves.
    Runs Sunday 03:00 UTC (low traffic).
    """
    logger.info("[SCHEDULER] Starting weekly model retraining...")
    try:
        from data.database import get_sync_session
        from ml.continuous_learner import run_full_retrain

        with get_sync_session() as db:
            results = run_full_retrain(db)

        for r in results:
            logger.info(
                f"[SCHEDULER] Retrain {r['sport']}: {r['status']} "
                f"({r.get('rows', 0)} rows, accuracy={r.get('accuracy', {})})"
            )
    except Exception as e:
        logger.error(f"[SCHEDULER] Retrain job failed: {e}")


def job_fetch_news():
    """
    Fetch latest football news from RSS feeds, rewrite with Gemini, save to DB.
    Runs every 6 hours.
    """
    logger.info("[SCHEDULER] Fetching and rewriting news articles...")
    try:
        from data.database import get_sync_session
        from intelligence.news_writer import run_news_pipeline_sync

        api_key = settings.gemini_api_key
        if not api_key:
            logger.debug("[SCHEDULER] GEMINI_API_KEY not set — news job skipped")
            return

        with get_sync_session() as db:
            saved = run_news_pipeline_sync(db, api_key, hours=8, max_articles=15)
        logger.info(f"[SCHEDULER] News: {saved} articles saved")
    except Exception as e:
        logger.error(f"[SCHEDULER] News job failed: {e}")


def job_live_scores():
    """
    Fetch live match scores from ESPN (no auth) and update the DB.
    Runs every 60 seconds — ESPN updates ~every 30s, so this stays fresh.
    Falls back to API-Football if ESPN returns nothing.
    """
    logger.info("[SCHEDULER] Updating live scores via ESPN...")
    try:
        from data.database import get_sync_session
        from data.live_scores import update_live_scores

        # Pass api_key as fallback only — ESPN needs no key
        api_key = settings.api_football_key

        with get_sync_session() as db:
            n = update_live_scores(db, api_key)
        logger.info(f"[SCHEDULER] Live scores: {n} matches updated")

        # Notify SSE connections immediately — don't wait for their 60s heartbeat
        if n > 0:
            from data.live_bus import notify
            notify(n)
    except Exception as e:
        logger.error(f"[SCHEDULER] Live scores job failed: {e}")


def job_retry_drafts():
    """
    Retry AI rewriting of draft articles that failed on first pass.
    Runs every 30 minutes — promotes drafts to 'published' as Gemini quota allows.
    Draft articles are raw scraped text held back from the public feed.
    """
    logger.info("[SCHEDULER] Retrying draft article rewrites...")
    try:
        from data.database import get_sync_session
        from intelligence.news_writer import retry_draft_articles

        api_key = settings.gemini_api_key
        if not api_key:
            logger.debug("[SCHEDULER] GEMINI_API_KEY not set — draft retry skipped")
            return

        with get_sync_session() as db:
            promoted = retry_draft_articles(db, api_key, max_articles=10)
        logger.info(f"[SCHEDULER] Draft retry: {promoted} articles promoted to published")
    except Exception as e:
        logger.error(f"[SCHEDULER] Draft retry job failed: {e}")


def job_fetch_odds():
    """Fetch live odds from Sportybet + Odds API."""
    logger.info("[SCHEDULER] Fetching live odds...")
    try:
        from data.pipeline import run_live_fetch
        run_live_fetch()
    except Exception as e:
        logger.error(f"[SCHEDULER] Odds fetch failed: {e}")


def job_fetch_lineups():
    """
    Fetch confirmed lineups + injury reports from API-Football for
    matches kicking off in the next 24 hours that are marked PLAY.
    Converts them to IntelligenceSignal rows so the decision engine
    can factor in unavailable players before the daily email.

    Runs hourly — lineups are published ~1 hr before kickoff.
    Only consumes quota for PLAY-labelled matches (free tier: 100 req/day).
    """
    api_key = settings.api_football_key
    if not api_key:
        logger.debug("[SCHEDULER] API_FOOTBALL_KEY not set — lineup job skipped")
        return

    logger.info("[SCHEDULER] Fetching pre-match lineups + injuries via API-Football...")
    try:
        from data.database import get_sync_session
        from data.db_models.models import Match, MatchDecision, Competition, Participant, IntelligenceSignal
        from data.loaders.api_football import build_injury_signals
        from sqlalchemy.orm import joinedload

        with get_sync_session() as db:
            cutoff = datetime.utcnow() + timedelta(hours=24)
            rows = (
                db.query(Match)
                .join(MatchDecision, Match.id == MatchDecision.match_id)
                .join(Competition)
                .options(
                    joinedload(Match.home),
                    joinedload(Match.away),
                    joinedload(Match.competition),
                )
                .filter(
                    Match.status == "scheduled",
                    Match.match_date <= cutoff,
                    Match.match_date >= datetime.utcnow(),
                    MatchDecision.ai_decision == "PLAY",
                )
                .all()
            )

            new_signals = 0
            for m in rows:
                for participant, is_home in [(m.home, True), (m.away, False)]:
                    if not participant:
                        continue
                    # Use participant external_id to extract API-Football team ID
                    # Format from our ingest: "football_team_name" — API-Football ID
                    # requires a separate mapping table; for now we skip if no api_id stored
                    api_team_id = getattr(participant, "api_football_id", None)
                    if not api_team_id:
                        continue

                    signals = build_injury_signals(
                        api_key,
                        team_id=api_team_id,
                        team_name=participant.name,
                    )
                    for sig in signals:
                        # Deduplicate: skip if same player signal already exists for this match
                        existing = db.query(IntelligenceSignal).filter_by(
                            match_id=m.id,
                            team_id=participant.id,
                            entity_name=sig["entity_name"],
                            signal_type=sig["signal_type"],
                        ).first()
                        if not existing:
                            db.add(IntelligenceSignal(
                                match_id     = m.id,
                                team_id      = participant.id,
                                team_name    = sig["team_name"],
                                signal_type  = sig["signal_type"],
                                entity_name  = sig["entity_name"],
                                impact_score = sig["impact_score"],
                                confidence   = sig["confidence"],
                                source_type  = sig["source_type"],
                                raw_text     = sig["raw_text"],
                            ))
                            new_signals += 1

            db.commit()
        logger.info(f"[SCHEDULER] Lineups job: {new_signals} new injury signals saved")
    except Exception as e:
        logger.error(f"[SCHEDULER] Lineups job failed: {e}")


# ── Scheduler lifecycle ───────────────────────────────────────────────

def start_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")

    # Live scores every 60 seconds — ESPN source, no quota concerns
    _scheduler.add_job(
        job_live_scores,
        IntervalTrigger(seconds=60),
        id="live_scores",
        replace_existing=True,
        misfire_grace_time=30,
    )

    # Intelligence signals every 30 minutes (real-time news/injury tracking)
    _scheduler.add_job(
        job_fetch_intelligence,
        IntervalTrigger(minutes=30),
        id="fetch_intelligence",
        replace_existing=True,
        misfire_grace_time=300,
    )

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

    # News pipeline every 3 hours — fresh articles throughout the day
    _scheduler.add_job(
        job_fetch_news,
        IntervalTrigger(hours=3),
        id="fetch_news",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Draft retry every 30 minutes — promotes unwritten articles to published as Gemini quota frees up
    _scheduler.add_job(
        job_retry_drafts,
        IntervalTrigger(minutes=30),
        id="retry_drafts",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Pre-match lineups + injuries every hour (API-Football, free tier)
    _scheduler.add_job(
        job_fetch_lineups,
        IntervalTrigger(hours=1),
        id="fetch_lineups",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Weekly model retraining — Sunday 03:00 UTC
    _scheduler.add_job(
        job_retrain_models,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="retrain_models",
        replace_existing=True,
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
