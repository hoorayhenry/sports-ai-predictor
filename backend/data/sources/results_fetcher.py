"""
Real match result fetcher — polls multiple sources to update finished matches.

Sources (priority order):
  1. The Odds API  — /scores endpoint (requires ODDS_API_KEY)
  2. API-Football  — fixture results (requires API_FOOTBALL_KEY)

Called by:
  - scheduler.job_resolve_matches() every 2 hours
  - betting.decision_engine.resolve_finished_matches()

Updates Match.status, Match.home_score, Match.away_score, Match.result
for any match that has finished since last check.
"""
from __future__ import annotations
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy.orm import Session
from config.settings import get_settings

settings = get_settings()

# Odds API sport keys that have a scores endpoint
ODDS_API_SCOREABLE_SPORTS = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_nigeria_npfl",
    "soccer_brazil_campeonato",
    "soccer_argentina_primera_division",
    "soccer_mls",
    "basketball_nba",
    "tennis_atp_french_open",
    "tennis_wta_french_open",
    "tennis_atp_wimbledon",
    "tennis_atp_us_open",
    "tennis_wta_us_open",
    "tennis_atp_australian_open",
    "americanfootball_nfl",
]


def _fetch_odds_api_scores(sport_key: str, days_from: int = 3) -> list[dict]:
    """
    Fetch completed scores from The Odds API /scores endpoint.
    Returns list of dicts with external_id, home_score, away_score, result.
    """
    if not settings.odds_api_key:
        return []
    try:
        with httpx.Client(timeout=15) as c:
            resp = c.get(
                f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/",
                params={"apiKey": settings.odds_api_key, "daysFrom": days_from},
            )
            if resp.status_code != 200:
                return []
            events = resp.json()
    except Exception as e:
        logger.debug(f"Odds API scores [{sport_key}]: {e}")
        return []

    results: list[dict] = []
    for ev in events:
        if not ev.get("completed"):
            continue

        home_team  = ev.get("home_team", "")
        away_team  = ev.get("away_team", "")
        scores_raw = ev.get("scores") or []
        score_map  = {s["name"]: s["score"] for s in scores_raw if s.get("name") and s.get("score")}

        try:
            home_score = int(score_map.get(home_team, 0))
            away_score = int(score_map.get(away_team, 0))
        except (ValueError, TypeError):
            continue

        result = "H" if home_score > away_score else ("A" if away_score > home_score else "D")

        results.append({
            "external_id": f"oa_{ev['id']}",
            "home_score":  home_score,
            "away_score":  away_score,
            "result":      result,
            "home_name":   home_team,
            "away_name":   away_team,
        })

    return results


def fetch_and_update_results(db: Session) -> int:
    """
    Poll all result sources and update finished matches in the database.
    Returns the number of matches updated.
    """
    from data.db_models.models import Match, Participant
    from sqlalchemy import func

    updated = 0

    # ── Source 1: The Odds API scores ─────────────────────────────────
    if settings.odds_api_key:
        for sport_key in ODDS_API_SCOREABLE_SPORTS:
            results = _fetch_odds_api_scores(sport_key, days_from=4)
            for r in results:
                match = db.query(Match).filter_by(external_id=r["external_id"]).first()
                if match and match.status != "finished":
                    match.status     = "finished"
                    match.home_score = r["home_score"]
                    match.away_score = r["away_score"]
                    match.result     = r["result"]
                    updated += 1
            time.sleep(0.2)

        if updated:
            db.commit()
            logger.info(f"Updated {updated} match results from The Odds API")

    # ── Source 2: API-Football ────────────────────────────────────────
    if settings.api_football_key:
        from data.sources.api_football import APIFootballClient
        client  = APIFootballClient()
        results = client.fetch_results_last_n_days(days=4)
        af_upd  = 0

        for r in results:
            match = db.query(Match).filter_by(external_id=r["external_id"]).first()

            if not match:
                # Fuzzy match by team names
                home_p = db.query(Participant).filter(
                    func.lower(Participant.name) == r["home_name"].lower()
                ).first()
                away_p = db.query(Participant).filter(
                    func.lower(Participant.name) == r["away_name"].lower()
                ).first()
                if home_p and away_p:
                    match = (
                        db.query(Match)
                        .filter_by(home_id=home_p.id, away_id=away_p.id)
                        .filter(Match.status.in_(["scheduled", "live"]))
                        .first()
                    )

            if match and match.status != "finished":
                match.status     = "finished"
                match.home_score = r["home_score"]
                match.away_score = r["away_score"]
                match.result     = r["result"]
                af_upd += 1

        if af_upd:
            db.commit()
            logger.info(f"Updated {af_upd} match results from API-Football")
            updated += af_upd

    return updated
