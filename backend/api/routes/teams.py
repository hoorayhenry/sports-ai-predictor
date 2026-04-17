"""
Team and player profiles — ESPN public API (no key, no quota).
Squad data is cached 1 hour: when a player transfers, ESPN updates within hours.
After the cache expires, the next request automatically reflects the new roster.
"""
from __future__ import annotations
import re
import time
import httpx
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from data.database import get_async_session
from data.db_models.models import NewsArticle

teams_router  = APIRouter(prefix="/teams",   tags=["teams"])
players_router = APIRouter(prefix="/players", tags=["players"])

_ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/",
}

_TEAM_CACHE:          dict[str, dict] = {}
_SQUAD_CACHE:         dict[str, dict] = {}
_PLAYER_CACHE:        dict[str, dict] = {}
_SEARCH_CACHE:        dict[str, dict] = {}
_SCHEDULE_CACHE:      dict[str, dict] = {}
_FULL_SCHEDULE_CACHE: dict[str, dict] = {}

# ── Friendly display names for every ESPN slug ───────────────────────────────
_LEAGUE_NAMES: dict[str, str] = {
    # Top 5 + others
    "eng.1":               "Premier League",
    "eng.2":               "Championship",
    "eng.3":               "League One",
    "eng.4":               "League Two",
    "eng.fa":              "FA Cup",
    "eng.league_cup":      "EFL Cup",
    "eng.community_shield":"Community Shield",
    "esp.1":               "La Liga",
    "esp.2":               "La Liga 2",
    "esp.copa_del_rey":    "Copa del Rey",
    "esp.supercopa":       "Supercopa de España",
    "ger.1":               "Bundesliga",
    "ger.2":               "2. Bundesliga",
    "ger.dfb_pokal":       "DFB-Pokal",
    "ger.dfb_supercup":    "DFB Supercup",
    "ita.1":               "Serie A",
    "ita.2":               "Serie B",
    "ita.coppa_italia":    "Coppa Italia",
    "ita.supercup":        "Supercoppa Italiana",
    "fra.1":               "Ligue 1",
    "fra.2":               "Ligue 2",
    "fra.coupe_de_france": "Coupe de France",
    "fra.trophee_champions":"Trophée des Champions",
    "por.1":               "Primeira Liga",
    "por.cup":             "Taça de Portugal",
    "por.league_cup":      "Taça da Liga",
    "por.super_cup":       "Supertaça",
    "ned.1":               "Eredivisie",
    "ned.cup":             "KNVB Cup",
    "ned.super_cup":       "Johan Cruijff Schaal",
    "bel.1":               "Pro League",
    "bel.cup":             "Belgian Cup",
    "tur.1":               "Süper Lig",
    "tur.cup":             "Turkish Cup",
    "tur.super_cup":       "Süper Kupa",
    "sco.1":               "Scottish Premiership",
    "sco.fa_cup":          "Scottish Cup",
    "sco.league_cup":      "Scottish League Cup",
    "gre.1":               "Super League",
    "gre.cup":             "Greek Cup",
    "rus.1":               "Russian Premier League",
    "ukr.1":               "Ukrainian Premier League",
    "cze.1":               "Czech First League",
    "svk.1":               "Slovak Super Liga",
    "aut.1":               "Austrian Bundesliga",
    "swi.1":               "Swiss Super League",
    "den.1":               "Superliga",
    "nor.1":               "Eliteserien",
    "swe.1":               "Allsvenskan",
    "fin.1":               "Veikkausliiga",
    "usa.1":               "MLS",
    "usa.open":            "U.S. Open Cup",
    "usa.2":               "USL Championship",
    "mex.1":               "Liga MX",
    "mex.copa_mx":         "Copa MX",
    "mex.supercopa":       "Supercopa MX",
    "bra.1":               "Brasileirão Série A",
    "bra.2":               "Brasileirão Série B",
    "bra.copa_do_brasil":  "Copa do Brasil",
    "bra.recopa":          "Recopa Brasileira",
    "arg.1":               "Liga Profesional",
    "arg.copa":            "Copa Argentina",
    "col.1":               "Liga BetPlay",
    "col.copa":            "Copa Colombia",
    "chi.1":               "Primera División Chile",
    "uru.1":               "Primera División Uruguay",
    "per.1":               "Liga 1 Perú",
    "ecu.1":               "LigaPro Ecuador",
    "ven.1":               "Primera División Venezuela",
    "par.1":               "División Profesional Paraguay",
    "bol.1":               "División Profesional Bolivia",
    "jpn.1":               "J1 League",
    "jpn.2":               "J2 League",
    "kor.1":               "K League 1",
    "chn.1":               "Chinese Super League",
    "sau.1":               "Saudi Pro League",
    "uae.league":          "UAE Pro League",
    "egy.1":               "Egyptian Premier League",
    "zaf.1":               "DStv Premiership",
    "nga.1":               "NPFL",
    "aus.1":               "A-League Men",
    # Continental
    "uefa.champions":      "Champions League",
    "uefa.europa":         "Europa League",
    "uefa.europa.conf":    "Conference League",
    "uefa.super_cup":      "UEFA Super Cup",
    "concacaf.champions":  "CONCACAF Champions Cup",
    "concacaf.league":     "CONCACAF League",
    "concacaf.nations":    "CONCACAF Nations League",
    "conmebol.libertadores":  "Copa Libertadores",
    "conmebol.sudamericana":  "Copa Sudamericana",
    "conmebol.recopa":        "Recopa Sudamericana",
    "afc.champions":          "AFC Champions League",
    "caf.champions":          "CAF Champions League",
    "caf.confederation":      "CAF Confederation Cup",
    "ofc.champions":          "OFC Champions League",
    # World
    "fifa.worldq.uefa":    "World Cup Qualifying (UEFA)",
    "fifa.worldq.conmebol":"World Cup Qualifying (CONMEBOL)",
    "fifa.cwc":            "Club World Cup",
    "fifa.confederations": "Confederations Cup",
}

# ── All extra competitions to check per primary league ───────────────────────
# ESPN returns an empty event list (not 404) for any competition the team
# hasn't entered, so over-fetching is safe — empty slugs are just filtered out.
_EXTRA_SLUGS_BY_LEAGUE: dict[str, list[str]] = {
    "eng.1": [
        "eng.fa", "eng.league_cup", "eng.community_shield",
        "uefa.champions", "uefa.europa", "uefa.europa.conf", "uefa.super_cup",
        "fifa.cwc",
    ],
    "eng.2": ["eng.fa", "eng.league_cup"],
    "eng.3": ["eng.fa", "eng.league_cup"],
    "esp.1": [
        "esp.copa_del_rey", "esp.supercopa",
        "uefa.champions", "uefa.europa", "uefa.europa.conf", "uefa.super_cup",
        "fifa.cwc",
    ],
    "esp.2": ["esp.copa_del_rey"],
    "ger.1": [
        "ger.dfb_pokal", "ger.dfb_supercup",
        "uefa.champions", "uefa.europa", "uefa.europa.conf", "uefa.super_cup",
        "fifa.cwc",
    ],
    "ger.2": ["ger.dfb_pokal"],
    "ita.1": [
        "ita.coppa_italia", "ita.supercup",
        "uefa.champions", "uefa.europa", "uefa.europa.conf", "uefa.super_cup",
        "fifa.cwc",
    ],
    "ita.2": ["ita.coppa_italia"],
    "fra.1": [
        "fra.coupe_de_france", "fra.trophee_champions",
        "uefa.champions", "uefa.europa", "uefa.europa.conf", "uefa.super_cup",
        "fifa.cwc",
    ],
    "fra.2": ["fra.coupe_de_france"],
    "por.1": [
        "por.cup", "por.league_cup", "por.super_cup",
        "uefa.champions", "uefa.europa", "uefa.europa.conf", "uefa.super_cup",
    ],
    "ned.1": [
        "ned.cup", "ned.super_cup",
        "uefa.champions", "uefa.europa", "uefa.europa.conf",
    ],
    "bel.1": [
        "bel.cup",
        "uefa.champions", "uefa.europa", "uefa.europa.conf",
    ],
    "tur.1": [
        "tur.cup", "tur.super_cup",
        "uefa.champions", "uefa.europa", "uefa.europa.conf",
    ],
    "sco.1": [
        "sco.fa_cup", "sco.league_cup",
        "uefa.champions", "uefa.europa", "uefa.europa.conf",
    ],
    "gre.1": [
        "gre.cup",
        "uefa.champions", "uefa.europa", "uefa.europa.conf",
    ],
    "aut.1": [
        "uefa.champions", "uefa.europa", "uefa.europa.conf",
    ],
    "swi.1": [
        "uefa.champions", "uefa.europa", "uefa.europa.conf",
    ],
    "den.1": [
        "uefa.champions", "uefa.europa", "uefa.europa.conf",
    ],
    "nor.1": [
        "uefa.champions", "uefa.europa", "uefa.europa.conf",
    ],
    "swe.1": [
        "uefa.champions", "uefa.europa", "uefa.europa.conf",
    ],
    "usa.1": [
        "usa.open",
        "concacaf.champions",
    ],
    "mex.1": [
        "mex.copa_mx", "mex.supercopa",
        "concacaf.champions",
    ],
    "bra.1": [
        "bra.copa_do_brasil", "bra.recopa",
        "conmebol.libertadores", "conmebol.sudamericana", "conmebol.recopa",
        "fifa.cwc",
    ],
    "bra.2": ["bra.copa_do_brasil"],
    "arg.1": [
        "arg.copa",
        "conmebol.libertadores", "conmebol.sudamericana", "conmebol.recopa",
    ],
    "col.1": [
        "col.copa",
        "conmebol.libertadores", "conmebol.sudamericana",
    ],
    "chi.1": [
        "conmebol.libertadores", "conmebol.sudamericana",
    ],
    "uru.1": [
        "conmebol.libertadores", "conmebol.sudamericana",
    ],
    "per.1": [
        "conmebol.libertadores", "conmebol.sudamericana",
    ],
    "ecu.1": [
        "conmebol.libertadores", "conmebol.sudamericana",
    ],
    "par.1": [
        "conmebol.libertadores", "conmebol.sudamericana",
    ],
    "bol.1": [
        "conmebol.libertadores", "conmebol.sudamericana",
    ],
    "ven.1": [
        "conmebol.libertadores", "conmebol.sudamericana",
    ],
    "jpn.1": [
        "afc.champions",
    ],
    "kor.1": [
        "afc.champions",
    ],
    "sau.1": [
        "afc.champions",
    ],
    "uae.league": [
        "afc.champions",
    ],
    "egy.1": [
        "caf.champions", "caf.confederation",
    ],
    "zaf.1": [
        "caf.champions", "caf.confederation",
    ],
    "nga.1": [
        "caf.champions", "caf.confederation",
    ],
}

# Fallback for any league not in the map: just check all UEFA slugs
_UEFA_FALLBACK = [
    "uefa.champions", "uefa.europa", "uefa.europa.conf", "uefa.super_cup",
]

_TEAM_TTL          = 3600
_SQUAD_TTL         = 3600
_PLAYER_TTL        = 3600
_SEARCH_TTL        = 1800
_SCHEDULE_TTL      = 300   # 5 min — results change on match days
_FULL_SCHEDULE_TTL = 300   # 5 min


def _espn_get(url: str, params: dict | None = None) -> dict | None:
    try:
        r = httpx.get(url, params=params, headers=_BROWSER_HEADERS, timeout=12)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _parse_logo(logos: list[dict]) -> str:
    """Return first logo URL, preferring non-dark variants."""
    if not logos:
        return ""
    for l in logos:
        rel = " ".join(l.get("rel", []))
        if "dark" not in rel:
            return l.get("href", "")
    return logos[0].get("href", "")


# ─────────────────────────────────────────────────────────────────────────────
# Team helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_team(league_slug: str, team_id: str) -> dict | None:
    data = _espn_get(f"{_ESPN_SITE}/{league_slug}/teams/{team_id}")
    if not data:
        return None

    team = data.get("team", {})
    if not team:
        return None

    logos  = team.get("logos", [])
    logo   = _parse_logo(logos)

    # Dark/alt logo
    logo_dark = ""
    for l in logos:
        rel = " ".join(l.get("rel", []))
        if "dark" in rel:
            logo_dark = l.get("href", "")
            break

    # Coach
    coach_name = ""
    for c in team.get("coaches", []):
        if c.get("type") == "head":
            coach_name = f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
            break

    # Season record summary
    record_summary = ""
    record = team.get("record", {})
    if record:
        items = record.get("items", [])
        if items:
            record_summary = items[0].get("summary", "")

    venue = team.get("venue", {})
    address = venue.get("address", {})

    links = team.get("links", [])
    espn_url = next(
        (l.get("href") for l in links if "clubhouse" in " ".join(l.get("rel", []))),
        f"https://www.espn.com/soccer/team/_/id/{team.get('id', '')}",
    )

    return {
        "id":            str(team.get("id", "")),
        "name":          team.get("displayName") or team.get("name", ""),
        "short_name":    team.get("shortDisplayName") or team.get("abbreviation", ""),
        "nickname":      team.get("nickname", ""),
        "logo":          logo,
        "logo_dark":     logo_dark,
        "primary_color": "#" + (team.get("color") or "6366f1"),
        "alt_color":     "#" + (team.get("alternateColor") or "4f5884"),
        "founded":       team.get("founded"),
        "description":   team.get("description") or team.get("standingSummary", ""),
        "location":      team.get("location", ""),
        "venue": {
            "name":     venue.get("fullName") or venue.get("name", ""),
            "city":     address.get("city", ""),
            "country":  address.get("country", ""),
            "capacity": venue.get("capacity"),
        },
        "record":      record_summary,
        "coach":       coach_name,
        "espn_url":    espn_url,
        "league_slug": league_slug,
    }


def _espn_headshot_url(player_id: str) -> str:
    """
    ESPN CDN serves player headshots at a predictable URL path.
    Works for the vast majority of professional players even when the
    roster API returns null for the 'headshot' field (which it does for ~95%).
    The CDN returns a placeholder image (not 404) for unknown IDs, so it's
    always safe to use.
    """
    return f"https://a.espncdn.com/i/headshots/soccer/players/full/{player_id}.png"


def _safe_pos(pos_field) -> tuple[str, str]:
    """Return (display_name, abbreviation) regardless of whether position
    is a dict, a plain string, or None."""
    if isinstance(pos_field, dict):
        display = pos_field.get("displayName") or pos_field.get("name") or ""
        abbr    = pos_field.get("abbreviation") or ""
        return display, abbr
    if isinstance(pos_field, str):
        return pos_field, pos_field[:3].upper()
    return "", ""


def _fetch_squad(league_slug: str, team_id: str) -> list[dict] | None:
    data = _espn_get(f"{_ESPN_SITE}/{league_slug}/teams/{team_id}/roster")
    if not data:
        return None

    athletes = data.get("athletes") or []
    if not athletes:
        return None

    squad: list[dict] = []

    try:
        for item in athletes:
            if not isinstance(item, dict):
                continue

            # Shape A: position-group wrapper  {"position": "...", "items": [...]}
            if "items" in item:
                players_list = item.get("items") or []
            # Shape B: flat athlete dict (ESPN soccer roster returns this)
            elif "id" in item:
                players_list = [item]
            else:
                continue

            for p in players_list:
                if not isinstance(p, dict):
                    continue

                pos_display, pos_abbr = _safe_pos(p.get("position"))

                pid = str(p.get("id") or "")

                # ESPN returns headshot=null for ~95% of players, but the CDN
                # URL is always predictable and safe to use.
                headshot_field = p.get("headshot")
                if isinstance(headshot_field, dict) and headshot_field.get("href"):
                    headshot_url = headshot_field["href"]
                elif pid:
                    headshot_url = _espn_headshot_url(pid)
                else:
                    headshot_url = ""

                birth_obj   = p.get("birthPlace") or {}
                nationality = (
                    p.get("citizenship")
                    or (birth_obj.get("country") if isinstance(birth_obj, dict) else None)
                    or ""
                )

                status_obj  = p.get("status") or {}
                status_type = (status_obj.get("type") or {}) if isinstance(status_obj, dict) else {}
                status_desc = status_type.get("description") or "Active" if isinstance(status_type, dict) else "Active"

                squad.append({
                    "id":            pid,
                    "name":          p.get("displayName") or p.get("fullName") or "",
                    "first_name":    p.get("firstName") or "",
                    "last_name":     p.get("lastName") or "",
                    "shirt_number":  p.get("jersey") or p.get("displayJersey"),
                    "position":      pos_display,
                    "position_abbr": pos_abbr,
                    "nationality":   nationality,
                    "age":           p.get("age"),
                    "dob":           (p.get("dateOfBirth") or "")[:10],
                    "headshot":      headshot_url,
                    "height":        p.get("displayHeight") or p.get("height"),
                    "weight":        p.get("displayWeight") or p.get("weight"),
                    "status":        status_desc,
                })

    except Exception:
        import traceback
        traceback.print_exc()
        return squad if squad else None

    return squad or None


# ─────────────────────────────────────────────────────────────────────────────
# Player helpers
# ─────────────────────────────────────────────────────────────────────────────

def _id_from_ref(ref: str, segment: str) -> str:
    """Extract a numeric ID from an ESPN $ref URL, e.g. '/teams/359?' → '359'."""
    m = re.search(rf"/{segment}/(\d+)", ref or "")
    return m.group(1) if m else ""


def _fetch_player(player_id: str) -> dict | None:
    """
    Two-call strategy (both confirmed working as of 2025):
      1. sports.core.api.espn.com  — bio, position, nationality, dob, team/league refs
      2. site.api.espn.com/common  — season stats by competition
    """
    # ── 1. Bio ────────────────────────────────────────────────────────────────
    bio = _espn_get(
        f"https://sports.core.api.espn.com/v2/sports/soccer/athletes/{player_id}"
    )
    if not bio:
        return None

    pos_display, pos_abbr = _safe_pos(bio.get("position"))

    birth_obj   = bio.get("birthPlace") or {}
    nationality = (
        bio.get("citizenship")
        or (birth_obj.get("country") if isinstance(birth_obj, dict) else None)
        or ""
    )

    # Team + league from $ref URLs
    team_ref   = (bio.get("defaultTeam")   or {}).get("$ref", "")
    league_ref = (bio.get("defaultLeague") or {}).get("$ref", "")
    team_id    = _id_from_ref(team_ref, "teams")
    league_slug = re.search(r"/leagues/([^?]+)", league_ref or "")
    league_slug = league_slug.group(1) if league_slug else ""

    # Fetch team name + logo via core API (one extra call, cached at route level)
    team_name = ""
    team_logo = (
        f"https://a.espncdn.com/i/teamlogos/soccer/500/{team_id}.png" if team_id else ""
    )
    if team_id:
        team_data = _espn_get(
            f"https://sports.core.api.espn.com/v2/sports/soccer/teams/{team_id}"
        )
        if team_data:
            team_name = team_data.get("displayName") or team_data.get("name") or ""

    # ── 2. Stats ──────────────────────────────────────────────────────────────
    stats:  list[dict] = []
    career: list[dict] = []

    overview = _espn_get(
        f"https://site.api.espn.com/apis/common/v3/sports/soccer/athletes/{player_id}/overview"
    )
    if overview:
        stat_info     = overview.get("statistics") or {}
        col_names     = stat_info.get("names", [])
        col_display   = stat_info.get("displayNames") or col_names
        splits        = stat_info.get("splits") or []

        # Each split = one competition/season row
        totals: dict[str, float] = {}
        for split in splits:
            vals = split.get("stats") or []
            row_stats = []
            for i, val in enumerate(vals):
                if i >= len(col_names):
                    break
                display = col_display[i] if i < len(col_display) else col_names[i]
                row_stats.append({"name": display, "display_value": str(val)})
                try:
                    totals[display] = totals.get(display, 0.0) + float(val)
                except (TypeError, ValueError):
                    pass
            if row_stats:
                career.append({
                    "season": split.get("displayName") or split.get("leagueSlug") or "",
                    "stats":  row_stats,
                })

        # Aggregate totals as the headline stat row
        stats = [
            {
                "name":          k,
                "display_value": str(int(v)) if v == int(v) else f"{v:.1f}",
            }
            for k, v in totals.items()
            if v > 0
        ]

    pid = str(bio.get("id") or player_id)

    return {
        "id":            pid,
        "name":          bio.get("displayName") or bio.get("fullName") or "",
        "first_name":    bio.get("firstName") or "",
        "last_name":     bio.get("lastName") or "",
        "shirt_number":  bio.get("jersey"),
        "position":      pos_display,
        "position_abbr": pos_abbr,
        "nationality":   nationality,
        "age":           bio.get("age"),
        "dob":           (bio.get("dateOfBirth") or "")[:10],
        "headshot":      _espn_headshot_url(pid),
        "height":        bio.get("displayHeight") or bio.get("height"),
        "weight":        bio.get("displayWeight") or bio.get("weight"),
        "team": {
            "id":          team_id,
            "name":        team_name,
            "logo":        team_logo,
            "league_slug": league_slug,
        },
        "stats":  stats,
        "career": career,
    }


def _search_players(name: str) -> list[dict]:
    """
    ESPN search returns items with uid like 's:600~a:280555'.
    The numeric athlete ID is after 'a:' — that ID works with the core API.
    Must use sport=soccer (not type=athlete) for the endpoint to return results.
    """
    data = _espn_get(
        "https://site.api.espn.com/apis/search/v2",
        params={"query": name, "sport": "soccer", "limit": "8"},
    )
    if not data:
        return []
    results = []
    for hit in (data.get("results") or []):
        if hit.get("type") != "player":
            continue
        for item in (hit.get("contents") or []):
            uid = item.get("uid") or ""
            m   = re.search(r"a:(\d+)", uid)
            if not m:
                continue
            athlete_id = m.group(1)
            results.append({
                "id":       athlete_id,
                "name":     item.get("displayName") or "",
                "team":     item.get("description") or "",   # ESPN puts league/team here
                "position": item.get("subType") or "",
                "image":    _espn_headshot_url(athlete_id),
            })
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Schedule / results helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_score(score_obj) -> str:
    """ESPN score can be a plain string, int, or a $ref dict."""
    if isinstance(score_obj, dict):
        return str(score_obj.get("displayValue") or score_obj.get("value") or "")
    return str(score_obj) if score_obj is not None else ""


def _fetch_schedule(league_slug: str, team_id: str) -> dict | None:
    """
    Returns recent results (last 8 completed) + next fixture + season record.
    Events are reverse-sorted by ESPN (most recent first).
    """
    # ── Schedule (completed matches) ──────────────────────────────────────────
    sched_data = _espn_get(
        f"{_ESPN_SITE}/{league_slug}/teams/{team_id}/schedule"
    )

    # ── Next fixture + record from team overview ───────────────────────────
    team_data = _espn_get(f"{_ESPN_SITE}/{league_slug}/teams/{team_id}")

    results:  list[dict] = []
    next_fix: dict | None = None
    record:   dict = {}

    # Parse record
    if team_data:
        team = team_data.get("team") or {}
        rec_items = (team.get("record") or {}).get("items") or []
        if rec_items:
            stats_map = {s["name"]: s["value"] for s in rec_items[0].get("stats", [])}
            record = {
                "summary":       rec_items[0].get("summary", ""),
                "played":        int(stats_map.get("gamesPlayed", 0)),
                "wins":          int(stats_map.get("wins", 0)),
                "draws":         int(stats_map.get("ties", 0)),
                "losses":        int(stats_map.get("losses", 0)),
                "goals_for":     int(stats_map.get("pointsFor", 0)),
                "goals_against": int(stats_map.get("pointsAgainst", 0)),
                "points":        int(stats_map.get("points", 0)),
                "home_wins":     int(stats_map.get("homeWins", 0)),
                "away_wins":     int(stats_map.get("awayWins", 0)),
                "standing":      team.get("standingSummary", ""),
            }

        # Next fixture
        next_evs = team.get("nextEvent") or []
        if next_evs:
            nev   = next_evs[0]
            ncomp = (nev.get("competitions") or [{}])[0]
            sides = []
            for c in ncomp.get("competitors") or []:
                t     = c.get("team") or {}
                tid   = str(t.get("id") or "")
                logos = t.get("logos") or []
                logo  = (logos[0].get("href") or "") if logos else (
                    f"https://a.espncdn.com/i/teamlogos/soccer/500/{tid}.png" if tid else ""
                )
                sides.append({
                    "id":       tid,
                    "name":     t.get("displayName") or t.get("name") or "",
                    "logo":     logo,
                    "home_away": c.get("homeAway") or "",
                })
            next_fix = {
                "name":        nev.get("name") or "",
                "date":        (nev.get("date") or "")[:16],
                "venue":       (ncomp.get("venue") or {}).get("fullName") or "",
                "competition": (nev.get("season") or {}).get("displayName") or "",
                "competitors": sides,
            }

    # Parse completed results
    if sched_data:
        events = sched_data.get("events") or []
        completed = [
            e for e in events
            if (e.get("competitions") or [{}])[0].get("status", {}).get("type", {}).get("completed")
        ]
        # Events are reverse-sorted (newest first)
        for ev in completed[:20]:
            comp        = (ev.get("competitions") or [{}])[0]
            date        = (ev.get("date") or "")[:10]
            competition = (
                (ev.get("season") or {}).get("displayName")
                or (comp.get("season") or {}).get("displayName")
                or ""
            )
            sides  = []
            for c in comp.get("competitors") or []:
                t     = c.get("team") or {}
                tid   = str(t.get("id") or "")
                score_raw = c.get("score")
                score = _parse_score(score_raw)
                winner = (score_raw or {}).get("winner", False) if isinstance(score_raw, dict) else False
                logos = t.get("logos") or []
                logo  = (logos[0].get("href") or "") if logos else (
                    f"https://a.espncdn.com/i/teamlogos/soccer/500/{tid}.png" if tid else ""
                )
                sides.append({
                    "id":       tid,
                    "name":     t.get("displayName") or t.get("name") or "",
                    "short":    t.get("shortDisplayName") or t.get("abbreviation") or "",
                    "logo":     logo,
                    "score":    score,
                    "winner":   winner,
                    "home_away": c.get("homeAway") or "",
                })
            # Determine result from perspective of the requested team
            team_side = next((s for s in sides if s["id"] == team_id), None)
            if team_side:
                opp = next((s for s in sides if s["id"] != team_id), None)
                if team_side["winner"]:
                    outcome = "W"
                elif opp and opp["winner"]:
                    outcome = "L"
                else:
                    outcome = "D"
            else:
                outcome = ""

            results.append({
                "date":        date,
                "competitors": sides,
                "outcome":     outcome,
                "venue":       (comp.get("venue") or {}).get("fullName") or "",
                "competition": competition,
            })

    return {
        "results":  results,
        "next_fix": next_fix,
        "record":   record,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Full multi-competition schedule helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_schedule_results_only(league_slug: str, team_id: str) -> list[dict]:
    """
    Lightweight schedule fetch for a single competition — completed results only.
    Returns [] silently for competitions the team hasn't entered (ESPN returns
    an empty events list, not 404, so this is always safe to call).
    """
    try:
        r = httpx.get(
            f"{_ESPN_SITE}/{league_slug}/teams/{team_id}/schedule",
            headers=_BROWSER_HEADERS,
            timeout=6,
        )
        sched_data = r.json() if r.status_code == 200 else None
    except Exception:
        sched_data = None
    if not sched_data:
        return []

    events    = sched_data.get("events") or []
    completed = [
        e for e in events
        if (e.get("competitions") or [{}])[0].get("status", {}).get("type", {}).get("completed")
    ]

    results: list[dict] = []
    for ev in completed:  # no cap — caller merges and deduplicates
        comp        = (ev.get("competitions") or [{}])[0]
        date        = (ev.get("date") or "")[:10]
        # Use ESPN's season displayName first, then our friendly map as fallback
        competition = (
            (ev.get("season") or {}).get("displayName")
            or (comp.get("season") or {}).get("displayName")
            or _LEAGUE_NAMES.get(league_slug, league_slug)
        )
        sides: list[dict] = []
        for c in comp.get("competitors") or []:
            t     = c.get("team") or {}
            tid   = str(t.get("id") or "")
            score_raw = c.get("score")
            score = _parse_score(score_raw)
            winner = (score_raw or {}).get("winner", False) if isinstance(score_raw, dict) else False
            logos  = t.get("logos") or []
            logo   = (logos[0].get("href") or "") if logos else (
                f"https://a.espncdn.com/i/teamlogos/soccer/500/{tid}.png" if tid else ""
            )
            sides.append({
                "id":       tid,
                "name":     t.get("displayName") or t.get("name") or "",
                "short":    t.get("shortDisplayName") or t.get("abbreviation") or "",
                "logo":     logo,
                "score":    score,
                "winner":   winner,
                "home_away": c.get("homeAway") or "",
            })

        team_side = next((s for s in sides if s["id"] == team_id), None)
        if team_side:
            opp     = next((s for s in sides if s["id"] != team_id), None)
            outcome = "W" if team_side["winner"] else ("L" if opp and opp["winner"] else "D")
        else:
            outcome = ""

        results.append({
            "date":        date,
            "competitors": sides,
            "outcome":     outcome,
            "venue":       (comp.get("venue") or {}).get("fullName") or "",
            "competition": competition,
        })

    return results


def _fetch_full_schedule(league_slug: str, team_id: str) -> dict | None:
    """
    Full multi-competition schedule for a team.

    Fetches the primary league (for record + next fixture) plus every other
    competition the team could be playing in this season — domestic cups,
    super cups, UEFA / CONMEBOL / CONCACAF / CAF tournaments — all in parallel.

    ESPN returns an empty event list (not an error) for competitions the team
    hasn't entered, so we can safely fire all slugs and discard empty results.
    No artificial cap on the number of results returned.
    """
    import concurrent.futures

    # ── Primary league ────────────────────────────────────────────────────────
    primary = _fetch_schedule(league_slug, team_id)
    if primary is None:
        primary = {"results": [], "next_fix": None, "record": {}}

    # Back-fill competition name for primary-league rows ESPN returns blank
    primary_name = _LEAGUE_NAMES.get(league_slug, "")
    for r in primary.get("results", []):
        if not r.get("competition"):
            r["competition"] = primary_name

    # ── Extra competitions — determined by primary league ─────────────────────
    extra_slugs: list[str] = list(_EXTRA_SLUGS_BY_LEAGUE.get(league_slug, _UEFA_FALLBACK))

    # ── Parallel fetch — one thread per slug, 6 s individual ESPN timeout ─────
    extra_results: list[dict] = []
    if extra_slugs:
        try:
            workers = min(len(extra_slugs), 12)  # up to 12 concurrent ESPN calls
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {
                    pool.submit(_fetch_schedule_results_only, s, team_id): s
                    for s in extra_slugs
                }
                for fut in concurrent.futures.as_completed(futs):
                    try:
                        extra_results.extend(fut.result())
                    except Exception:
                        pass
        except Exception:
            pass  # extra competitions failed — primary league data still returned

    # ── Merge + deduplicate by (date, sorted competitor IDs) ─────────────────
    all_results = list(primary.get("results", [])) + extra_results
    seen: set = set()
    unique: list[dict] = []
    for r in all_results:
        sides = tuple(sorted(c.get("id", "") for c in r.get("competitors", [])))
        key   = (r.get("date", ""), sides)
        if sides and key not in seen:
            seen.add(key)
            unique.append(r)

    unique.sort(key=lambda r: r.get("date", ""), reverse=True)

    return {
        "results":  unique,          # all competitions, no cap
        "next_fix": primary.get("next_fix"),
        "record":   primary.get("record", {}),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Team routes
# ─────────────────────────────────────────────────────────────────────────────

@teams_router.get("/{league_slug}/{team_id}")
async def get_team(league_slug: str, team_id: str):
    """Team overview — ESPN cached 1 hour. Transfers auto-reflect on next cache miss."""
    import asyncio
    cache_key = f"{league_slug}:{team_id}"
    cached = _TEAM_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _TEAM_TTL:
        return {**cached["data"], "cached": True}

    result = await asyncio.get_event_loop().run_in_executor(
        None, _fetch_team, league_slug, team_id
    )
    if result is None:
        if cached:
            return {**cached["data"], "cached": True, "stale": True}
        raise HTTPException(503, f"Could not fetch team {team_id} from ESPN.")

    _TEAM_CACHE[cache_key] = {"data": result, "ts": time.time()}
    return result


@teams_router.get("/{league_slug}/{team_id}/squad")
async def get_squad(league_slug: str, team_id: str):
    """
    Full squad for a team.
    Cached 1 hour — player transfers are reflected automatically on the next cache miss,
    since ESPN updates squad data within hours of a transfer completing.
    """
    import asyncio
    cache_key = f"squad:{league_slug}:{team_id}"
    cached = _SQUAD_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _SQUAD_TTL:
        return {"players": cached["data"], "cached": True}

    result = await asyncio.get_event_loop().run_in_executor(
        None, _fetch_squad, league_slug, team_id
    )
    if result is None:
        if cached:
            return {"players": cached["data"], "cached": True, "stale": True}
        raise HTTPException(503, f"Could not fetch squad for team {team_id}.")

    _SQUAD_CACHE[cache_key] = {"data": result, "ts": time.time()}
    return {"players": result, "cached": False}


@teams_router.get("/{league_slug}/{team_id}/schedule")
async def get_team_schedule(league_slug: str, team_id: str):
    """Recent results + next fixture + season record. Cached 5 min."""
    import asyncio
    cache_key = f"sched:{league_slug}:{team_id}"
    cached = _SCHEDULE_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _SCHEDULE_TTL:
        return {**cached["data"], "cached": True}

    result = await asyncio.get_event_loop().run_in_executor(
        None, _fetch_schedule, league_slug, team_id
    )
    if result is None:
        if cached:
            return {**cached["data"], "cached": True, "stale": True}
        raise HTTPException(503, "Could not fetch schedule from ESPN.")

    _SCHEDULE_CACHE[cache_key] = {"data": result, "ts": time.time()}
    return result


@teams_router.get("/{league_slug}/{team_id}/schedule/full")
async def get_full_team_schedule(league_slug: str, team_id: str):
    """
    Full team schedule across the primary league + UEFA competitions in parallel.
    Returns merged, deduplicated results with competition names — ideal for the
    team overview page where fans want to see ALL matches, not just one league.
    Cached 5 min.
    """
    import asyncio
    cache_key = f"full_sched:{league_slug}:{team_id}"
    cached    = _FULL_SCHEDULE_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _FULL_SCHEDULE_TTL:
        return {**cached["data"], "cached": True}

    result = await asyncio.get_event_loop().run_in_executor(
        None, _fetch_full_schedule, league_slug, team_id
    )
    if result is None:
        if cached:
            return {**cached["data"], "cached": True, "stale": True}
        raise HTTPException(503, "Could not fetch full schedule from ESPN.")

    _FULL_SCHEDULE_CACHE[cache_key] = {"data": result, "ts": time.time()}
    return result


@teams_router.get("/{league_slug}/{team_id}/news")
async def get_team_news(
    league_slug: str,
    team_id: str,
    team_name: str = Query(...),
    db: AsyncSession = Depends(get_async_session),
):
    """Articles from our news DB that mention this team by name."""
    result = await db.execute(
        select(NewsArticle)
        .where(
            NewsArticle.status == "published",
            or_(
                NewsArticle.title.ilike(f"%{team_name}%"),
                NewsArticle.tags.ilike(f"%{team_name}%"),
            ),
        )
        .order_by(NewsArticle.created_at.desc())
        .limit(12)
    )
    articles = result.scalars().all()
    return {
        "articles": [
            {
                "id":           a.id,
                "title":        a.title,
                "summary":      a.summary,
                "category":     a.category,
                "image_url":    a.image_url,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "created_at":   a.created_at.isoformat() if a.created_at else None,
            }
            for a in articles
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# Player routes
# ─────────────────────────────────────────────────────────────────────────────

@players_router.get("/soccer/{player_id}")
async def get_player(player_id: str):
    """Player profile — bio, stats, career history. ESPN cached 1 hour."""
    import asyncio
    cached = _PLAYER_CACHE.get(player_id)
    if cached and (time.time() - cached["ts"]) < _PLAYER_TTL:
        return {**cached["data"], "cached": True}

    result = await asyncio.get_event_loop().run_in_executor(
        None, _fetch_player, player_id
    )
    if result is None:
        if cached:
            return {**cached["data"], "cached": True, "stale": True}
        raise HTTPException(503, f"Could not fetch player {player_id} from ESPN.")

    _PLAYER_CACHE[player_id] = {"data": result, "ts": time.time()}
    return result


@players_router.get("/soccer/{player_id}/news")
async def get_player_news(
    player_id: str,
    player_name: str = Query(...),
    db: AsyncSession = Depends(get_async_session),
):
    """Articles from our news DB that mention this player by name."""
    result = await db.execute(
        select(NewsArticle)
        .where(
            NewsArticle.status == "published",
            or_(
                NewsArticle.title.ilike(f"%{player_name}%"),
                NewsArticle.body.ilike(f"%{player_name}%"),
                NewsArticle.tags.ilike(f"%{player_name}%"),
            ),
        )
        .order_by(NewsArticle.created_at.desc())
        .limit(12)
    )
    articles = result.scalars().all()
    return {
        "articles": [
            {
                "id":           a.id,
                "title":        a.title,
                "summary":      a.summary,
                "category":     a.category,
                "image_url":    a.image_url,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "created_at":   a.created_at.isoformat() if a.created_at else None,
            }
            for a in articles
        ]
    }


@players_router.get("/top-stats")
async def get_top_player_stats(
    league_key: str = Query(..., description="nba or nfl"),
    season: int = Query(None, description="Season year, e.g. 2024"),
):
    """
    Return cached top-player stats for NBA or NFL.
    Stats are fetched from ESPN once per day by the scheduler and stored in DB.
    Falls back to fetching live if cache is empty.
    """
    import json
    from datetime import datetime as _dt
    from data.database import get_sync_session
    from data.db_models.models import PlayerStatsCache

    if season is None:
        season = _dt.utcnow().year

    # Try current season, then previous season (for off-season periods)
    for s in [season, season - 1]:
        with get_sync_session() as db:
            row = (
                db.query(PlayerStatsCache)
                .filter_by(league_key=league_key, season=s)
                .first()
            )
            if row and row.categories_json:
                cats = json.loads(row.categories_json)
                if cats:
                    return {"league_key": league_key, "season": s, "categories": cats}

    # Cache miss — fetch live and store
    from data.loaders.player_stats import fetch_league_leaders, _upsert_cache
    cats = fetch_league_leaders(league_key, season)
    if not cats:
        cats = fetch_league_leaders(league_key, season - 1)
        if cats:
            season = season - 1
    if cats:
        with get_sync_session() as db:
            _upsert_cache(db, league_key, season, cats)
    return {"league_key": league_key, "season": season, "categories": cats}


@players_router.get("/soccer/search")
async def search_players(q: str = Query(..., min_length=2)):
    """Search for a player by name — ESPN athlete search. Used for smart interlinking."""
    import asyncio
    cached = _SEARCH_CACHE.get(q.lower())
    if cached and (time.time() - cached["ts"]) < _SEARCH_TTL:
        return {"results": cached["data"]}

    results = await asyncio.get_event_loop().run_in_executor(
        None, _search_players, q
    )
    _SEARCH_CACHE[q.lower()] = {"data": results, "ts": time.time()}
    return {"results": results}
