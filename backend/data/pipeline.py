"""
Data ingestion pipeline.

Entry points:
  run_live_fetch()        — pull upcoming fixtures + odds (Sportybet + Odds API)
  run_historical_load()   — download and ingest full historical data (one-time setup)
  run_full_season_fetch() — download current season from API-Football (all fixtures)
"""
from __future__ import annotations
import json
from datetime import datetime
from loguru import logger
from sqlalchemy.orm import Session
from data.db_models.models import Sport, Competition, Participant, Match, MatchOdds
from data.database import get_sync_session


SPORTS_META = {
    "football":          {"name": "Football",          "icon": "⚽"},
    "basketball":        {"name": "Basketball",        "icon": "🏀"},
    "tennis":            {"name": "Tennis",            "icon": "🎾"},
    "american_football": {"name": "American Football", "icon": "🏈"},
    "table_tennis":      {"name": "Table Tennis",      "icon": "🏓"},
    "volleyball":        {"name": "Volleyball",        "icon": "🏐"},
    "ice_hockey":        {"name": "Ice Hockey",        "icon": "🏒"},
    "cricket":           {"name": "Cricket",           "icon": "🏏"},
    "rugby":             {"name": "Rugby",             "icon": "🏉"},
    "baseball":          {"name": "Baseball",          "icon": "⚾"},
}


# ── DB helpers ────────────────────────────────────────────────────────

def _get_or_create_sport(db: Session, key: str) -> Sport:
    s = db.query(Sport).filter_by(key=key).first()
    if not s:
        meta = SPORTS_META.get(key, {"name": key.title(), "icon": "🏆"})
        s    = Sport(key=key, name=meta["name"], icon=meta["icon"])
        db.add(s)
        db.flush()
    return s


def _get_or_create_competition(db: Session, sport: Sport, name: str, country: str) -> Competition:
    ext_id = f"{sport.key}_{name}_{country}".replace(" ", "_").lower()[:100]
    c = db.query(Competition).filter_by(external_id=ext_id).first()
    if not c:
        c = Competition(sport_id=sport.id, external_id=ext_id, name=name, country=country)
        db.add(c)
        db.flush()
    return c


def _get_or_create_participant(db: Session, sport: Sport, name: str) -> Participant:
    ext_id = f"{sport.key}_{name}".replace(" ", "_").lower()[:100]
    p = db.query(Participant).filter_by(external_id=ext_id).first()
    if not p:
        p = Participant(sport_id=sport.id, external_id=ext_id, name=name)
        db.add(p)
        db.flush()
    return p


# ── Core ingest ───────────────────────────────────────────────────────

def ingest_events(db: Session, events: list[dict]) -> tuple[int, int]:
    """
    Upsert a list of normalised event dicts into the database.

    Each event dict must have:
      external_id, sport, competition, country, home_name, away_name,
      match_date, status

    Optional:
      result ("H"/"D"/"A"), home_score, away_score, odds (list of dicts)

    Returns (saved_new, updated_existing).
    """
    saved = updated = 0

    for ev in events:
        try:
            sport = _get_or_create_sport(db, ev["sport"])
            comp  = _get_or_create_competition(db, sport, ev["competition"], ev.get("country", ""))
            home  = _get_or_create_participant(db, sport, ev["home_name"])
            away  = _get_or_create_participant(db, sport, ev["away_name"])

            match = db.query(Match).filter_by(external_id=ev["external_id"]).first()

            extra_json = json.dumps(ev["extra"]) if ev.get("extra") else None

            if not match:
                match = Match(
                    external_id    = ev["external_id"],
                    competition_id = comp.id,
                    home_id        = home.id,
                    away_id        = away.id,
                    match_date     = ev["match_date"],
                    status         = ev.get("status", "scheduled"),
                    result         = ev.get("result"),
                    home_score     = ev.get("home_score"),
                    away_score     = ev.get("away_score"),
                    extra_data     = extra_json,
                )
                db.add(match)
                db.flush()
                saved += 1
            else:
                # Update if match has now finished
                new_status = ev.get("status", match.status)
                if new_status == "finished" and match.status != "finished":
                    match.status     = "finished"
                    match.result     = ev.get("result", match.result)
                    match.home_score = ev.get("home_score", match.home_score)
                    match.away_score = ev.get("away_score", match.away_score)
                    # Backfill shots/referee if we now have it and didn't before
                    if extra_json and not match.extra_data:
                        match.extra_data = extra_json
                    updated += 1
                elif new_status == "live" and match.status == "scheduled":
                    match.status = "live"
                    updated += 1

            # Attach fresh odds snapshots for upcoming/live matches
            if ev.get("status") in ("scheduled", "live") and ev.get("odds"):
                for o in ev["odds"]:
                    db.add(MatchOdds(
                        match_id  = match.id,
                        bookmaker = o["bookmaker"],
                        market    = o["market"],
                        outcome   = o["outcome"],
                        price     = o["price"],
                        point     = o.get("point"),
                    ))

        except Exception as e:
            logger.warning(f"Ingest error [{ev.get('external_id', '?')}]: {e}")
            db.rollback()
            continue

    db.commit()
    return saved, updated


# ── Live fetch (runs every 6 hours via scheduler) ─────────────────────

def run_live_fetch():
    """
    Pull latest upcoming fixtures + odds from all sources:
      1. Sportybet       — fixtures + h2h odds (no key required)
      2. The Odds API    — h2h / totals / btts / draw_no_bet / spreads
      3. API-Football    — 20+ markets: double chance, asian handicap,
                           win to nil, clean sheet, HT/FT, and more
    """
    from data.sources.sportybet          import SportybetClient
    from data.sources.odds_api           import OddsAPIClient
    from data.sources.api_football_odds  import fetch_and_save_af_odds

    sb_events = []
    oa_events = []

    # ── 1. Sportybet fixtures ────────────────────────────────────────
    try:
        sb = SportybetClient()
        sb_events = sb.get_all_sports(hours_ahead=168)   # 7 days ahead
        logger.info(f"Sportybet: {len(sb_events)} upcoming matches")
    except Exception as e:
        logger.error(f"Sportybet fetch error: {e}")

    # ── 2. The Odds API fixtures + base odds ─────────────────────────
    try:
        oa = OddsAPIClient()
        oa_events = oa.fetch_all()
        logger.info(f"Odds API: {len(oa_events)} matches")
    except Exception as e:
        logger.error(f"Odds API fetch error: {e}")

    # Ingest fixtures first so AF matches have DB ids before we add odds
    all_events = sb_events + oa_events
    with get_sync_session() as db:
        saved, updated = ingest_events(db, all_events)
    logger.info(f"Fixtures ingested — {saved} new, {updated} updated")

    # ── 3. API-Football extended odds (20+ markets) ──────────────────
    # Runs after fixture ingest so match rows exist; saves directly to MatchOdds
    try:
        with get_sync_session() as db:
            af_lines = fetch_and_save_af_odds(db, days_ahead=7)
        logger.info(f"API-Football odds: {af_lines} price lines saved")
    except Exception as e:
        logger.error(f"API-Football odds fetch error: {e}")

    logger.info("Live fetch complete")


# ── Historical load (one-time setup) ─────────────────────────────────

def run_historical_load():
    """
    Download and ingest complete historical match data from free sources:
      - football-data.co.uk CSVs  (11 leagues × 4 seasons)
      - Jeff Sackmann ATP/WTA     (2020–2025)
      - NBA official stats API    (2021–22 through 2024–25)

    This should be run once during production setup to build training data
    for the ML models. Takes ~5–10 minutes depending on network speed.
    """
    from data.loaders.football_csv  import download_all_historical as load_football
    from data.loaders.tennis_loader import fetch_all_tennis_historical as load_tennis
    from data.loaders.nba_loader    import fetch_all_nba_historical    as load_nba

    total_saved = total_updated = 0

    # 1. Football
    logger.info("=== Loading football historical data ===")
    football_events = load_football()
    with get_sync_session() as db:
        s, u = ingest_events(db, football_events)
    logger.info(f"Football: {s} saved, {u} updated")
    total_saved += s; total_updated += u

    # 2. Tennis
    logger.info("=== Loading tennis historical data ===")
    tennis_events = load_tennis()
    with get_sync_session() as db:
        s, u = ingest_events(db, tennis_events)
    logger.info(f"Tennis: {s} saved, {u} updated")
    total_saved += s; total_updated += u

    # 3. NBA
    logger.info("=== Loading NBA historical data ===")
    nba_events = load_nba()
    with get_sync_session() as db:
        s, u = ingest_events(db, nba_events)
    logger.info(f"NBA: {s} saved, {u} updated")
    total_saved += s; total_updated += u

    logger.info(f"Historical load complete — {total_saved} new, {total_updated} updated")
    return total_saved


# ── Full season fetch (API-Football) ─────────────────────────────────

def run_full_season_fetch():
    """
    Fetch the entire current season schedule from API-Football.
    Includes both played (with results) and upcoming fixtures.
    Requires API_FOOTBALL_KEY in .env.
    """
    from data.sources.api_football import APIFootballClient
    client = APIFootballClient()

    if not client.key:
        logger.warning("API_FOOTBALL_KEY not set — skipping full season fetch")
        return 0

    logger.info("=== Fetching full current season from API-Football ===")
    events = client.fetch_all_current_season()

    with get_sync_session() as db:
        saved, updated = ingest_events(db, events)

    logger.info(f"Full season fetch complete — {saved} new, {updated} updated")
    return saved
