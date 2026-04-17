"""
Live scores integration — ESPN as primary source.

Sources (in priority order):
  1. ESPN public scoreboard API  — no auth, no quota, exact live minute
  2. API-Football                — fallback only (100 req/day shared cap)

ESPN covers all major leagues simultaneously with no authentication.
Data refreshes every ~30s on their side; we poll every 60s.
"""
from __future__ import annotations
import httpx
import concurrent.futures
from datetime import datetime, date, timedelta
from loguru import logger

# ── Constants ─────────────────────────────────────────────────────────────────

_ESPN_BASE     = "https://site.api.espn.com/apis/site/v2/sports/soccer"
_ESPN_HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# All leagues ESPN covers — (slug, display_name, country)
ESPN_LEAGUES = [
    ("eng.1",                  "Premier League",           "England"),
    ("eng.2",                  "Championship",             "England"),
    ("eng.3",                  "League One",               "England"),
    ("eng.4",                  "League Two",               "England"),
    ("esp.1",                  "La Liga",                  "Spain"),
    ("ger.1",                  "Bundesliga",               "Germany"),
    ("ita.1",                  "Serie A",                  "Italy"),
    ("ita.2",                  "Serie B",                  "Italy"),
    ("fra.1",                  "Ligue 1",                  "France"),
    ("por.1",                  "Primeira Liga",            "Portugal"),
    ("ned.1",                  "Eredivisie",               "Netherlands"),
    ("tur.1",                  "Süper Lig",                "Turkey"),
    ("sco.1",                  "Scottish Premiership",     "Scotland"),
    ("bel.1",                  "First Division A",         "Belgium"),
    ("usa.1",                  "MLS",                      "USA"),
    ("mex.1",                  "Liga MX",                  "Mexico"),
    ("bra.1",                  "Brasileirão",              "Brazil"),
    ("arg.1",                  "Liga Profesional",         "Argentina"),
    ("col.1",                  "Liga BetPlay",             "Colombia"),
    ("chi.1",                  "Primera División",         "Chile"),
    ("ecu.1",                  "LigaPro",                  "Ecuador"),
    ("per.1",                  "Liga 1",                   "Peru"),
    ("uru.1",                  "Primera División",         "Uruguay"),
    ("par.1",                  "Primera División",         "Paraguay"),
    ("bol.1",                  "División Profesional",     "Bolivia"),
    ("ven.1",                  "Primera División",         "Venezuela"),
    ("sau.1",                  "Saudi Pro League",         "Saudi Arabia"),
    ("jpn.1",                  "J1 League",                "Japan"),
    ("chn.1",                  "Chinese Super League",     "China"),
    ("uefa.champions",         "Champions League",         "Europe"),
    ("uefa.europa",            "Europa League",            "Europe"),
    ("uefa.europa.conf",       "Conference League",        "Europe"),
    ("conmebol.libertadores",  "Copa Libertadores",        "South America"),
    ("conmebol.sudamericana",  "Copa Sudamericana",        "South America"),
    ("concacaf.champions",     "CONCACAF Champions Cup",   "CONCACAF"),
]

_API_BASE     = "https://v3.football.api-sports.io"
_RAPIDAPI_BASE = "https://api-football-v1.p.rapidapi.com/v3"


# ── ESPN fetcher (PRIMARY — no auth, no quota) ────────────────────────────────

def _fetch_espn_league(slug: str, country: str, timeout: int = 8) -> list[dict]:
    """Fetch scoreboard for one ESPN league. Returns live fixtures only."""
    try:
        resp = httpx.get(
            f"{_ESPN_BASE}/{slug}/scoreboard",
            headers=_ESPN_HEADERS,
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        events = data.get("events", [])
        results = []
        for e in events:
            stype = e.get("status", {}).get("type", {})
            state = stype.get("state", "")
            name  = stype.get("name", "")
            # Include in-progress and halftime; exclude pre-match and final
            if state == "in" or name in ("STATUS_HALFTIME", "STATUS_IN_PROGRESS",
                                          "STATUS_SECOND_HALF", "STATUS_FIRST_HALF",
                                          "STATUS_OVERTIME", "STATUS_EXTRA_TIME",
                                          "STATUS_PENALTY"):
                results.append(_parse_espn_event(e, country))
        return results
    except Exception:
        return []


def _parse_espn_event(e: dict, country: str) -> dict:
    """Parse a single ESPN event into our internal format."""
    comp       = e.get("competitions", [{}])[0]
    competitors = comp.get("competitors", [])
    status     = e.get("status", {})
    stype      = status.get("type", {})

    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})

    # Parse live minute from displayClock (e.g. "58'" → 58)
    clock_str  = status.get("displayClock", "")
    live_min   = None
    try:
        live_min = int(clock_str.replace("'", "").replace("+", "").strip().split("+")[0])
    except (ValueError, IndexError):
        pass

    # Status mapping
    desc = stype.get("name", "")
    if desc in ("STATUS_HALFTIME",):
        status_str  = "live"
        live_min    = 45
        clock_str   = "HT"
    elif stype.get("state") == "in":
        status_str  = "live"
    elif stype.get("completed"):
        status_str  = "finished"
    else:
        status_str  = "scheduled"

    home_score_raw = home.get("score", "")
    away_score_raw = away.get("score", "")
    try:
        home_score = int(home_score_raw) if home_score_raw not in (None, "", "--") else None
        away_score = int(away_score_raw) if away_score_raw not in (None, "", "--") else None
    except (ValueError, TypeError):
        home_score = away_score = None

    home_name  = home.get("team", {}).get("displayName") or home.get("team", {}).get("shortDisplayName", "")
    away_name  = away.get("team", {}).get("displayName") or away.get("team", {}).get("shortDisplayName", "")
    league_name = e.get("season", {}).get("slug", "") or ""

    # Use ESPN event ID as external_id with prefix so it doesn't clash
    ext_id = f"espn_{e.get('id', '')}"

    return {
        "fixture_id":  e.get("id"),
        "external_id": ext_id,
        "home_team":   home_name,
        "away_team":   away_name,
        "home_score":  home_score,
        "away_score":  away_score,
        "status":      status_str,
        "live_minute": live_min,
        "clock_str":   clock_str,
        "league_name": league_name,
        "country":     country,
        "match_date":  comp.get("date", "") or e.get("date", ""),
        "api_status":  stype.get("name", ""),
    }


def fetch_live_fixtures_espn() -> list[dict]:
    """
    Fetch ALL live matches across all supported leagues in parallel.
    No authentication. No daily quota. Returns internal fixture dicts.
    """
    live: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = {
            pool.submit(_fetch_espn_league, slug, country): slug
            for slug, _, country in ESPN_LEAGUES
        }
        for fut in concurrent.futures.as_completed(futures):
            try:
                live.extend(fut.result())
            except Exception:
                pass
    logger.info(f"ESPN live scores: {len(live)} live matches across all leagues")
    return live


# ── API-Football (FALLBACK only) ───────────────────────────────────────────────

def _headers(api_key: str) -> dict:
    if len(api_key) > 40:
        return {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"}
    return {"x-apisports-key": api_key}


def _base(api_key: str) -> str:
    return _RAPIDAPI_BASE if len(api_key) > 40 else _API_BASE


def fetch_live_fixtures(api_key: str) -> list[dict]:
    """API-Football fallback — only called when ESPN returns nothing."""
    if not api_key:
        return []
    try:
        resp = httpx.get(
            f"{_base(api_key)}/fixtures",
            params={"live": "all"},
            headers=_headers(api_key),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        errors = data.get("errors", {})
        if errors:
            logger.warning(f"API-Football error: {errors}")
            return []
        fixtures = data.get("response", [])
        logger.info(f"API-Football fallback: {len(fixtures)} live fixtures")
        return [_parse_fixture(f) for f in fixtures]
    except Exception as e:
        logger.warning(f"API-Football live fetch failed: {e}")
        return []


def fetch_todays_fixtures(api_key: str) -> list[dict]:
    """Fetch all fixtures for today from API-Football."""
    if not api_key:
        return []
    today = date.today().strftime("%Y-%m-%d")
    try:
        resp = httpx.get(
            f"{_base(api_key)}/fixtures",
            params={"date": today},
            headers=_headers(api_key),
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            return []
        fixtures = data.get("response", [])
        logger.info(f"Today's fixtures: {len(fixtures)} for {today}")
        return [_parse_fixture(f) for f in fixtures]
    except Exception as e:
        logger.warning(f"Today's fixtures fetch failed: {e}")
        return []


def _parse_fixture(f: dict) -> dict:
    """Parse API-Football fixture into internal format."""
    fixture  = f.get("fixture", {})
    teams    = f.get("teams", {})
    goals    = f.get("goals", {})
    league   = f.get("league", {})
    elapsed  = fixture.get("status", {}).get("elapsed")
    api_status = fixture.get("status", {}).get("short", "NS")
    return {
        "fixture_id":  fixture.get("id"),
        "external_id": str(fixture.get("id", "")),
        "home_team":   teams.get("home", {}).get("name", ""),
        "away_team":   teams.get("away", {}).get("name", ""),
        "home_score":  goals.get("home"),
        "away_score":  goals.get("away"),
        "status":      _map_status(api_status),
        "live_minute": elapsed,
        "clock_str":   f"{elapsed}'" if elapsed else api_status,
        "league_name": league.get("name", ""),
        "country":     league.get("country", ""),
        "match_date":  fixture.get("date", ""),
        "api_status":  api_status,
    }


def _map_status(api_status: str) -> str:
    live_statuses     = {"1H", "2H", "HT", "ET", "P", "BT", "LIVE", "INT"}
    finished_statuses = {"FT", "AET", "PEN"}
    if api_status in live_statuses:
        return "live"
    if api_status in finished_statuses:
        return "finished"
    return "scheduled"


# ── Main update function ───────────────────────────────────────────────────────

def _expire_stale_live_matches(db, active_external_ids: set) -> int:
    """
    Any DB match that is still marked 'live' but is NOT in the current
    ESPN live feed AND started more than 3 hours ago is almost certainly
    finished. Reset it to 'finished' so the live page stays accurate.
    """
    from data.db_models.models import Match
    cutoff = datetime.utcnow() - timedelta(hours=3)
    stale = db.query(Match).filter(
        Match.status == "live",
        Match.match_date <= cutoff,
    ).all()

    expired = 0
    for m in stale:
        if m.external_id not in active_external_ids:
            m.status = "finished"
            expired += 1

    if expired:
        try:
            db.commit()
            logger.info(f"[live-cleanup] Expired {expired} stale 'live' matches → 'finished'")
        except Exception as e:
            db.rollback()
            logger.warning(f"[live-cleanup] Commit failed: {e}")

    return expired


def update_live_scores(db, api_key: str = "") -> int:
    """
    Fetch live fixtures from ESPN (primary) and update match scores in DB.
    Falls back to API-Football only if ESPN returns nothing.
    Always expires stale 'live' rows regardless of whether ESPN has data.
    Returns number of matches updated.
    """
    from data.db_models.models import Match, Participant
    from sqlalchemy import func

    # Primary: ESPN — no auth, no quota
    fixtures = fetch_live_fixtures_espn()

    # Fallback: API-Football (only if ESPN has nothing AND we have a key)
    if not fixtures and api_key:
        logger.info("ESPN returned no live matches — trying API-Football fallback")
        fixtures = fetch_live_fixtures(api_key)

    # Always clean up stale live rows — even if ESPN returned 0 right now
    active_ids = {f.get("external_id", "") for f in fixtures}
    _expire_stale_live_matches(db, active_ids)

    if not fixtures:
        logger.info("No live fixtures from any source")
        return 0

    updated = 0
    for fix in fixtures:
        m = None

        # Match by external_id
        if fix.get("external_id"):
            m = db.query(Match).filter(Match.external_id == fix["external_id"]).first()

        # Fallback: fuzzy match by team name + today's date
        if not m and fix["home_team"] and fix["away_team"]:
            home = db.query(Participant).filter(
                func.lower(Participant.name).like(f"%{fix['home_team'].lower()[:12]}%")
            ).first()
            away = db.query(Participant).filter(
                func.lower(Participant.name).like(f"%{fix['away_team'].lower()[:12]}%")
            ).first()
            if home and away:
                today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                m = db.query(Match).filter(
                    Match.home_id == home.id,
                    Match.away_id == away.id,
                    Match.match_date >= today_start,
                ).first()

        if not m:
            continue

        changed = False

        if fix["home_score"] is not None and m.home_score != fix["home_score"]:
            m.home_score = fix["home_score"]
            changed = True
        if fix["away_score"] is not None and m.away_score != fix["away_score"]:
            m.away_score = fix["away_score"]
            changed = True
        if fix["status"] in ("live", "finished") and m.status != fix["status"]:
            m.status = fix["status"]
            changed = True

        # Store live_minute in extra_data
        if fix.get("live_minute") is not None:
            import json
            try:
                extra = json.loads(m.extra_data or "{}")
            except Exception:
                extra = {}
            extra["live_minute"] = fix["live_minute"]
            m.extra_data = json.dumps(extra)
            changed = True

        if changed:
            m.updated_at = datetime.utcnow()
            updated += 1

    if updated:
        try:
            db.commit()
            logger.info(f"Live scores: updated {updated} matches in DB")
        except Exception as e:
            db.rollback()
            logger.warning(f"Live scores commit failed: {e}")

    return updated


def sync_todays_results(db, api_key: str) -> int:
    """
    Fetch today's completed fixtures from API-Football and update results.
    Used alongside resolve_finished_matches job.
    """
    from data.db_models.models import Match

    fixtures = fetch_todays_fixtures(api_key)
    finished = [f for f in fixtures if f["status"] == "finished"]
    if not finished:
        return 0

    updated = 0
    for fix in finished:
        m = db.query(Match).filter(Match.external_id == fix["external_id"]).first()
        if not m or m.status == "finished":
            continue
        m.home_score = fix["home_score"]
        m.away_score = fix["away_score"]
        m.status     = "finished"
        hs = fix["home_score"] or 0
        as_ = fix["away_score"] or 0
        m.result     = "H" if hs > as_ else ("A" if hs < as_ else "D")
        m.updated_at = datetime.utcnow()
        updated += 1

    if updated:
        try:
            db.commit()
            logger.info(f"Today's results: {updated} matches resolved")
        except Exception as e:
            db.rollback()
            logger.warning(f"Results sync commit failed: {e}")

    return updated
