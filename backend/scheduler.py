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
    """
    Run ML predictions for all upcoming scheduled matches.

    Batches by sport to avoid reloading the model and rebuilding the historical
    context DataFrame for every single match (was O(N*M) DB queries; now O(S)
    where S = number of sports with a trained model).
    """
    logger.info("[SCHEDULER] Running predictions for upcoming matches...")
    try:
        import pandas as pd
        from collections import defaultdict
        from data.database import get_sync_session
        from data.db_models.models import Match, Competition, Sport
        from sqlalchemy.orm import joinedload
        from ml.models.sport_model import SportModel, MODEL_DIR
        from features.engineering import (
            build_row, COMMON_FEATURES, _build_team_index,
            _parse_extra,
        )
        from betting.value_engine import evaluate_match, save_predictions

        with get_sync_session() as db:
            # Load all upcoming matches grouped by sport
            all_upcoming = (
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

            # Group by sport key
            by_sport: dict = defaultdict(list)
            for m in all_upcoming:
                sk = m.competition.sport.key if m.competition and m.competition.sport else None
                if sk:
                    by_sport[sk].append(m)

            total_predicted = 0
            for sk, sport_matches in by_sport.items():
                model_path = MODEL_DIR / f"{sk}_model.pkl"
                if not model_path.exists():
                    continue

                try:
                    model = SportModel.load(sk)
                    sport = db.query(Sport).filter_by(key=sk).first()
                    if not sport:
                        continue

                    # Load ALL finished matches for this sport ONCE
                    hist_matches = (
                        db.query(Match)
                        .join(Competition)
                        .filter(Competition.sport_id == sport.id, Match.result.isnot(None))
                        .options(joinedload(Match.home), joinedload(Match.away))
                        .order_by(Match.match_date)
                        .all()
                    )

                    def _mrow(m: Match) -> dict:
                        row = {
                            "id": m.id, "home_id": m.home_id, "away_id": m.away_id,
                            "match_date": pd.to_datetime(m.match_date),
                            "home_score": m.home_score or 0,
                            "away_score": m.away_score or 0,
                            "result": m.result,
                        }
                        ex = _parse_extra(m.extra_data)
                        for k, col in [("hs","home_shots"),("as_","away_shots"),
                                       ("hst","home_sot"),("ast","away_sot"),
                                       ("hy","home_yellow"),("ay","away_yellow"),
                                       ("hr","home_red"),("ar","away_red"),
                                       ("ref","referee"),
                                       ("home_xg","home_xg"),("away_xg","away_xg")]:
                            row[col] = ex.get(k)
                        return row

                    df = pd.DataFrame([_mrow(m) for m in hist_matches]) if hist_matches else pd.DataFrame()
                    if df.empty:
                        continue

                    # Build team index once for this sport
                    team_idx, h2h_idx = _build_team_index(df)
                    import numpy as np
                    lg_avg = float(df[df.result.notna()]["home_score"].mean() or 1.3)

                    for m in sport_matches:
                        try:
                            row = build_row(db, m, df, sk,
                                            team_idx=team_idx, h2h_idx=h2h_idx,
                                            lg_avg=lg_avg)
                            X = pd.DataFrame([row])[COMMON_FEATURES]
                            if X.empty:
                                continue
                            pred_probs = model.predict(X)
                            vbs        = evaluate_match(db, m.id, pred_probs)
                            save_predictions(db, m, pred_probs, vbs)
                            total_predicted += 1
                        except Exception as e:
                            logger.debug(f"Prediction error match {m.id} ({sk}): {e}")

                    logger.info(f"[SCHEDULER] {sk}: predicted {len(sport_matches)} matches")

                except Exception as e:
                    logger.error(f"[SCHEDULER] Prediction batch failed for {sk}: {e}")

        logger.info(f"[SCHEDULER] Predictions complete — {total_predicted} matches updated")
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


def job_ingest_multi_sport_history():
    """
    Incremental multi-sport historical data ingestion via Sofascore + ESPN.
    Fetches all sports (football, basketball, tennis, baseball, NFL, NHL, cricket,
    rugby, handball, volleyball) for dates not yet in the DB.
    Runs daily at 02:00 UTC — off-peak, before the weekly retrain.
    More data in DB = better ML predictions across all sports.
    """
    logger.info("[SCHEDULER] Starting multi-sport historical ingestion...")
    try:
        from data.database import get_sync_session
        from data.loaders.multi_sport_ingest import (
            run_full_multi_sport_ingest, run_espn_historical_ingest
        )

        with get_sync_session() as db:
            # Sofascore: fetch last 7 days of new data (incremental)
            ss_results = run_full_multi_sport_ingest(db, days_back=7)

        with get_sync_session() as db:
            # ESPN: supplement US sports with last 3 seasons
            from datetime import datetime as _dt
            current_year = _dt.utcnow().year
            espn_results = run_espn_historical_ingest(
                db, seasons=list(range(current_year - 2, current_year + 1))
            )

        total = sum(ss_results.values()) + sum(espn_results.values())
        logger.info(
            f"[SCHEDULER] Multi-sport ingest complete: {total} new matches. "
            f"Breakdown: {ss_results}"
        )
    except Exception as e:
        logger.error(f"[SCHEDULER] Multi-sport ingest failed: {e}")


def job_browser_ingest_sofascore():
    """
    Daily incremental ingestion for sports that Sofascore blocks via httpx.
    Uses Playwright (headless Chrome) to bypass TLS fingerprint detection.

    Sports: cricket, rugby, handball, volleyball, tennis
    Fetches the last 3 days so any catch-up after downtime is handled.
    Runs at 02:30 UTC, after the standard multi-sport ingest.
    """
    logger.info("[SCHEDULER] Starting browser-based Sofascore ingestion...")
    try:
        from data.database import get_sync_session
        from data.loaders.sofascore_browser import browser_ingest_sport, SofascoreBrowserFetcher, BROWSER_ONLY_SPORTS
        from data.loaders.multi_sport_ingest import SPORTS_CONFIG
        from datetime import date, timedelta

        # Fetch last 3 days (catches up if yesterday's job missed)
        end   = date.today() - timedelta(days=1)
        start = end - timedelta(days=2)

        slug_map = {sk: slug for slug, sk, *_ in SPORTS_CONFIG}
        results: dict[str, int] = {}

        with SofascoreBrowserFetcher() as fetcher:
            for sport_key in BROWSER_ONLY_SPORTS:
                ss_slug = slug_map.get(sport_key)
                if not ss_slug:
                    continue
                try:
                    with get_sync_session() as db:
                        n = browser_ingest_sport(db, ss_slug, sport_key, start, end, fetcher=fetcher)
                    results[sport_key] = n
                except Exception as e:
                    logger.warning(f"[SCHEDULER] Browser ingest {sport_key} failed: {e}")
                    results[sport_key] = 0

        total = sum(results.values())
        logger.info(f"[SCHEDULER] Browser ingest done: {total} new matches — {results}")
    except Exception as e:
        logger.error(f"[SCHEDULER] Browser ingest job failed: {e}")


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
    Fetch live match scores from Sofascore (primary) + ESPN fallback and update the DB.
    Adaptive rate: reschedules itself at 30s when matches are live (Sofascore cadence),
    5 min when idle. SSE bus pushes changes to connected clients immediately.
    """
    logger.info("[SCHEDULER] Updating live scores via ESPN...")
    live_count = 0
    try:
        from data.database import get_sync_session
        from data.live_scores import update_live_scores, fetch_live_fixtures_espn

        api_key = settings.api_football_key

        with get_sync_session() as db:
            live_count = update_live_scores(db, api_key)
        logger.info(f"[SCHEDULER] Live scores: {live_count} matches updated")

        if live_count > 0:
            from data.live_bus import notify
            notify(live_count)
    except Exception as e:
        logger.error(f"[SCHEDULER] Live scores job failed: {e}")
    finally:
        # Adaptive interval: poll every 20s during live matches (Sofascore updates every ~20s),
        # every 5 min when no live matches to avoid unnecessary polling.
        global _scheduler
        if _scheduler and _scheduler.running:
            next_interval = 20 if live_count > 0 else 300
            try:
                _scheduler.reschedule_job(
                    "live_scores",
                    trigger=IntervalTrigger(seconds=next_interval),
                )
            except Exception:
                pass


def job_refresh_clubs_data():
    """
    Refresh standings and fixtures for all leagues in the Clubs tab.
    Scheduler runs this every 5 min so routes always read from DB — no per-user ESPN calls.
    Runs immediately on startup (next_run_time=now) to warm the DB before first user hit.
    """
    logger.info("[SCHEDULER] Refreshing Clubs standings + fixtures...")
    try:
        from api.routes.standings import (
            LEAGUES, CURRENT_SEASON,
            _fetch_espn, _fetch_league_fixtures, _db_put_sync,
        )

        refreshed = 0
        for slug, name, _country, _flag in LEAGUES:
            # Standings
            try:
                result = _fetch_espn(slug, CURRENT_SEASON)
                if result:
                    _db_put_sync(slug, CURRENT_SEASON, "standings", result)
                    refreshed += 1
            except Exception as e:
                logger.debug(f"[SCHEDULER] Standings refresh failed {slug}: {e}")

            # Fixtures (4 days back, 14 ahead)
            try:
                result = _fetch_league_fixtures(slug, CURRENT_SEASON)
                if result:
                    _db_put_sync(slug, CURRENT_SEASON, "fixtures", result)
                    refreshed += 1
            except Exception as e:
                logger.debug(f"[SCHEDULER] Fixtures refresh failed {slug}: {e}")

        logger.info(f"[SCHEDULER] Clubs data: {refreshed} datasets refreshed")
    except Exception as e:
        logger.error(f"[SCHEDULER] Clubs data refresh failed: {e}")


def job_refresh_clubs_news_leaders():
    """
    Refresh league news and top scorers for all leagues.
    Runs every 30 min — less time-sensitive than standings/fixtures.
    """
    logger.info("[SCHEDULER] Refreshing Clubs news + leaders...")
    try:
        from api.routes.standings import (
            LEAGUES, CURRENT_SEASON, _NEWS_SEASON,
            _fetch_league_news, _fetch_league_leaders, _db_put_sync,
        )

        for slug, _, _, _ in LEAGUES:
            try:
                articles = _fetch_league_news(slug)
                _db_put_sync(slug, _NEWS_SEASON, "news", {"articles": articles})
            except Exception as e:
                logger.debug(f"[SCHEDULER] News refresh failed {slug}: {e}")

            try:
                leaders = _fetch_league_leaders(slug, CURRENT_SEASON)
                _db_put_sync(slug, CURRENT_SEASON, "leaders", {"categories": leaders})
            except Exception as e:
                logger.debug(f"[SCHEDULER] Leaders refresh failed {slug}: {e}")

        logger.info("[SCHEDULER] Clubs news + leaders refreshed")
    except Exception as e:
        logger.error(f"[SCHEDULER] Clubs news/leaders refresh failed: {e}")


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


def _job_generate_smart_sets_for_window(job_name: str, days_ahead_start: int, days_ahead_end: int):
    """
    Core helper: generate smart sets for a WAT-aligned match window.

    WAT = UTC+1.  Window day boundaries are computed in WAT then converted to UTC.
    'days_ahead_start' / 'days_ahead_end' are calendar days from *today in WAT*.

    E.g. Sunday job fired at 17:00 WAT:
      days_ahead_start=1 (Monday), days_ahead_end=3 (Wednesday)
    """
    logger.info(f"[SCHEDULER] Generating smart sets — {job_name}...")
    try:
        from data.database import get_sync_session
        from betting.decision_engine import process_decisions, generate_smart_sets

        # Compute window in WAT then convert to UTC
        now_utc = datetime.utcnow()
        now_wat_naive = now_utc + timedelta(hours=1)          # WAT = UTC+1 (no DST)

        # Start of the target day in WAT (midnight)
        start_wat = (now_wat_naive + timedelta(days=days_ahead_start)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # End of the last target day in WAT (23:59:59)
        end_wat = (now_wat_naive + timedelta(days=days_ahead_end)).replace(
            hour=23, minute=59, second=59, microsecond=0
        )
        # Convert back to UTC
        window_start_utc = start_wat - timedelta(hours=1)
        window_end_utc   = end_wat   - timedelta(hours=1)

        logger.info(
            f"[SCHEDULER] {job_name} window: "
            f"{window_start_utc.strftime('%a %b %d %H:%M')} – "
            f"{window_end_utc.strftime('%a %b %d %H:%M')} UTC"
        )

        with get_sync_session() as db:
            # Re-run decisions so any new fixtures in this window are evaluated
            process_decisions(db)
            sets = generate_smart_sets(db, window_start_utc, window_end_utc)

        logger.info(f"[SCHEDULER] {job_name}: {len(sets)} sets generated")
    except Exception as e:
        logger.error(f"[SCHEDULER] {job_name} failed: {e}")


def job_smart_sets_mon_wed():
    """Sunday 16:00 UTC (17:00 WAT) → picks for Monday–Wednesday."""
    _job_generate_smart_sets_for_window("Mon–Wed picks", days_ahead_start=1, days_ahead_end=3)


def job_smart_sets_thu_fri():
    """Wednesday 16:00 UTC (17:00 WAT) → picks for Thursday–Friday."""
    _job_generate_smart_sets_for_window("Thu–Fri picks", days_ahead_start=1, days_ahead_end=2)


def job_smart_sets_sat_sun():
    """Friday 16:00 UTC (17:00 WAT) → picks for Saturday–Sunday."""
    _job_generate_smart_sets_for_window("Sat–Sun picks", days_ahead_start=1, days_ahead_end=2)


def job_history_backfill():
    """
    10-year historical data backfill for all sports.
    Runs ONCE on startup (if DB is thin) and then weekly to catch any gaps.
    Purpose: user experience (historical records, H2H depth for features).
    Training uses only the last 2 years — see build_training_matrix().

    This is a long-running job (hours for a full 10-year fetch).
    It is safe to interrupt: checkpoint file resumes where it left off.
    """
    logger.info("[SCHEDULER] Checking if history backfill is needed...")
    try:
        from data.database import get_sync_session
        from data.loaders.history_backfill import needs_backfill, run_backfill

        with get_sync_session() as db:
            if not needs_backfill(db, years_back=10):
                logger.info("[SCHEDULER] Backfill not needed — DB has sufficient history")
                return

        logger.info("[SCHEDULER] Starting 10-year history backfill in background...")
        with get_sync_session() as db:
            results = run_backfill(db, years_back=10)
        logger.info(f"[SCHEDULER] Backfill complete: {results}")
    except Exception as e:
        logger.error(f"[SCHEDULER] History backfill failed: {e}")


def job_fetch_player_stats():
    """
    Fetch NBA and NFL top-player stats from ESPN and cache in DB.
    Runs daily at 03:30 UTC — after the historical ingest so the DB is warm.
    One ESPN call per league, no API key required.
    """
    logger.info("[SCHEDULER] Fetching NBA/NFL player stats...")
    try:
        from data.database import get_sync_session
        from data.loaders.player_stats import refresh_player_stats_cache

        with get_sync_session() as db:
            results = refresh_player_stats_cache(db)
        logger.info(f"[SCHEDULER] Player stats: {results}")
    except Exception as e:
        logger.error(f"[SCHEDULER] Player stats job failed: {e}")


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

    # Live scores — adaptive: 20s when matches are live (aligned with Sofascore's ~20s update cadence),
    # 5 min when no live matches. SSE pushes score changes to clients immediately.
    _scheduler.add_job(
        job_live_scores,
        IntervalTrigger(seconds=20),
        id="live_scores",
        replace_existing=True,
        misfire_grace_time=10,
        next_run_time=datetime.utcnow(),
    )

    # Clubs standings + fixtures — every 5 min, warm DB immediately on startup
    _scheduler.add_job(
        job_refresh_clubs_data,
        IntervalTrigger(minutes=5),
        id="refresh_clubs_data",
        replace_existing=True,
        misfire_grace_time=120,
        next_run_time=datetime.utcnow(),   # fire immediately so first user hits warm DB
    )

    # Clubs news + top scorers — every 30 min, warm DB immediately on startup
    _scheduler.add_job(
        job_refresh_clubs_news_leaders,
        IntervalTrigger(minutes=30),
        id="refresh_clubs_news_leaders",
        replace_existing=True,
        misfire_grace_time=300,
        next_run_time=datetime.utcnow(),
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

    # ── Rolling smart set windows (17:00 WAT = 16:00 UTC) ──────────────────
    # Sunday  → Mon–Wed picks
    _scheduler.add_job(
        job_smart_sets_mon_wed,
        CronTrigger(day_of_week="sun", hour=16, minute=0),
        id="smart_sets_mon_wed",
        replace_existing=True,
    )
    # Wednesday → Thu–Fri picks
    _scheduler.add_job(
        job_smart_sets_thu_fri,
        CronTrigger(day_of_week="wed", hour=16, minute=0),
        id="smart_sets_thu_fri",
        replace_existing=True,
    )
    # Friday → Sat–Sun picks
    _scheduler.add_job(
        job_smart_sets_sat_sun,
        CronTrigger(day_of_week="fri", hour=16, minute=0),
        id="smart_sets_sat_sun",
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

    # Multi-sport historical data ingestion — daily at 02:00 UTC
    # Feeds the ML model with fresh data from Sofascore + ESPN across all sports
    _scheduler.add_job(
        job_ingest_multi_sport_history,
        CronTrigger(hour=2, minute=0),
        id="ingest_multi_sport",
        replace_existing=True,
    )

    # Browser-based Sofascore ingestion — daily at 02:30 UTC
    # Fetches cricket, rugby, handball, volleyball, tennis using Playwright
    # (httpx gets 403 for these; real browser fingerprint passes bot detection)
    _scheduler.add_job(
        job_browser_ingest_sofascore,
        CronTrigger(hour=2, minute=30),
        id="browser_ingest_sofascore",
        replace_existing=True,
    )

    # NBA + NFL player stats — daily at 03:30 UTC (after historical ingest)
    _scheduler.add_job(
        job_fetch_player_stats,
        CronTrigger(hour=3, minute=30),
        id="fetch_player_stats",
        replace_existing=True,
        next_run_time=datetime.utcnow(),   # warm cache immediately on startup
    )

    # 10-year history backfill — runs on startup if DB is thin, then weekly
    # Long-running job (hours); checkpoint makes it safe to interrupt/resume
    _scheduler.add_job(
        job_history_backfill,
        CronTrigger(day_of_week="mon", hour=1, minute=0),
        id="history_backfill",
        replace_existing=True,
        next_run_time=datetime.utcnow(),   # check immediately on startup
    )

    # Weekly model retraining — Sunday 03:00 UTC (after daily ingest finishes)
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
