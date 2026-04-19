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

Matching strategy (no external ID dependency):
  Date window ± 24h + fuzzy team name similarity ≥ 0.70.
  This works across Sofascore, ESPN, Odds API, and API-Football which all
  use different ID schemes and slightly different team name spellings.
"""
from __future__ import annotations
import re
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


# ── Fuzzy name matching ───────────────────────────────────────────────────────

# Common words that add noise but carry no identity signal
_NOISE_WORDS = {
    "fc", "cf", "sc", "ac", "afc", "fk", "sk", "bk", "if", "ik",
    "united", "city", "town", "athletic", "athletics", "sport", "sports",
    "club", "de", "del", "the", "real", "new",
}

def _normalize(name: str) -> str:
    """Lowercase, strip punctuation, remove noise words."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s]", " ", name)   # punctuation → space
    name = re.sub(r"\s+", " ", name).strip()
    tokens = [t for t in name.split() if t not in _NOISE_WORDS and len(t) > 1]
    return " ".join(tokens)


def _similarity(a: str, b: str) -> float:
    """
    Token-overlap similarity between two team names after normalization.
    Returns 0.0–1.0. Threshold for a confident match: ≥ 0.70.
    """
    na = _normalize(a)
    nb = _normalize(b)

    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # Containment (e.g. "Man United" vs "Manchester United")
    if na in nb or nb in na:
        return 0.85

    ta = set(na.split())
    tb = set(nb.split())
    union = ta | tb
    if not union:
        return 0.0
    return len(ta & tb) / len(union)   # Jaccard


def _find_match_fuzzy(
    db: Session,
    home_name: str,
    away_name: str,
    match_date: datetime,
    window_hours: int = 24,
    min_score: float = 0.70,
) -> Optional[object]:
    """
    Find an unresolved Match in the DB by date proximity + fuzzy team names.

    Loads all unfinished matches in the ±window_hours window, scores each
    by (home_similarity + away_similarity) / 2, returns the best if ≥ min_score.
    """
    from data.db_models.models import Match

    date_from = match_date - timedelta(hours=window_hours)
    date_to   = match_date + timedelta(hours=window_hours)

    candidates = (
        db.query(Match)
        .filter(
            Match.match_date >= date_from,
            Match.match_date <= date_to,
            Match.status.in_(["scheduled", "live"]),
            Match.result.is_(None),
        )
        .all()
    )

    best_match = None
    best_score = 0.0

    for m in candidates:
        if not m.home or not m.away:
            continue
        h_sim = _similarity(home_name, m.home.name)
        a_sim = _similarity(away_name, m.away.name)
        score = (h_sim + a_sim) / 2.0
        if score > best_score:
            best_score = score
            best_match = m

    if best_match and best_score >= min_score:
        logger.debug(
            f"Fuzzy match ({best_score:.2f}): "
            f"'{home_name} v {away_name}' → "
            f"'{best_match.home.name} v {best_match.away.name}'"
        )
        return best_match

    if best_score > 0.50:
        logger.debug(
            f"Fuzzy match below threshold ({best_score:.2f}): "
            f"'{home_name} v {away_name}' — skipped"
        )
    return None


# ── Odds API ──────────────────────────────────────────────────────────────────

def _fetch_odds_api_scores(sport_key: str, days_from: int = 3) -> list[dict]:
    """
    Fetch completed scores from The Odds API /scores endpoint.
    Returns list of dicts: home_name, away_name, match_date, home_score, away_score, result.
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

        # Parse commence_time for date-window matching
        match_date = None
        try:
            ct = ev.get("commence_time")
            if ct:
                match_date = datetime.fromisoformat(ct.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            match_date = datetime.utcnow() - timedelta(days=1)

        result = "H" if home_score > away_score else ("A" if away_score > home_score else "D")

        results.append({
            "home_name":  home_team,
            "away_name":  away_team,
            "match_date": match_date,
            "home_score": home_score,
            "away_score": away_score,
            "result":     result,
        })

    return results


# ── Main entry point ──────────────────────────────────────────────────────────

def fetch_and_update_results(db: Session) -> int:
    """
    Poll all result sources and update finished matches in the database.
    Uses fuzzy date + team-name matching — no external ID dependency.
    Returns the number of matches updated.
    """
    updated = 0

    # ── Source 1: The Odds API scores ─────────────────────────────────
    if settings.odds_api_key:
        oa_updated = 0
        for sport_key in ODDS_API_SCOREABLE_SPORTS:
            results = _fetch_odds_api_scores(sport_key, days_from=4)
            for r in results:
                if not r.get("match_date"):
                    continue
                match = _find_match_fuzzy(
                    db,
                    r["home_name"],
                    r["away_name"],
                    r["match_date"],
                )
                if match:
                    match.status     = "finished"
                    match.home_score = r["home_score"]
                    match.away_score = r["away_score"]
                    match.result     = r["result"]
                    oa_updated += 1
            time.sleep(0.2)

        if oa_updated:
            db.commit()
            logger.info(f"Updated {oa_updated} match results from The Odds API")
            updated += oa_updated

    # ── Source 2: API-Football ────────────────────────────────────────
    if settings.api_football_key:
        from data.sources.api_football import APIFootballClient
        client  = APIFootballClient()
        results = client.fetch_results_last_n_days(days=4)
        af_updated = 0

        for r in results:
            # Try exact external_id first (fast path)
            from data.db_models.models import Match
            match = db.query(Match).filter_by(external_id=r.get("external_id")).first()

            # Fall back to fuzzy if no ID match
            if not match and r.get("match_date") and r.get("home_name") and r.get("away_name"):
                match_date = r["match_date"]
                if isinstance(match_date, str):
                    try:
                        match_date = datetime.fromisoformat(match_date)
                    except Exception:
                        match_date = None
                if match_date:
                    match = _find_match_fuzzy(
                        db,
                        r["home_name"],
                        r["away_name"],
                        match_date,
                    )

            if match and match.status != "finished":
                match.status     = "finished"
                match.home_score = r["home_score"]
                match.away_score = r["away_score"]
                match.result     = r["result"]
                af_updated += 1

        if af_updated:
            db.commit()
            logger.info(f"Updated {af_updated} match results from API-Football")
            updated += af_updated

    return updated
