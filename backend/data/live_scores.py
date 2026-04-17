"""
Live scores — Sofascore as primary (all sports, ~20-30s delay).
ESPN as fallback per sport (~60-90s delay, no auth).
API-Football as last resort (100 req/day free tier).

Architecture:
  1. Sofascore fetches ALL sports in one parallel sweep — football, basketball,
     tennis, baseball, NFL, NHL, cricket, rugby, handball, volleyball.
  2. If Sofascore returns nothing (rare outage), ESPN covers all football leagues.
  3. If ESPN also fails, API-Football covers live football as a last resort.

The adaptive scheduler runs this every 60s during live matches, 5 min otherwise.
"""
from __future__ import annotations
import httpx
import concurrent.futures
try:
    from curl_cffi import requests as _cffi_requests
    _CFFI_AVAILABLE = True
except ImportError:
    _CFFI_AVAILABLE = False
from datetime import datetime, date, timedelta
from loguru import logger

# ── Sofascore constants ───────────────────────────────────────────────────────

_SS_BASE = "https://api.sofascore.com/api/v1"
_SS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.sofascore.com/",
}

# (sofascore_slug, internal_sport_key)
SOFASCORE_SPORTS = [
    ("football",          "football"),
    ("basketball",        "basketball"),
    ("tennis",            "tennis"),
    ("baseball",          "baseball"),
    ("american-football", "american_football"),
    ("ice-hockey",        "ice_hockey"),
    ("cricket",           "cricket"),
    ("rugby",             "rugby"),
    ("handball",          "handball"),
    ("volleyball",        "volleyball"),
]

# ── ESPN constants ────────────────────────────────────────────────────────────

_ESPN_BASE    = "https://site.api.espn.com/apis/site/v2/sports"
_ESPN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# ESPN leagues for football fallback — (espn_path, display_name, country)
ESPN_FOOTBALL_LEAGUES = [
    ("soccer/eng.1",            "Premier League",          "England"),
    ("soccer/eng.2",            "Championship",            "England"),
    ("soccer/esp.1",            "La Liga",                 "Spain"),
    ("soccer/ger.1",            "Bundesliga",              "Germany"),
    ("soccer/ita.1",            "Serie A",                 "Italy"),
    ("soccer/fra.1",            "Ligue 1",                 "France"),
    ("soccer/por.1",            "Primeira Liga",           "Portugal"),
    ("soccer/ned.1",            "Eredivisie",              "Netherlands"),
    ("soccer/tur.1",            "Süper Lig",               "Turkey"),
    ("soccer/sco.1",            "Scottish Premiership",    "Scotland"),
    ("soccer/bel.1",            "First Division A",        "Belgium"),
    ("soccer/usa.1",            "MLS",                     "USA"),
    ("soccer/mex.1",            "Liga MX",                 "Mexico"),
    ("soccer/bra.1",            "Brasileirão",             "Brazil"),
    ("soccer/arg.1",            "Liga Profesional",        "Argentina"),
    ("soccer/col.1",            "Liga BetPlay",            "Colombia"),
    ("soccer/sau.1",            "Saudi Pro League",        "Saudi Arabia"),
    ("soccer/jpn.1",            "J1 League",               "Japan"),
    ("soccer/uefa.champions",   "Champions League",        "Europe"),
    ("soccer/uefa.europa",      "Europa League",           "Europe"),
    ("soccer/uefa.europa.conf", "Conference League",       "Europe"),
    ("soccer/conmebol.libertadores", "Copa Libertadores",  "South America"),
]

# ESPN paths for non-football sports fallback
ESPN_OTHER_LEAGUES = [
    ("basketball/nba",       "NBA",        "basketball", "USA"),
    ("basketball/mens-college-basketball", "NCAA Basketball", "basketball", "USA"),
    ("basketball/wnba",      "WNBA",       "basketball", "USA"),
    ("basketball/nbl",       "NBL",        "basketball", "Australia"),
    ("baseball/mlb",         "MLB",        "baseball",   "USA"),
    ("football/nfl",         "NFL",        "american_football", "USA"),
    ("football/college-football", "NCAA Football", "american_football", "USA"),
    ("hockey/nhl",           "NHL",        "ice_hockey", "USA"),
]

# ── API-Football constants ────────────────────────────────────────────────────

_API_BASE      = "https://v3.football.api-sports.io"
_RAPIDAPI_BASE = "https://api-football-v1.p.rapidapi.com/v3"


# ── Sofascore parsers ─────────────────────────────────────────────────────────

def _parse_sofascore_event(e: dict, sport_key: str) -> dict:
    """Parse a Sofascore event into internal fixture format."""
    tournament = e.get("tournament", {})
    home       = e.get("homeTeam", {})
    away       = e.get("awayTeam", {})
    hs         = e.get("homeScore", {})
    as_        = e.get("awayScore", {})
    status     = e.get("status", {})
    time_data  = e.get("time", {})

    status_type = status.get("type", "")
    if status_type == "inprogress":
        status_str = "live"
    elif status_type in ("finished", "ended"):
        status_str = "finished"
    else:
        status_str = "scheduled"

    # Live minute: football uses played time; other sports use period/description
    live_min   = None
    clock_str  = status.get("description", "")
    if sport_key == "football" and status_str == "live":
        played = time_data.get("played")
        if played is not None:
            live_min  = int(played)
            clock_str = f"{live_min}'"
        if status.get("description", "").lower() in ("halftime", "ht"):
            live_min  = 45
            clock_str = "HT"

    home_score_raw = hs.get("current")
    away_score_raw = as_.get("current")

    # Sport-specific period scores
    extra: dict = {}
    if sport_key == "basketball":
        extra["period"]       = e.get("roundInfo", {}).get("round")
        extra["home_periods"] = [hs.get(f"period{i}") for i in range(1, 5) if hs.get(f"period{i}") is not None]
        extra["away_periods"] = [as_.get(f"period{i}") for i in range(1, 5) if as_.get(f"period{i}") is not None]
    elif sport_key == "tennis":
        extra["home_sets"] = [hs.get(f"period{i}") for i in range(1, 6) if hs.get(f"period{i}") is not None]
        extra["away_sets"] = [as_.get(f"period{i}") for i in range(1, 6) if as_.get(f"period{i}") is not None]
        clock_str = status.get("description", "")
    elif sport_key == "ice_hockey":
        extra["period"] = time_data.get("currentPeriod")

    return {
        "fixture_id":  e.get("id"),
        "external_id": f"ss_{e.get('id', '')}",
        "home_team":   home.get("name") or home.get("shortName", ""),
        "away_team":   away.get("name") or away.get("shortName", ""),
        "home_score":  int(home_score_raw) if home_score_raw is not None else None,
        "away_score":  int(away_score_raw) if away_score_raw is not None else None,
        "status":      status_str,
        "live_minute": live_min,
        "clock_str":   clock_str,
        "league_name": tournament.get("name", ""),
        "country":     (tournament.get("category") or {}).get("name", ""),
        "match_date":  e.get("startTimestamp", ""),
        "sport_key":   sport_key,
        "source":      "sofascore",
        "extra":       extra,
    }


def _fetch_sofascore_sport(ss_slug: str, sport_key: str, timeout: int = 10) -> list[dict]:
    """
    Fetch all live events for one sport from Sofascore.
    Uses curl_cffi (Chrome TLS fingerprint) to bypass Sofascore's bot detection.
    Falls back to httpx if curl_cffi is unavailable.
    """
    try:
        url = f"{_SS_BASE}/sport/{ss_slug}/events/live"
        if _CFFI_AVAILABLE:
            resp = _cffi_requests.get(
                url,
                impersonate="chrome124",
                headers={"Referer": "https://www.sofascore.com/", "Accept": "application/json"},
                timeout=timeout,
            )
        else:
            resp = httpx.get(url, headers=_SS_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return []
        events = resp.json().get("events", [])
        return [_parse_sofascore_event(e, sport_key) for e in events]
    except Exception:
        return []


def fetch_live_fixtures_sofascore() -> list[dict]:
    """
    Fetch ALL live matches across ALL supported sports from Sofascore in parallel.
    Returns a flat list of internal fixture dicts.
    """
    all_live: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SOFASCORE_SPORTS)) as pool:
        futures = {
            pool.submit(_fetch_sofascore_sport, ss_slug, sport_key): ss_slug
            for ss_slug, sport_key in SOFASCORE_SPORTS
        }
        for fut in concurrent.futures.as_completed(futures):
            try:
                results = fut.result()
                all_live.extend(results)
            except Exception:
                pass
    logger.info(f"Sofascore: {len(all_live)} live matches across all sports")
    return all_live


# ── ESPN parsers (football fallback) ─────────────────────────────────────────

def _parse_espn_event(e: dict, country: str, sport_key: str = "football") -> dict:
    """Parse a single ESPN scoreboard event into internal format."""
    comp        = e.get("competitions", [{}])[0]
    competitors = comp.get("competitors", [])
    status      = e.get("status", {})
    stype       = status.get("type", {})

    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})

    clock_str = status.get("displayClock", "")
    live_min  = None
    try:
        live_min = int(clock_str.replace("'", "").strip().split("+")[0])
    except (ValueError, IndexError):
        pass

    desc = stype.get("name", "")
    if desc == "STATUS_HALFTIME":
        status_str = "live"
        live_min   = 45
        clock_str  = "HT"
    elif stype.get("state") == "in":
        status_str = "live"
    elif stype.get("completed"):
        status_str = "finished"
    else:
        status_str = "scheduled"

    def _score(c: dict):
        raw = c.get("score", "")
        try:
            return int(raw) if raw not in (None, "", "--") else None
        except (ValueError, TypeError):
            return None

    return {
        "fixture_id":  e.get("id"),
        "external_id": f"espn_{e.get('id', '')}",
        "home_team":   (home.get("team") or {}).get("displayName") or "",
        "away_team":   (away.get("team") or {}).get("displayName") or "",
        "home_score":  _score(home),
        "away_score":  _score(away),
        "status":      status_str,
        "live_minute": live_min,
        "clock_str":   clock_str,
        "league_name": e.get("season", {}).get("slug", ""),
        "country":     country,
        "match_date":  comp.get("date", "") or e.get("date", ""),
        "sport_key":   sport_key,
        "source":      "espn",
        "extra":       {},
    }


def _fetch_espn_league(espn_path: str, country: str, sport_key: str = "football", timeout: int = 8) -> list[dict]:
    """Fetch scoreboard for one ESPN league. Returns live fixtures only."""
    try:
        resp = httpx.get(
            f"{_ESPN_BASE}/{espn_path}/scoreboard",
            headers=_ESPN_HEADERS,
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        events = resp.json().get("events", [])
        live   = []
        for e in events:
            stype = e.get("status", {}).get("type", {})
            state = stype.get("state", "")
            name  = stype.get("name", "")
            if state == "in" or name in (
                "STATUS_HALFTIME", "STATUS_IN_PROGRESS",
                "STATUS_SECOND_HALF", "STATUS_FIRST_HALF",
                "STATUS_OVERTIME", "STATUS_EXTRA_TIME", "STATUS_PENALTY",
            ):
                live.append(_parse_espn_event(e, country, sport_key))
        return live
    except Exception:
        return []


def fetch_live_fixtures_espn() -> list[dict]:
    """
    Fetch live football matches from all ESPN leagues (Sofascore fallback).
    Also fetches NBA, MLB, NFL, NHL as secondary sport coverage.
    """
    live: list[dict] = []

    # Football leagues
    football_tasks = [
        (path, country, "football")
        for path, _name, country in ESPN_FOOTBALL_LEAGUES
    ]
    # Other sports
    other_tasks = [
        (path, country, sport_key)
        for path, _name, sport_key, country in ESPN_OTHER_LEAGUES
    ]
    all_tasks = football_tasks + other_tasks

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futures = {
            pool.submit(_fetch_espn_league, path, country, sport_key): path
            for path, country, sport_key in all_tasks
        }
        for fut in concurrent.futures.as_completed(futures):
            try:
                live.extend(fut.result())
            except Exception:
                pass

    logger.info(f"ESPN fallback: {len(live)} live matches")
    return live


# ── API-Football fallback ─────────────────────────────────────────────────────

def _af_headers(api_key: str) -> dict:
    if len(api_key) > 40:
        return {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"}
    return {"x-apisports-key": api_key}


def _af_base(api_key: str) -> str:
    return _RAPIDAPI_BASE if len(api_key) > 40 else _API_BASE


def fetch_live_fixtures_api_football(api_key: str) -> list[dict]:
    """API-Football last-resort fallback — football only, 100 req/day free tier."""
    if not api_key:
        return []
    try:
        resp = httpx.get(
            f"{_af_base(api_key)}/fixtures",
            params={"live": "all"},
            headers=_af_headers(api_key),
            timeout=15,
        )
        resp.raise_for_status()
        data   = resp.json()
        errors = data.get("errors", {})
        if errors:
            return []
        return [_parse_af_fixture(f) for f in data.get("response", [])]
    except Exception as e:
        logger.warning(f"API-Football live fetch failed: {e}")
        return []


def _parse_af_fixture(f: dict) -> dict:
    fixture    = f.get("fixture", {})
    teams      = f.get("teams", {})
    goals      = f.get("goals", {})
    league     = f.get("league", {})
    elapsed    = fixture.get("status", {}).get("elapsed")
    api_status = fixture.get("status", {}).get("short", "NS")
    live_stats = {"1H", "2H", "HT", "ET", "P", "BT", "LIVE", "INT"}
    fin_stats  = {"FT", "AET", "PEN"}
    status_str = "live" if api_status in live_stats else ("finished" if api_status in fin_stats else "scheduled")
    return {
        "fixture_id":  fixture.get("id"),
        "external_id": str(fixture.get("id", "")),
        "home_team":   teams.get("home", {}).get("name", ""),
        "away_team":   teams.get("away", {}).get("name", ""),
        "home_score":  goals.get("home"),
        "away_score":  goals.get("away"),
        "status":      status_str,
        "live_minute": elapsed,
        "clock_str":   f"{elapsed}'" if elapsed else api_status,
        "league_name": league.get("name", ""),
        "country":     league.get("country", ""),
        "match_date":  fixture.get("date", ""),
        "sport_key":   "football",
        "source":      "api_football",
        "extra":       {},
    }


# ── Stale match cleanup ───────────────────────────────────────────────────────

def _expire_stale_live_matches(db, active_external_ids: set) -> int:
    """
    Reset any DB match still marked 'live' that's not in the current feed
    AND started more than 3 hours ago — it's almost certainly finished.
    """
    from data.db_models.models import Match
    cutoff = datetime.utcnow() - timedelta(hours=3)
    stale  = db.query(Match).filter(
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


# ── Shared live cache ─────────────────────────────────────────────────────────
#
# The scheduler populates this every 30 s. Both /matches/live/scores and the SSE
# stream read from here so the navbar count and Live page always agree.

import time as _time

_LIVE_CACHE: list[dict] = []
_LIVE_CACHE_TS: float   = 0.0

_SPORT_ICONS: dict[str, str] = {
    "football":          "⚽",
    "basketball":        "🏀",
    "tennis":            "🎾",
    "baseball":          "⚾",
    "american_football": "🏈",
    "ice_hockey":        "🏒",
    "cricket":           "🏏",
    "rugby":             "🏉",
    "handball":          "🤾",
    "volleyball":        "🏐",
}


def get_cached_live_fixtures() -> list[dict]:
    """
    Return the most recent live fixtures fetched by the scheduler.
    Falls back to a direct Sofascore fetch if cache is older than 90 s or empty.
    """
    global _LIVE_CACHE, _LIVE_CACHE_TS
    age = _time.time() - _LIVE_CACHE_TS
    if _LIVE_CACHE and age < 90:
        return list(_LIVE_CACHE)
    # Cache is cold or stale — do a fresh fetch
    try:
        fresh = fetch_live_fixtures_sofascore()
        if fresh:
            _LIVE_CACHE    = fresh
            _LIVE_CACHE_TS = _time.time()
            return list(_LIVE_CACHE)
    except Exception:
        pass
    return list(_LIVE_CACHE)  # return stale rather than nothing


def _enrich_fixture(f: dict) -> dict:
    """Add sport_icon and normalise competition field for frontend consumption."""
    sk = f.get("sport_key", "football")
    return {
        **f,
        "sport_icon":  _SPORT_ICONS.get(sk, "🏆"),
        "competition": f.get("competition") or f.get("league_name", ""),
    }


# ── Main update function ───────────────────────────────────────────────────────

def update_live_scores(db, api_key: str = "") -> int:
    """
    Fetch live matches from Sofascore (primary, all sports) → ESPN (fallback, multi-sport)
    → API-Football (last resort, football only).
    Updates match scores in DB. Returns number of matches updated.
    """
    from data.db_models.models import Match, Participant
    from sqlalchemy import func

    # ── 1. Sofascore — all sports, ~20-30s delay ──────────────────────
    fixtures = fetch_live_fixtures_sofascore()

    # ── 2. ESPN fallback — if Sofascore completely empty (rare outage) ─
    if not fixtures:
        logger.info("Sofascore returned nothing — falling back to ESPN")
        fixtures = fetch_live_fixtures_espn()

    # ── 3. API-Football last resort — football only ────────────────────
    if not fixtures and api_key:
        logger.info("ESPN also empty — last resort: API-Football")
        fixtures = fetch_live_fixtures_api_football(api_key)

    # ── Populate the shared live cache ─────────────────────────────────
    # Always update even if fixtures is empty — an empty list means nothing
    # is live right now, which is valid information.
    global _LIVE_CACHE, _LIVE_CACHE_TS
    _LIVE_CACHE    = [_enrich_fixture(f) for f in fixtures if f.get("status") == "live"]
    _LIVE_CACHE_TS = _time.time()

    # Always clean stale 'live' rows even if no live data right now
    active_ids = {f.get("external_id", "") for f in fixtures}
    _expire_stale_live_matches(db, active_ids)

    if not fixtures:
        logger.info("No live fixtures from any source")
        return 0

    updated = 0
    for fix in fixtures:
        m = None

        # Try exact external_id match first
        if fix.get("external_id"):
            m = db.query(Match).filter(Match.external_id == fix["external_id"]).first()

        # Fuzzy match: team names + today
        if not m and fix.get("home_team") and fix.get("away_team"):
            home_p = db.query(Participant).filter(
                func.lower(Participant.name).like(f"%{fix['home_team'].lower()[:12]}%")
            ).first()
            away_p = db.query(Participant).filter(
                func.lower(Participant.name).like(f"%{fix['away_team'].lower()[:12]}%")
            ).first()
            if home_p and away_p:
                today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                m = db.query(Match).filter(
                    Match.home_id   == home_p.id,
                    Match.away_id   == away_p.id,
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

        # Store live metadata in extra_data
        if fix.get("live_minute") is not None or fix.get("extra"):
            import json
            try:
                extra = json.loads(m.extra_data or "{}")
            except Exception:
                extra = {}
            if fix.get("live_minute") is not None:
                extra["live_minute"] = fix["live_minute"]
            if fix.get("clock_str"):
                extra["clock"] = fix["clock_str"]
            if fix.get("source"):
                extra["live_source"] = fix["source"]
            extra.update(fix.get("extra") or {})
            m.extra_data = json.dumps(extra)
            changed = True

        if changed:
            m.updated_at = datetime.utcnow()
            updated += 1

    if updated:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"Live scores commit failed: {e}")

    return updated


# ── Sofascore: scheduled events for any date (data ingestion) ─────────────────

def fetch_sofascore_events_for_date(ss_slug: str, sport_key: str, event_date: date) -> list[dict]:
    """
    Fetch all scheduled (including finished) events for a specific date.
    Used by the historical data ingestion job to populate the matches table.
    """
    try:
        date_str = event_date.strftime("%Y-%m-%d")
        resp = httpx.get(
            f"{_SS_BASE}/sport/{ss_slug}/scheduled-events/{date_str}",
            headers=_SS_HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        events = resp.json().get("events", [])
        return [_parse_sofascore_event(e, sport_key) for e in events]
    except Exception:
        return []


# ── Today's results (for resolve job) ────────────────────────────────────────

def fetch_todays_fixtures(api_key: str) -> list[dict]:
    """Fetch all fixtures for today from API-Football (resolve job)."""
    if not api_key:
        return []
    today = date.today().strftime("%Y-%m-%d")
    try:
        resp = httpx.get(
            f"{_af_base(api_key)}/fixtures",
            params={"date": today},
            headers=_af_headers(api_key),
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            return []
        return [_parse_af_fixture(f) for f in data.get("response", [])]
    except Exception as e:
        logger.warning(f"Today's fixtures fetch failed: {e}")
        return []


def sync_todays_results(db, api_key: str) -> int:
    """Fetch today's completed fixtures and update results in DB."""
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
        hs  = fix["home_score"] or 0
        as_ = fix["away_score"] or 0
        m.result     = "H" if hs > as_ else ("A" if hs < as_ else "D")
        m.updated_at = datetime.utcnow()
        updated += 1

    if updated:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"Results sync commit failed: {e}")

    return updated
