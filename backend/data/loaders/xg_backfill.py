"""
Post-match xG backfill using API-Football.

After a match finishes, this module fetches the official xG, shots, shots on target,
and possession stats and writes them into the match's extra_data JSON field.

This enriches the training data so the model can learn from actual shot quality
rather than just goals — dramatically improving Over/Under and BTTS prediction.

Free tier usage: one API call per finished match. We backfill in batches of up to
50 matches per run (half the daily quota) so production usage stays within limits.

Scheduler: runs as part of job_resolve_matches (every 2 hours).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy.orm import Session


def backfill_xg(db: Session, api_key: str, max_matches: int = 50) -> int:
    """
    Find recently-finished matches that have no xG data and fetch it.

    Strategy:
      1. Query matches finished in the last 7 days with no extra_data xG
      2. Look up their API-Football fixture ID via name+date matching
      3. Fetch fixture stats → extract xG, shots, possession
      4. Merge into match.extra_data JSON

    Returns number of matches enriched.
    """
    if not api_key:
        logger.debug("[xG-backfill] No API_FOOTBALL_KEY — skipping")
        return 0

    from data.db_models.models import Match, Competition, Sport, Participant
    from data.loaders.api_football import get_fixture_stats, get_upcoming_fixtures
    from sqlalchemy.orm import joinedload

    cutoff = datetime.utcnow() - timedelta(days=7)

    matches = (
        db.query(Match)
        .join(Competition)
        .join(Sport, Competition.sport_id == Sport.id)
        .options(
            joinedload(Match.home),
            joinedload(Match.away),
            joinedload(Match.competition),
        )
        .filter(
            Match.status == "finished",
            Match.match_date >= cutoff,
            Sport.key == "football",
        )
        .all()
    )

    # Only process matches missing xG in their extra_data
    needs_xg = []
    for m in matches:
        extra = {}
        if m.extra_data:
            try:
                extra = json.loads(m.extra_data)
            except Exception:
                pass
        if "home_xg" not in extra:
            needs_xg.append(m)

    if not needs_xg:
        logger.debug("[xG-backfill] All recent matches already have xG data")
        return 0

    to_process = needs_xg[:max_matches]
    logger.info(f"[xG-backfill] Enriching {len(to_process)} matches with xG data")

    enriched = 0
    for m in to_process:
        try:
            # Try to look up API-Football fixture ID from the match
            # First check if we stored it in extra_data during ingest
            extra = {}
            if m.extra_data:
                try:
                    extra = json.loads(m.extra_data)
                except Exception:
                    pass

            fixture_id = extra.get("api_football_fixture_id")

            if not fixture_id:
                # Try to find via API-Football search (uses home team api_football_id)
                fixture_id = _find_fixture_id(
                    api_key,
                    m.home,
                    m.away,
                    m.match_date,
                )
                if fixture_id:
                    extra["api_football_fixture_id"] = fixture_id

            if not fixture_id:
                logger.debug(f"[xG-backfill] No fixture ID for {m.id} — skipping")
                continue

            stats = get_fixture_stats(api_key, fixture_id)
            if not stats or "home" not in stats:
                continue

            h = stats["home"]
            a = stats["away"]

            # Merge into existing extra_data
            extra["home_xg"]              = h.get("xg")
            extra["away_xg"]              = a.get("xg")
            extra["hs"]                   = h.get("shots",           extra.get("hs"))
            extra["as_"]                  = a.get("shots",           extra.get("as_"))
            extra["hst"]                  = h.get("shots_on_target", extra.get("hst"))
            extra["ast"]                  = a.get("shots_on_target", extra.get("ast"))
            extra["home_possession"]      = h.get("possession")
            extra["away_possession"]      = a.get("possession")
            extra["hy"]                   = h.get("yellow_cards",    extra.get("hy"))
            extra["ay"]                   = a.get("yellow_cards",    extra.get("ay"))
            extra["hr"]                   = h.get("red_cards",       extra.get("hr"))
            extra["ar"]                   = a.get("red_cards",       extra.get("ar"))

            m.extra_data = json.dumps(extra)
            db.add(m)
            enriched += 1

        except Exception as e:
            logger.warning(f"[xG-backfill] Error for match {m.id}: {e}")
            continue

    if enriched > 0:
        db.commit()

    logger.info(f"[xG-backfill] Enriched {enriched} matches with xG + shot data")
    return enriched


def _find_fixture_id(
    api_key: str,
    home: object | None,
    away: object | None,
    match_date: datetime,
) -> int | None:
    """
    Attempt to find the API-Football fixture ID by matching team IDs and date.
    Uses api_football_id on the Participant if available.
    """
    from data.loaders.api_football import get_upcoming_fixtures, _fetch

    home_api_id = getattr(home, "api_football_id", None)
    away_api_id = getattr(away, "api_football_id", None)

    if not home_api_id or not away_api_id:
        return None

    date_str = match_date.strftime("%Y-%m-%d")
    data = _fetch(api_key, "fixtures", {
        "team": home_api_id,
        "date": date_str,
    })
    fixtures = data.get("response", [])
    for fix in fixtures:
        teams  = fix.get("teams", {})
        if teams.get("away", {}).get("id") == away_api_id:
            return fix.get("fixture", {}).get("id")

    return None


# ── API-Football team ID seeder ───────────────────────────────────────────────

def seed_api_football_ids(db: Session, api_key: str, league_id: int, season: int) -> int:
    """
    Populate api_football_id on Participant rows by matching team names
    from a known API-Football league/season response.

    Run once per league after initial data load:
        seed_api_football_ids(db, api_key, league_id=39, season=2024)  # PL

    Returns count of participants updated.
    """
    if not api_key:
        logger.debug("[xG-seed] No API_FOOTBALL_KEY — skipping")
        return 0

    from data.db_models.models import Participant, Sport
    from data.loaders.api_football import _fetch

    data = _fetch(api_key, "teams", {"league": league_id, "season": season})
    api_teams = data.get("response", [])
    if not api_teams:
        logger.warning(f"[xG-seed] No teams found for league={league_id} season={season}")
        return 0

    sport = db.query(Sport).filter_by(key="football").first()
    if not sport:
        return 0

    updated = 0
    for entry in api_teams:
        team = entry.get("team", {})
        api_id   = team.get("id")
        api_name = team.get("name", "").strip().lower()
        if not api_id or not api_name:
            continue

        # Fuzzy match against our participant names
        participants = db.query(Participant).filter(
            Participant.sport_id == sport.id,
            Participant.api_football_id.is_(None),
        ).all()

        for p in participants:
            if _name_matches(p.name, api_name):
                p.api_football_id = api_id
                db.add(p)
                updated += 1
                break

    if updated > 0:
        db.commit()

    logger.info(f"[xG-seed] Seeded api_football_id for {updated} teams (league={league_id})")
    return updated


def _name_matches(our_name: str, api_name: str) -> bool:
    """Simple normalised name comparison."""
    def norm(s: str) -> str:
        return s.lower().strip().replace("  ", " ").replace("fc ", "").replace(" fc", "").replace(".", "")
    return norm(our_name) == norm(api_name) or norm(our_name) in norm(api_name) or norm(api_name) in norm(our_name)
