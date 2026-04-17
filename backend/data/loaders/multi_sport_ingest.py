"""
Multi-sport historical data ingestion via Sofascore + ESPN.

Strategy:
  - Sofascore /sport/{slug}/scheduled-events/{date} → fetch every date in range
  - ESPN scoreboard with ?dates=YYYYMMDD-YYYYMMDD&limit=500 → bulk fetch per season
  - Upserts Sport, Competition, Participant, Match rows into DB
  - Runs incrementally: only fetches dates not already in DB

The more historical data we collect, the better the ML model predicts.
Run via scheduler job_ingest_multi_sport_history() (weekly, off-peak).
Run manually via:   python -m data.loaders.multi_sport_ingest
"""
from __future__ import annotations

import httpx
import concurrent.futures
from datetime import date, datetime, timedelta
from loguru import logger
from sqlalchemy.orm import Session

# ── Sport definitions ─────────────────────────────────────────────────────────

# (sofascore_slug, sport_key, display_name, icon, has_draw)
SPORTS_CONFIG = [
    ("football",          "football",          "Football",         "⚽", True),
    ("basketball",        "basketball",        "Basketball",       "🏀", False),
    ("tennis",            "tennis",            "Tennis",           "🎾", False),
    ("baseball",          "baseball",          "Baseball",         "⚾", False),
    ("american-football", "american_football", "American Football","🏈", False),
    ("ice-hockey",        "ice_hockey",        "Ice Hockey",       "🏒", False),
    ("cricket",           "cricket",           "Cricket",          "🏏", True),
    ("rugby",             "rugby",             "Rugby",            "🏉", False),
    ("handball",          "handball",          "Handball",         "🤾", True),
    ("volleyball",        "volleyball",        "Volleyball",       "🏐", False),
]

_SS_BASE    = "https://api.sofascore.com/api/v1"
_SS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
}

_ESPN_BASE    = "https://site.api.espn.com/apis/site/v2/sports"
_ESPN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# ESPN scoreboard paths for bulk historical fetches
ESPN_SPORT_PATHS = {
    "football":          None,          # handled separately via standings.py
    "basketball":        "basketball/nba",
    "baseball":          "baseball/mlb",
    "american_football": "football/nfl",
    "ice_hockey":        "hockey/nhl",
}


# ── Sofascore fetchers ────────────────────────────────────────────────────────

def fetch_sofascore_day(ss_slug: str, sport_key: str, day: date, timeout: int = 12) -> list[dict]:
    """Fetch all events (all statuses) for a sport on a given date."""
    try:
        resp = httpx.get(
            f"{_SS_BASE}/sport/{ss_slug}/scheduled-events/{day.isoformat()}",
            headers=_SS_HEADERS,
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        return [_parse_ss_event(e, sport_key) for e in resp.json().get("events", [])]
    except Exception:
        return []


def _parse_ss_event(e: dict, sport_key: str) -> dict:
    """Parse Sofascore event into a normalised dict suitable for DB ingestion."""
    tournament  = e.get("tournament", {})
    category    = tournament.get("category", {})
    unique_t    = tournament.get("uniqueTournament", {})
    home        = e.get("homeTeam", {})
    away        = e.get("awayTeam", {})
    hs          = e.get("homeScore", {})
    as_         = e.get("awayScore", {})
    status      = e.get("status", {})
    ts          = e.get("startTimestamp")

    status_type = status.get("type", "")
    if status_type in ("finished", "ended"):
        status_str = "finished"
    elif status_type == "inprogress":
        status_str = "live"
    else:
        status_str = "scheduled"

    home_score = hs.get("current")
    away_score = as_.get("current")

    # Derive result only for finished matches
    result = None
    if status_str == "finished" and home_score is not None and away_score is not None:
        if home_score > away_score:
            result = "H"
        elif away_score > home_score:
            result = "A"
        else:
            result = "D"   # draw (or N/A for no-draw sports — handled by training skip)

    match_dt = datetime.utcfromtimestamp(ts) if ts else None

    return {
        "external_id":    f"ss_{e.get('id', '')}",
        "sport_key":      sport_key,
        "competition_ext": f"ss_comp_{unique_t.get('id', tournament.get('id', ''))}",
        "competition_name": tournament.get("name", ""),
        "country":        category.get("name", ""),
        "home_ext":       f"ss_team_{home.get('id', '')}",
        "home_name":      home.get("name") or home.get("shortName", ""),
        "away_ext":       f"ss_team_{away.get('id', '')}",
        "away_name":      away.get("name") or away.get("shortName", ""),
        "home_score":     int(home_score) if home_score is not None else None,
        "away_score":     int(away_score) if away_score is not None else None,
        "result":         result,
        "status":         status_str,
        "match_date":     match_dt,
        "source":         "sofascore",
    }


# ── ESPN bulk fetcher (for supported sports) ──────────────────────────────────

def fetch_espn_season(sport_key: str, season_year: int) -> list[dict]:
    """
    Fetch all events for a sport/season from ESPN using date-range scoreboard.
    Only works for ESPN-mapped sports.  Football is handled by standings.py.
    """
    path = ESPN_SPORT_PATHS.get(sport_key)
    if not path:
        return []

    # Season boundaries — US sports (calendar year)
    from_date = f"{season_year}0101"
    to_date   = f"{season_year}1231"

    try:
        resp = httpx.get(
            f"{_ESPN_BASE}/{path}/scoreboard",
            params={"dates": f"{from_date}-{to_date}", "limit": 1000},
            headers=_ESPN_HEADERS,
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        events = resp.json().get("events", [])
        return [_parse_espn_event(e, sport_key) for e in events]
    except Exception as e:
        logger.warning(f"ESPN season fetch failed {sport_key}/{season_year}: {e}")
        return []


def _parse_espn_event(e: dict, sport_key: str) -> dict:
    """Parse ESPN scoreboard event into normalised ingestion dict."""
    comp        = (e.get("competitions") or [{}])[0]
    competitors = comp.get("competitors", [])
    stype       = e.get("status", {}).get("type", {})

    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})

    completed  = stype.get("completed", False)
    status_str = "finished" if completed else ("live" if stype.get("state") == "in" else "scheduled")

    def _tid(c): return str((c.get("team") or {}).get("id") or "")
    def _tname(c): return (c.get("team") or {}).get("displayName") or (c.get("team") or {}).get("name") or ""

    def _score(c):
        raw = c.get("score")
        if isinstance(raw, dict):
            raw = raw.get("displayValue") or raw.get("value")
        try:
            return int(raw) if raw not in (None, "", "--") else None
        except (TypeError, ValueError):
            return None

    hs = _score(home)
    as_ = _score(away)
    result = None
    if status_str == "finished" and hs is not None and as_ is not None:
        result = "H" if hs > as_ else ("A" if hs < as_ else "D")

    league   = (e.get("competitions") or [{}])[0].get("league") or {}
    date_str = comp.get("date") or e.get("date") or ""
    match_dt = None
    if date_str:
        try:
            match_dt = datetime.fromisoformat(date_str.rstrip("Z"))
        except Exception:
            pass

    return {
        "external_id":     f"espn_{e.get('id', '')}",
        "sport_key":       sport_key,
        "competition_ext": f"espn_comp_{league.get('id', sport_key)}",
        "competition_name": league.get("name") or sport_key.replace("_", " ").title(),
        "country":         "USA",
        "home_ext":        f"espn_team_{_tid(home)}",
        "home_name":       _tname(home),
        "away_ext":        f"espn_team_{_tid(away)}",
        "away_name":       _tname(away),
        "home_score":      hs,
        "away_score":      as_,
        "result":          result,
        "status":          status_str,
        "match_date":      match_dt,
        "source":          "espn",
    }


# ── DB upsert helpers ─────────────────────────────────────────────────────────

def _ensure_sport(db: Session, sport_key: str) -> int:
    from data.db_models.models import Sport
    row = db.query(Sport).filter_by(key=sport_key).first()
    if row:
        return row.id
    icon = next((ic for _, sk, _, ic, _ in SPORTS_CONFIG if sk == sport_key), "🏆")
    name = next((n for _, sk, n, _, _ in SPORTS_CONFIG if sk == sport_key), sport_key)
    row  = Sport(key=sport_key, name=name, icon=icon)
    db.add(row)
    db.flush()
    return row.id


def _ensure_competition(db: Session, ext_id: str, name: str, country: str, sport_id: int) -> int:
    from data.db_models.models import Competition
    row = db.query(Competition).filter_by(external_id=ext_id).first()
    if row:
        return row.id
    row = Competition(
        external_id=ext_id, name=name, country=country,
        sport_id=sport_id, active=True,
    )
    db.add(row)
    db.flush()
    return row.id


def _ensure_participant(db: Session, ext_id: str, name: str, sport_id: int) -> int:
    from data.db_models.models import Participant
    row = db.query(Participant).filter_by(external_id=ext_id).first()
    if row:
        return row.id
    row = Participant(
        external_id=ext_id, name=name, sport_id=sport_id, elo_rating=1500.0,
    )
    db.add(row)
    db.flush()
    return row.id


def upsert_events(db: Session, events: list[dict]) -> int:
    """
    Upsert a list of normalised event dicts into Sport/Competition/Participant/Match.
    Returns number of new matches inserted.
    """
    from data.db_models.models import Match

    inserted = 0
    sport_cache: dict[str, int]          = {}
    comp_cache:  dict[str, int]          = {}
    part_cache:  dict[str, int]          = {}

    for ev in events:
        if not ev.get("home_name") or not ev.get("away_name"):
            continue
        if not ev.get("match_date"):
            continue

        sport_key = ev["sport_key"]

        # Sport
        if sport_key not in sport_cache:
            sport_cache[sport_key] = _ensure_sport(db, sport_key)
        sport_id = sport_cache[sport_key]

        # Competition
        comp_ext = ev["competition_ext"]
        if comp_ext not in comp_cache:
            comp_cache[comp_ext] = _ensure_competition(
                db, comp_ext, ev["competition_name"], ev.get("country", ""), sport_id
            )
        comp_id = comp_cache[comp_ext]

        # Participants
        h_ext = ev["home_ext"]
        a_ext = ev["away_ext"]
        if h_ext not in part_cache:
            part_cache[h_ext] = _ensure_participant(db, h_ext, ev["home_name"], sport_id)
        if a_ext not in part_cache:
            part_cache[a_ext] = _ensure_participant(db, a_ext, ev["away_name"], sport_id)
        home_id = part_cache[h_ext]
        away_id = part_cache[a_ext]

        # Match — upsert
        ext_id = ev["external_id"]
        match  = db.query(Match).filter_by(external_id=ext_id).first()
        if match:
            # Update score/result if now available
            if ev["home_score"] is not None:
                match.home_score = ev["home_score"]
            if ev["away_score"] is not None:
                match.away_score = ev["away_score"]
            if ev["result"]:
                match.result = ev["result"]
            if ev["status"] != "scheduled":
                match.status = ev["status"]
        else:
            match = Match(
                external_id    = ext_id,
                competition_id = comp_id,
                home_id        = home_id,
                away_id        = away_id,
                match_date     = ev["match_date"],
                status         = ev["status"],
                home_score     = ev["home_score"],
                away_score     = ev["away_score"],
                result         = ev["result"],
            )
            db.add(match)
            inserted += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Upsert commit failed: {e}")

    return inserted


# ── Incremental ingestion orchestrator ────────────────────────────────────────

def ingest_sport_date_range(
    db: Session,
    ss_slug: str,
    sport_key: str,
    start: date,
    end: date,
    max_workers: int = 4,
) -> int:
    """
    Fetch and upsert all events for a sport between start and end (inclusive).
    Skips dates that already have data in the DB for this sport.
    Returns total new matches inserted.
    """
    from data.db_models.models import Match, Competition, Sport
    from sqlalchemy import func

    sport_row = db.query(Sport).filter_by(key=sport_key).first()

    # Build set of dates already in DB (to avoid re-fetching)
    existing_dates: set[date] = set()
    if sport_row:
        rows = db.query(func.date(Match.match_date)).join(Competition).filter(
            Competition.sport_id == sport_row.id
        ).distinct().all()
        existing_dates = {r[0] for r in rows if r[0]}

    days = []
    cur  = start
    while cur <= end:
        if cur not in existing_dates:
            days.append(cur)
        cur += timedelta(days=1)

    if not days:
        logger.info(f"[ingest] {sport_key}: all dates already in DB, nothing to fetch")
        return 0

    logger.info(f"[ingest] {sport_key}: fetching {len(days)} new dates from Sofascore...")

    total_inserted = 0
    batch_size     = 30   # commit every 30 days to avoid huge transactions

    def _fetch_day(d: date) -> list[dict]:
        return fetch_sofascore_day(ss_slug, sport_key, d)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_day, d): d for d in days}
        batch: list[dict] = []
        for fut in concurrent.futures.as_completed(futures):
            try:
                batch.extend(fut.result())
            except Exception:
                pass
            if len(batch) >= batch_size * 20:   # ~20 events/day average
                total_inserted += upsert_events(db, batch)
                batch = []

        if batch:
            total_inserted += upsert_events(db, batch)

    logger.info(f"[ingest] {sport_key}: inserted {total_inserted} new matches")
    return total_inserted


def run_full_multi_sport_ingest(db: Session, days_back: int = 365 * 3) -> dict[str, int]:
    """
    Ingest up to `days_back` days of historical data for all sports from Sofascore.
    Run weekly during off-peak hours.  Incremental — skips already-fetched dates.
    Returns {sport_key: new_matches_inserted}.
    """
    end   = date.today() - timedelta(days=1)   # yesterday (today is incomplete)
    start = end - timedelta(days=days_back)

    results: dict[str, int] = {}
    for ss_slug, sport_key, _, _, _ in SPORTS_CONFIG:
        try:
            n = ingest_sport_date_range(db, ss_slug, sport_key, start, end)
            results[sport_key] = n
        except Exception as e:
            logger.error(f"[ingest] {sport_key} failed: {e}")
            results[sport_key] = 0

    return results


# ── ESPN supplemental ingestion for US sports ─────────────────────────────────

def run_espn_historical_ingest(db: Session, seasons: list[int] | None = None) -> dict[str, int]:
    """
    Bulk ingest historical seasons from ESPN for NBA, MLB, NFL, NHL.
    Complements Sofascore with ESPN's richer US sports coverage.
    """
    if seasons is None:
        current_year = datetime.utcnow().year
        seasons = list(range(current_year - 5, current_year + 1))

    results: dict[str, int] = {}
    for sport_key in ["basketball", "baseball", "american_football", "ice_hockey"]:
        total = 0
        for season in seasons:
            try:
                events    = fetch_espn_season(sport_key, season)
                if events:
                    inserted  = upsert_events(db, events)
                    total    += inserted
                    logger.info(f"[espn-ingest] {sport_key}/{season}: {inserted} matches inserted")
            except Exception as e:
                logger.warning(f"[espn-ingest] {sport_key}/{season} failed: {e}")
        results[sport_key] = total

    return results


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 365

    from data.database import get_sync_session
    with get_sync_session() as db:
        results = run_full_multi_sport_ingest(db, days_back=days)
        espn_r  = run_espn_historical_ingest(db)

    print("\n=== Multi-sport ingestion complete ===")
    for sport, n in {**results, **espn_r}.items():
        print(f"  {sport:25s}: {n:,} new matches")
