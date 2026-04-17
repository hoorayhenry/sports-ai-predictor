"""
League standings — ESPN public API (current season) + API-Football (historical).

ESPN: no API key, no daily quota, updates within minutes of match completion.
API-Football: used only for past seasons, cached for 30 days (historical data never changes).
"""
from __future__ import annotations
import time
import concurrent.futures
import httpx
from fastapi import APIRouter, Query, HTTPException

router = APIRouter(prefix="/standings", tags=["standings"])

_ESPN_V2   = "https://site.api.espn.com/apis/v2/sports/soccer"
_ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
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

# In-memory caches
_ESPN_CACHE:     dict[str, dict] = {}    # slug → {data, ts}
_AF_CACHE:       dict[str, dict] = {}    # "slug:season" → {data, ts}
_FIXTURES_CACHE: dict[str, dict] = {}    # "fixtures:{slug}" → {data, ts}
_NEWS_CACHE:     dict[str, dict] = {}    # "news:{slug}" → {data, ts}
_LEADERS_CACHE:  dict[str, dict] = {}    # "leaders:{slug}" → {data, ts}
_ESPN_TTL     = 300             # 5 minutes — real-time
_AF_TTL       = 30 * 24 * 3600  # 30 days — historical data never changes
_FIXTURES_TTL = 120             # 2 minutes — fixtures update on match days
_NEWS_TTL     = 600             # 10 minutes
_LEADERS_TTL  = 1800            # 30 minutes — stats don't change that fast


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
    for base in (_ESPN_V2, _ESPN_SITE):
        try:
            resp = httpx.get(
                f"{base}/{slug}/standings",
                params=params,
                headers=_BROWSER_HEADERS,
                timeout=12,
            )
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
    Get league standings for any season.
    Primary source: ESPN (free, no key, supports all seasons back to ~2010).
    Fallback:       API-Football (only if ESPN returns empty AND key is available).
    """
    if slug not in _SLUG_META:
        raise HTTPException(400, f"Unknown league: '{slug}'. Check /standings/leagues.")

    import asyncio
    from functools import partial

    is_current   = season == CURRENT_SEASON
    espn_ttl     = _ESPN_TTL if is_current else _AF_TTL   # historical data never changes
    cache_key    = f"{slug}:{season}"

    # ── ESPN (works for ALL seasons — current and historical) ─────
    espn_cached = _ESPN_CACHE.get(cache_key)
    if espn_cached and (time.time() - espn_cached["ts"]) < espn_ttl:
        r = dict(espn_cached["data"])
        r["cached"] = True
        return r

    result = await asyncio.get_event_loop().run_in_executor(
        None, partial(_fetch_espn, slug, season)
    )

    if result:
        _ESPN_CACHE[cache_key] = {"data": result, "ts": time.time()}
        return result

    # ── Stale ESPN cache is better than nothing ───────────────────
    if espn_cached:
        r = dict(espn_cached["data"])
        r["cached"] = True
        r["stale"]  = True
        return r

    # ── Optional API-Football fallback (historical only) ──────────
    if not is_current:
        try:
            from config.settings import get_settings
            settings = get_settings()
            if settings.api_football_key:
                af_cached = _AF_CACHE.get(cache_key)
                if af_cached and (time.time() - af_cached["ts"]) < _AF_TTL:
                    r = dict(af_cached["data"])
                    r["cached"] = True
                    return r

                af_result = await asyncio.get_event_loop().run_in_executor(
                    None, partial(_fetch_api_football, slug, season, settings.api_football_key)
                )
                if af_result:
                    _AF_CACHE[cache_key] = {"data": af_result, "ts": time.time()}
                    return af_result
        except Exception:
            pass

    raise HTTPException(503, f"Could not fetch {season} standings for {slug}. Please try again.")


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


def _fetch_league_fixtures(slug: str, days_back: int = 4, days_ahead: int = 14) -> dict:
    """
    Fetch recent + upcoming fixtures by querying ESPN scoreboard in parallel
    for each date in the range. More reliable than a single range call.
    """
    from datetime import datetime, timedelta

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
        pass  # partial results are better than nothing

    # Deduplicate by ESPN event ID, then sort chronologically
    seen: set = set()
    unique: list[dict] = []
    for f in all_fixtures:
        if f["id"] and f["id"] not in seen:
            seen.add(f["id"])
            unique.append(f)

    unique.sort(key=lambda x: x["date"])
    return {"fixtures": unique, "slug": slug, "total": len(unique)}


@router.get("/fixtures")
async def get_league_fixtures(slug: str = Query("eng.1")):
    """League fixtures (recent results + upcoming) from ESPN scoreboard."""
    import asyncio
    if slug not in _SLUG_META:
        raise HTTPException(400, f"Unknown league: '{slug}'")

    cache_key = f"fixtures:{slug}"
    cached    = _FIXTURES_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _FIXTURES_TTL:
        return {**cached["data"], "cached": True}

    result = await asyncio.get_event_loop().run_in_executor(
        None, _fetch_league_fixtures, slug
    )
    _FIXTURES_CACHE[cache_key] = {"data": result, "ts": time.time()}
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

    cache_key = f"news:{slug}"
    cached    = _NEWS_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _NEWS_TTL:
        return {"articles": cached["data"], "cached": True}

    result = await asyncio.get_event_loop().run_in_executor(None, _fetch_league_news, slug)
    _NEWS_CACHE[cache_key] = {"data": result, "ts": time.time()}
    return {"articles": result}


# ── League Leaders (top scorers / stats) ──────────────────────────────────────

def _fetch_league_leaders(slug: str) -> list[dict]:
    """
    Fetch top statistical leaders (Goals, Assists) from ESPN's /statistics endpoint.
    Confirmed working: returns full inline athlete objects, no $ref resolution needed.
    """
    try:
        resp = httpx.get(
            f"{_ESPN_SITE}/{slug}/statistics",
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
async def get_league_leaders(slug: str = Query("eng.1")):
    """Top statistical leaders (scorers, assists, etc.) for a league from ESPN."""
    import asyncio
    if slug not in _SLUG_META:
        raise HTTPException(400, f"Unknown league: '{slug}'")

    cache_key = f"leaders:{slug}"
    cached    = _LEADERS_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _LEADERS_TTL:
        return {"categories": cached["data"], "cached": True}

    result = await asyncio.get_event_loop().run_in_executor(None, _fetch_league_leaders, slug)
    _LEADERS_CACHE[cache_key] = {"data": result, "ts": time.time()}
    return {"categories": result}


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
