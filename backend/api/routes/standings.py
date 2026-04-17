"""
League standings — ESPN public API (current season) + API-Football (historical).

ESPN: no API key, no daily quota, updates within minutes of match completion.
API-Football: used only for past seasons, cached for 30 days (historical data never changes).
"""
from __future__ import annotations
import concurrent.futures
import httpx
from fastapi import APIRouter, Query, HTTPException

router = APIRouter(prefix="/standings", tags=["standings"])

_ESPN_V2_BASE   = "https://site.api.espn.com/apis/v2/sports"
_ESPN_SITE_BASE = "https://site.api.espn.com/apis/site/v2/sports"
# Legacy aliases kept for the soccer-only helpers below
_ESPN_V2   = f"{_ESPN_V2_BASE}/soccer"
_ESPN_SITE = f"{_ESPN_SITE_BASE}/soccer"
_AF_BASE   = "https://v3.football.api-sports.io"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/",
}

CURRENT_SEASON = 2025
AVAILABLE_SEASONS = list(range(CURRENT_SEASON, 2015, -1))  # [2025, 2024, ..., 2016]

# (slug, display_name, country, flag_emoji)
LEAGUES = [
    ("eng.1",            "Premier League",    "England",      "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    ("esp.1",            "La Liga",           "Spain",        "🇪🇸"),
    ("ger.1",            "Bundesliga",        "Germany",      "🇩🇪"),
    ("ita.1",            "Serie A",           "Italy",        "🇮🇹"),
    ("fra.1",            "Ligue 1",           "France",       "🇫🇷"),
    ("por.1",            "Primeira Liga",     "Portugal",     "🇵🇹"),
    ("ned.1",            "Eredivisie",        "Netherlands",  "🇳🇱"),
    ("tur.1",            "Süper Lig",         "Turkey",       "🇹🇷"),
    ("sco.1",            "Scottish Prem.",    "Scotland",     "🏴󠁧󠁢󠁳󠁣󠁴󠁿"),
    ("bel.1",            "Pro League",        "Belgium",      "🇧🇪"),
    ("usa.1",            "MLS",               "USA",          "🇺🇸"),
    ("bra.1",            "Brasileirão",       "Brazil",       "🇧🇷"),
    ("arg.1",            "Liga Profesional",  "Argentina",    "🇦🇷"),
    ("col.1",            "Liga BetPlay",      "Colombia",     "🇨🇴"),
    ("uefa.champions",   "Champions League",  "Europe",       "⭐"),
    ("uefa.europa",      "Europa League",     "Europe",       "🟠"),
    ("uefa.europa.conf", "Conference League", "Europe",       "🔵"),
]

_SLUG_META = {s: {"name": n, "country": c, "flag": f} for s, n, c, f in LEAGUES}

# Additional slugs for multi-sport ESPN support
_SLUG_META.update({
    "basketball/nba":                      {"name": "NBA",                "country": "USA",       "flag": "🇺🇸"},
    "basketball/wnba":                     {"name": "WNBA",               "country": "USA",       "flag": "🇺🇸"},
    "basketball/mens-college-basketball":  {"name": "NCAA Basketball",    "country": "USA",       "flag": "🇺🇸"},
    "football/nfl":                        {"name": "NFL",                "country": "USA",       "flag": "🇺🇸"},
    "football/college-football":           {"name": "NCAA Football",      "country": "USA",       "flag": "🇺🇸"},
    "hockey/nhl":                          {"name": "NHL",                "country": "USA/Canada","flag": "🏒"},
    "hockey/ahl":                          {"name": "AHL",                "country": "USA/Canada","flag": "🏒"},
    "baseball/mlb":                        {"name": "MLB",                "country": "USA",       "flag": "🇺🇸"},
    "tennis/atp":                          {"name": "ATP Tour",           "country": "World",     "flag": "🎾"},
    "tennis/wta":                          {"name": "WTA Tour",           "country": "World",     "flag": "🎾"},
    "rugby/premiership":                   {"name": "Premiership",        "country": "England",   "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿"},
    "rugby/top14":                         {"name": "Top 14",             "country": "France",    "flag": "🇫🇷"},
    "rugby/super-rugby":                   {"name": "Super Rugby Pacific","country": "Pacific",   "flag": "🌏"},
    "rugby/six-nations":                   {"name": "Six Nations",        "country": "Europe",    "flag": "🇪🇺"},
    "rugby/rugby-championship":            {"name": "Rugby Championship", "country": "World",     "flag": "🌍"},
    "cricket/ipl":                         {"name": "IPL",                "country": "India",     "flag": "🇮🇳"},
    "cricket/bbl":                         {"name": "BBL",                "country": "Australia", "flag": "🇦🇺"},
    "cricket/cpl":                         {"name": "CPL",                "country": "Caribbean", "flag": "🌎"},
    "handball/ehf-champions-league":       {"name": "EHF Champions League","country": "Europe",   "flag": "🇪🇺"},
    "handball/dkb-handball-bundesliga":    {"name": "Handball Bundesliga","country": "Germany",   "flag": "🇩🇪"},
    "volleyball/ncaa-volleyball":          {"name": "NCAA Volleyball",    "country": "USA",       "flag": "🇺🇸"},
    "mma/ufc":                             {"name": "UFC",                "country": "World",     "flag": "🥊"},
})

# ESPN slug → API-Football league ID
LEAGUE_API_IDS: dict[str, int] = {
    "eng.1":            39,
    "esp.1":            140,
    "ger.1":            78,
    "ita.1":            135,
    "fra.1":            61,
    "por.1":            94,
    "ned.1":            88,
    "tur.1":            203,
    "sco.1":            179,
    "bel.1":            144,
    "usa.1":            253,
    "bra.1":            71,
    "arg.1":            128,
    "col.1":            239,
    "uefa.champions":   2,
    "uefa.europa":      3,
    "uefa.europa.conf": 848,
}

# Sentinel season for news (no season concept — news is always current)
_NEWS_SEASON = 0


# ── DB helpers — permanent storage for all data ───────────────────────────────

async def _db_get(
    league_slug: str, season: int, data_type: str,
    max_age_s: int | None = None,
) -> dict | None:
    """
    Return cached JSON payload from DB, or None when:
      - no row found, OR
      - max_age_s is set and the row is older than max_age_s seconds.

    max_age_s=None  → accept any age (historical data never changes).
    max_age_s=N     → return None when data is stale (current season live data).
    """
    import json as _json
    from datetime import datetime as _dt
    from data.database import AsyncSessionLocal
    from data.db_models.models import LeagueSeasonCache
    from sqlalchemy import select
    try:
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(LeagueSeasonCache).where(
                    LeagueSeasonCache.league_slug == league_slug,
                    LeagueSeasonCache.season      == season,
                    LeagueSeasonCache.data_type   == data_type,
                )
            )
            rec = row.scalar_one_or_none()
            if rec:
                if max_age_s is not None:
                    age = (_dt.utcnow() - rec.fetched_at).total_seconds()
                    if age > max_age_s:
                        return None  # stale — caller will re-fetch
                return _json.loads(rec.json_data)
    except Exception:
        pass
    return None


async def _db_put(league_slug: str, season: int, data_type: str, payload: dict) -> None:
    """Async upsert — used by FastAPI routes (async context)."""
    import json as _json
    from data.database import AsyncSessionLocal
    from data.db_models.models import LeagueSeasonCache
    from sqlalchemy import select
    from datetime import datetime as _dt
    try:
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(LeagueSeasonCache).where(
                    LeagueSeasonCache.league_slug == league_slug,
                    LeagueSeasonCache.season      == season,
                    LeagueSeasonCache.data_type   == data_type,
                )
            )
            rec = row.scalar_one_or_none()
            if rec:
                rec.json_data  = _json.dumps(payload)
                rec.fetched_at = _dt.utcnow()
            else:
                db.add(LeagueSeasonCache(
                    league_slug = league_slug,
                    season      = season,
                    data_type   = data_type,
                    json_data   = _json.dumps(payload),
                ))
            await db.commit()
    except Exception:
        pass


def _db_put_sync(league_slug: str, season: int, data_type: str, payload: dict) -> None:
    """Sync upsert — used by the BackgroundScheduler (runs in a thread, not async)."""
    import json as _json
    from data.database import get_sync_session
    from data.db_models.models import LeagueSeasonCache
    from datetime import datetime as _dt
    try:
        with get_sync_session() as db:
            rec = db.query(LeagueSeasonCache).filter_by(
                league_slug=league_slug, season=season, data_type=data_type
            ).first()
            if rec:
                rec.json_data  = _json.dumps(payload)
                rec.fetched_at = _dt.utcnow()
            else:
                db.add(LeagueSeasonCache(
                    league_slug = league_slug,
                    season      = season,
                    data_type   = data_type,
                    json_data   = _json.dumps(payload),
                ))
            db.commit()
    except Exception:
        pass


# ── ESPN parsers ──────────────────────────────────────────────────────────────

def _stat(stats: list[dict], *names: str) -> float:
    for name in names:
        for s in stats:
            if s.get("name") == name or s.get("shortDisplayName") == name:
                try:
                    return float(s.get("value") or 0)
                except (TypeError, ValueError):
                    pass
    return 0.0


def _parse_entries(entries: list[dict], group_name: str = "") -> list[dict]:
    rows = []
    for i, entry in enumerate(entries):
        team  = entry.get("team", {})
        stats = entry.get("stats", [])

        logos = team.get("logos", [])
        logo  = logos[0].get("href", "") if logos else team.get("logo", "")

        rank   = int(_stat(stats, "rank") or (i + 1))
        played = int(_stat(stats, "gamesPlayed", "played", "GP"))
        wins   = int(_stat(stats, "wins", "w", "W"))
        draws  = int(_stat(stats, "ties", "draws", "D", "d"))
        losses = int(_stat(stats, "losses", "l", "L"))
        gf     = int(_stat(stats, "pointsFor", "goalsFor", "GF"))
        ga     = int(_stat(stats, "pointsAgainst", "goalsAgainst", "GA"))
        gd     = int(_stat(stats, "pointDifferential", "goalDifference", "GD"))
        pts    = int(_stat(stats, "points", "pts", "PTS", "Pts"))

        rows.append({
            "rank":          rank,
            "team_id":       str(team.get("id") or ""),
            "team_name":     team.get("displayName") or team.get("name", ""),
            "team_short":    team.get("shortDisplayName") or team.get("abbreviation", ""),
            "team_logo":     logo,
            "points":        pts,
            "played":        played,
            "win":           wins,
            "draw":          draws,
            "lose":          losses,
            "goals_for":     gf,
            "goals_against": ga,
            "goal_diff":     gd,
            "form":          [],
            "description":   None,
            "group":         group_name,
        })

    rows.sort(key=lambda r: r["rank"])
    return rows


def _extract_groups(data: dict) -> list[list[dict]]:
    groups: list[list[dict]] = []

    # Shape A: data.children[].standings.entries
    for child in data.get("children", []):
        name    = child.get("name") or child.get("abbreviation") or ""
        entries = child.get("standings", {}).get("entries", [])
        if entries:
            rows = _parse_entries(entries, name)
            if rows:
                groups.append(rows)
    if groups:
        return groups

    # Shape B: data.standings.entries
    entries = data.get("standings", {}).get("entries", [])
    if entries:
        rows = _parse_entries(entries)
        if rows:
            return [rows]

    # Shape C: data.groups[].standings.entries
    for g in data.get("groups", []):
        name    = g.get("name") or g.get("shortName") or ""
        entries = g.get("standings", {}).get("entries", [])
        if entries:
            rows = _parse_entries(entries, name)
            if rows:
                groups.append(rows)

    return groups


def _fetch_espn(slug: str, season: int = CURRENT_SEASON) -> dict | None:
    meta   = _SLUG_META.get(slug, {})
    params = {"season": season} if season != CURRENT_SEASON else {}

    # Slug may be "eng.1" (soccer) or "basketball/nba", "hockey/nhl", etc.
    # For soccer slugs (no "/" prefix with a sport), use the soccer base URLs.
    # For multi-sport slugs like "basketball/nba", build the URL directly.
    if "/" in slug:
        # e.g. "basketball/nba" → https://site.api.espn.com/apis/v2/sports/basketball/nba/standings
        bases = [
            f"{_ESPN_V2_BASE}/{slug}/standings",
            f"{_ESPN_SITE_BASE}/{slug}/standings",
        ]
    else:
        bases = [
            f"{_ESPN_V2}/{slug}/standings",
            f"{_ESPN_SITE}/{slug}/standings",
        ]

    for url in bases:
        try:
            resp = httpx.get(url, params=params, headers=_BROWSER_HEADERS, timeout=12)
            if resp.status_code != 200:
                continue
            data   = resp.json()
            groups = _extract_groups(data)
            if not groups:
                continue
            return {
                "slug":        slug,
                "league_name": meta.get("name", slug),
                "country":     meta.get("country", ""),
                "flag":        meta.get("flag", ""),
                "season":      season,
                "groups":      groups,
                "source":      "espn",
                "cached":      False,
                "stale":       False,
            }
        except Exception:
            continue
    return None


# ── API-Football parser ───────────────────────────────────────────────────────

def _fetch_api_football(slug: str, season: int, api_key: str) -> dict | None:
    league_id = LEAGUE_API_IDS.get(slug)
    if not league_id or not api_key:
        return None

    meta = _SLUG_META.get(slug, {})

    try:
        resp = httpx.get(
            f"{_AF_BASE}/standings",
            params={"league": league_id, "season": season},
            headers={"x-apisports-key": api_key, "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        response_list = data.get("response", [])
        if not response_list:
            return None

        groups_dict: dict[str, list[dict]] = {}
        for item in response_list:
            league_info   = item.get("league", {})
            standings_arr = league_info.get("standings", [])
            for group_rows in standings_arr:
                if not group_rows:
                    continue
                group_name = group_rows[0].get("group", "")
                rows = []
                for row in group_rows:
                    team      = row.get("team", {})
                    all_stats = row.get("all", {})
                    goals     = all_stats.get("goals", {})
                    desc      = (row.get("description") or "").lower()
                    rows.append({
                        "rank":          row.get("rank", 0),
                        "team_name":     team.get("name", ""),
                        "team_short":    team.get("name", "")[:3].upper(),
                        "team_logo":     team.get("logo", ""),
                        "points":        row.get("points", 0),
                        "played":        all_stats.get("played", 0),
                        "win":           all_stats.get("win", 0),
                        "draw":          all_stats.get("draw", 0),
                        "lose":          all_stats.get("lose", 0),
                        "goals_for":     goals.get("for", 0),
                        "goals_against": goals.get("against", 0),
                        "goal_diff":     row.get("goalsDiff", 0),
                        "form":          list(row.get("form", "") or ""),
                        "description":   desc,
                        "group":         group_name,
                    })
                rows.sort(key=lambda r: r["rank"])
                if rows:
                    key = group_name or f"group_{len(groups_dict)}"
                    groups_dict[key] = rows

        if not groups_dict:
            return None

        return {
            "slug":        slug,
            "league_name": meta.get("name", slug),
            "country":     meta.get("country", ""),
            "flag":        meta.get("flag", ""),
            "season":      season,
            "groups":      list(groups_dict.values()),
            "source":      "api-football",
            "cached":      False,
            "stale":       False,
        }
    except Exception:
        return None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
async def get_standings(
    slug:   str = Query("eng.1"),
    season: int = Query(CURRENT_SEASON),
):
    """
    Standings for any season.
    Historical (non-current): DB-first — fetch from ESPN once, store permanently.
    Current season: in-memory cache, refreshed every 5 minutes.
    """
    if slug not in _SLUG_META:
        raise HTTPException(400, f"Unknown league: '{slug}'. Check /standings/leagues.")

    import asyncio
    from functools import partial

    is_current = season == CURRENT_SEASON

    # ── Historical: permanent DB storage ────────────────────────────
    if not is_current:
        stored = await _db_get(slug, season, "standings")
        if stored:
            return {**stored, "source": "db"}

        # Not in DB yet — fetch from ESPN and persist
        result = await asyncio.get_event_loop().run_in_executor(
            None, partial(_fetch_espn, slug, season)
        )
        if result:
            await _db_put(slug, season, "standings", result)
            return {**result, "source": "espn_saved"}

        raise HTTPException(503, f"Could not fetch {season} standings for {slug}.")

    # ── Current season: DB only (scheduler keeps it fresh every 5 min) ──
    stored = await _db_get(slug, CURRENT_SEASON, "standings")
    if stored:
        return stored

    # DB empty — scheduler hasn't warmed up yet (first startup).
    # Do a one-time direct fetch so the user isn't left with an error.
    result = await asyncio.get_event_loop().run_in_executor(None, partial(_fetch_espn, slug, season))
    if result:
        await _db_put(slug, CURRENT_SEASON, "standings", result)
        return result

    raise HTTPException(503, f"Could not fetch standings for {slug}.")


# ── Scoreboard / Fixtures ─────────────────────────────────────────────────────

def _parse_scoreboard_event(e: dict, slug: str) -> dict:
    """Parse a single ESPN scoreboard event into a fixture dict."""
    comp        = (e.get("competitions") or [{}])[0]
    competitors = comp.get("competitors", [])
    status      = e.get("status", {})
    stype       = status.get("type", {})
    clock       = status.get("displayClock", "")

    home = next((c for c in competitors if c.get("homeAway") == "home"),
                competitors[0] if competitors else {})
    away = next((c for c in competitors if c.get("homeAway") == "away"),
                competitors[1] if len(competitors) > 1 else {})

    def _team(c: dict) -> dict:
        t    = c.get("team") or {}
        tid  = str(t.get("id") or "")
        logos = t.get("logos") or []
        logo  = (logos[0].get("href") or "") if logos else (
            f"https://a.espncdn.com/i/teamlogos/soccer/500/{tid}.png" if tid else ""
        )
        score_raw = c.get("score")
        score = None
        if isinstance(score_raw, dict):
            sv = score_raw.get("displayValue") or score_raw.get("value")
            if sv not in (None, "", "--"):
                try:    score = int(sv)
                except: score = sv
        elif score_raw not in (None, "", "--"):
            try:    score = int(score_raw)
            except: score = str(score_raw)
        return {
            "id":    tid,
            "name":  t.get("displayName") or t.get("name") or "",
            "short": t.get("shortDisplayName") or t.get("abbreviation") or "",
            "logo":  logo,
            "score": score,
        }

    completed = stype.get("completed", False)
    state     = stype.get("state", "")
    sname     = stype.get("name", "")

    if completed:
        status_str = "finished"
    elif state == "in" or sname in ("STATUS_HALFTIME", "STATUS_IN_PROGRESS",
                                     "STATUS_SECOND_HALF", "STATUS_FIRST_HALF",
                                     "STATUS_OVERTIME", "STATUS_EXTRA_TIME"):
        status_str = "live"
    else:
        status_str = "scheduled"

    live_min = None
    if status_str == "live":
        try:
            live_min = int(clock.replace("'", "").strip().split("+")[0])
        except Exception:
            pass
    if sname == "STATUS_HALFTIME":
        live_min = 45

    return {
        "id":          str(e.get("id") or ""),
        "date":        (comp.get("date") or e.get("date") or "")[:16],
        "status":      status_str,
        "live_minute": live_min,
        "home":        _team(home) if home else {"id": "", "name": "TBD", "short": "TBD", "logo": "", "score": None},
        "away":        _team(away) if away else {"id": "", "name": "TBD", "short": "TBD", "logo": "", "score": None},
        "venue":       (comp.get("venue") or {}).get("fullName") or "",
        "league_slug": slug,
    }


def _fetch_league_fixtures(slug: str, season: int = CURRENT_SEASON,
                           days_back: int = 4, days_ahead: int = 14) -> dict:
    """
    Current season: parallel per-date ESPN calls (exact live state).
    Historical season: single ESPN scoreboard call with full-season date range
    (ESPN returns up to 500 events per call — enough for any full season).
    """
    from datetime import datetime, timedelta

    if season != CURRENT_SEASON:
        # Full historical season in one call
        # European seasons run Aug–Jun; use Jul 1 → Jun 30 to be safe
        from_date = f"{season}0701"
        to_date   = f"{season + 1}0630"
        try:
            resp = httpx.get(
                f"{_ESPN_SITE}/{slug}/scoreboard",
                params={"dates": f"{from_date}-{to_date}", "limit": 500},
                headers=_BROWSER_HEADERS,
                timeout=20,
            )
            events = resp.json().get("events", []) if resp.status_code == 200 else []
        except Exception:
            events = []
        fixtures = [_parse_scoreboard_event(e, slug) for e in events]
        fixtures.sort(key=lambda x: x["date"])
        return {"fixtures": fixtures, "slug": slug, "total": len(fixtures), "season": season}

    # Current season — parallel per-date fetch (preserves live state)
    today = datetime.utcnow().date()
    dates = (
        [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(days_back, 0, -1)]
        + [(today + timedelta(days=i)).strftime("%Y%m%d") for i in range(0, days_ahead + 1)]
    )

    def _fetch_one(date_str: str) -> list[dict]:
        try:
            resp = httpx.get(
                f"{_ESPN_SITE}/{slug}/scoreboard",
                params={"dates": date_str},
                headers=_BROWSER_HEADERS,
                timeout=8,
            )
            if resp.status_code == 200:
                return [_parse_scoreboard_event(e, slug) for e in resp.json().get("events", [])]
        except Exception:
            pass
        return []

    all_fixtures: list[dict] = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            for results in pool.map(_fetch_one, dates, timeout=20):
                all_fixtures.extend(results)
    except Exception:
        pass

    seen: set = set()
    unique: list[dict] = []
    for f in all_fixtures:
        if f["id"] and f["id"] not in seen:
            seen.add(f["id"])
            unique.append(f)

    unique.sort(key=lambda x: x["date"])
    return {"fixtures": unique, "slug": slug, "total": len(unique), "season": season}


@router.get("/fixtures")
async def get_league_fixtures(
    slug:   str = Query("eng.1"),
    season: int = Query(CURRENT_SEASON),
):
    """
    Fixtures for any season.
    Historical: DB-first, all 380 matches stored permanently after first fetch.
    Current: in-memory 2-min cache (live scores change frequently).
    """
    import asyncio
    from functools import partial
    if slug not in _SLUG_META:
        raise HTTPException(400, f"Unknown league: '{slug}'")

    is_historical = season != CURRENT_SEASON

    # ── Historical: permanent DB storage ────────────────────────────
    if is_historical:
        stored = await _db_get(slug, season, "fixtures")
        if stored:
            return {**stored, "source": "db"}

        result = await asyncio.get_event_loop().run_in_executor(
            None, partial(_fetch_league_fixtures, slug, season)
        )
        await _db_put(slug, season, "fixtures", result)
        return {**result, "source": "espn_saved"}

    # ── Current season: DB only (scheduler keeps it fresh every 5 min) ──
    stored = await _db_get(slug, CURRENT_SEASON, "fixtures")
    if stored:
        return stored

    # Warmup fallback — first startup before scheduler has run
    result = await asyncio.get_event_loop().run_in_executor(
        None, partial(_fetch_league_fixtures, slug, season)
    )
    await _db_put(slug, CURRENT_SEASON, "fixtures", result)
    return result


# ── League News ───────────────────────────────────────────────────────────────

def _fetch_league_news(slug: str) -> list[dict]:
    try:
        resp = httpx.get(
            f"{_ESPN_SITE}/{slug}/news",
            headers=_BROWSER_HEADERS,
            timeout=12,
        )
        if resp.status_code != 200:
            return []
        out = []
        for a in resp.json().get("articles", [])[:20]:
            images = a.get("images", [])
            img    = images[0].get("url", "") if images else ""
            out.append({
                "id":          str(a.get("dataSourceIdentifier") or a.get("id") or ""),
                "headline":    a.get("headline") or "",
                "description": a.get("description") or "",
                "published":   a.get("published") or "",
                "image":       img,
                "url":         (a.get("links") or {}).get("web", {}).get("href") or "",
            })
        return out
    except Exception:
        return []


@router.get("/news")
async def get_league_news(slug: str = Query("eng.1")):
    """Latest ESPN news articles for a league."""
    import asyncio
    if slug not in _SLUG_META:
        raise HTTPException(400, f"Unknown league: '{slug}'")

    # News has no season concept — use _NEWS_SEASON=0 as sentinel key.
    # Scheduler refreshes every 30 min; route reads DB only.
    stored = await _db_get(slug, _NEWS_SEASON, "news")
    if stored:
        return stored

    # Warmup fallback
    articles = await asyncio.get_event_loop().run_in_executor(None, _fetch_league_news, slug)
    payload = {"articles": articles}
    await _db_put(slug, _NEWS_SEASON, "news", payload)
    return payload


# ── League Leaders (top scorers / stats) ──────────────────────────────────────

def _fetch_league_leaders(slug: str, season: int = CURRENT_SEASON) -> list[dict]:
    """
    Fetch top statistical leaders (Goals, Assists) from ESPN's /statistics endpoint.
    Supports historical seasons via ?season=YYYY parameter.
    """
    try:
        params = {"season": season} if season != CURRENT_SEASON else {}
        resp = httpx.get(
            f"{_ESPN_SITE}/{slug}/statistics",
            params=params,
            headers=_BROWSER_HEADERS,
            timeout=12,
        )
        if resp.status_code != 200:
            return []

        categories: list[dict] = []
        for cat in resp.json().get("stats", []):
            name  = cat.get("displayName") or cat.get("name") or ""
            abbr  = cat.get("shortDisplayName") or cat.get("abbreviation") or ""
            entries: list[dict] = []
            for l in cat.get("leaders", [])[:10]:
                athlete = l.get("athlete") or {}
                team    = athlete.get("team") or {}
                pid     = str(athlete.get("id") or "")
                tid     = str(team.get("id")    or "")
                entries.append({
                    "rank":        len(entries) + 1,
                    "value":       l.get("value") or 0,
                    "display":     str(int(l.get("value") or 0)) if l.get("value") is not None else l.get("displayValue") or "0",
                    "player_id":   pid,
                    "name":        athlete.get("displayName") or athlete.get("shortName") or "",
                    "headshot":    f"https://a.espncdn.com/i/headshots/soccer/players/full/{pid}.png" if pid else "",
                    "team_id":     tid,
                    "team_name":   team.get("displayName") or team.get("name") or team.get("shortDisplayName") or "",
                    "team_logo":   f"https://a.espncdn.com/i/teamlogos/soccer/500/{tid}.png" if tid else "",
                    "league_slug": slug,
                })
            if entries:
                categories.append({"name": name, "abbr": abbr, "leaders": entries})
        return categories
    except Exception:
        return []


@router.get("/leaders")
async def get_league_leaders(
    slug:   str = Query("eng.1"),
    season: int = Query(CURRENT_SEASON),
):
    """
    Top statistical leaders for any season.
    Historical: DB-first, stored permanently after first fetch.
    Current: in-memory 30-min cache.
    """
    import asyncio
    from functools import partial
    if slug not in _SLUG_META:
        raise HTTPException(400, f"Unknown league: '{slug}'")

    is_historical = season != CURRENT_SEASON

    # ── Historical: permanent DB storage ────────────────────────────
    if is_historical:
        stored = await _db_get(slug, season, "leaders")
        if stored:
            return {**stored, "source": "db"}

        result = await asyncio.get_event_loop().run_in_executor(
            None, partial(_fetch_league_leaders, slug, season)
        )
        payload = {"categories": result}
        await _db_put(slug, season, "leaders", payload)
        return {**payload, "source": "espn_saved"}

    # ── Current season: DB only (scheduler refreshes every 30 min) ──
    stored = await _db_get(slug, CURRENT_SEASON, "leaders")
    if stored:
        return stored

    # Warmup fallback
    result = await asyncio.get_event_loop().run_in_executor(
        None, partial(_fetch_league_leaders, slug, season)
    )
    payload = {"categories": result}
    await _db_put(slug, CURRENT_SEASON, "leaders", payload)
    return payload


@router.get("/leagues")
async def list_leagues():
    return {
        "leagues": [
            {"slug": slug, "name": name, "country": country, "flag": flag}
            for slug, name, country, flag in LEAGUES
        ],
        "current_season": CURRENT_SEASON,
        "available_seasons": AVAILABLE_SEASONS,
    }
