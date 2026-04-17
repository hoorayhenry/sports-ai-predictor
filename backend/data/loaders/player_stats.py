"""
Daily top-player stats cache for leagues not covered by Sofascore's
top-players endpoint (NBA and NFL).

Data source: ESPN public API (no key required).
  NBA: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/leaders
  NFL: https://site.api.espn.com/apis/site/v2/sports/football/nfl/leaders

Outputs a list of LeaderCat dicts compatible with the frontend:
  [{ name, abbr, leaders: [{ rank, name, value, display,
                              player_id, headshot, team_id, team_name, team_logo }] }]

Entry point: refresh_player_stats_cache(db)
  - Fetches NBA + NFL for the current season
  - Upserts into PlayerStatsCache table
  - Returns { "nba": int_cats_saved, "nfl": int_cats_saved }
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
from loguru import logger

import httpx

from data.db_models.models import PlayerStatsCache

# ── Constants ─────────────────────────────────────────────────────────────────

_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

LEAGUE_CONFIGS: dict[str, dict] = {
    "nba": {
        "sport":  "basketball",
        "league": "nba",
        "season_type": 2,          # regular season
        "headshot_base": "https://a.espncdn.com/i/headshots/nba/players/full/{player_id}.png",
        "team_logo_base": "https://a.espncdn.com/i/teamlogos/nba/500/{team_abbr}.png",
    },
    "nfl": {
        "sport":  "football",
        "league": "nfl",
        "season_type": 2,
        "headshot_base": "https://a.espncdn.com/i/headshots/nfl/players/full/{player_id}.png",
        "team_logo_base": "https://a.espncdn.com/i/teamlogos/nfl/500/{team_abbr}.png",
    },
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SportsAI/1.0)",
    "Accept": "application/json",
}


# ── Parsing ───────────────────────────────────────────────────────────────────

def _parse_espn_leaders(data: dict, cfg: dict) -> list[dict]:
    """
    Normalize ESPN /leaders response into frontend-compatible LeaderCat list.

    ESPN returns either:
      data["categories"][i]["leaders"][j]["athlete"] + data["categories"][i]["leaders"][j]["team"]
    or (for some sports):
      data["categories"][i]["leaders"][j]["statistics"][k]["athletes"]
    We handle both shapes.
    """
    cats: list[dict] = []

    for cat in data.get("categories", []):
        cat_name = cat.get("displayName") or cat.get("name") or "Stats"
        cat_abbr = cat.get("shortDisplayName") or cat.get("abbreviation") or cat_name[:6]

        leaders: list[dict] = []

        raw_leaders = cat.get("leaders", [])

        # Shape A: each item has "athlete" + "displayValue" at top level
        # Shape B: each item has "statistics" list with athletes inside
        if raw_leaders and "athlete" in raw_leaders[0]:
            # Shape A — most ESPN leaders endpoints
            for rank0, entry in enumerate(raw_leaders):
                athlete = entry.get("athlete") or {}
                team    = entry.get("team") or {}

                player_id = str(athlete.get("id") or "")
                name      = athlete.get("displayName") or athlete.get("fullName") or ""
                if not name:
                    continue

                display = str(entry.get("displayValue") or "")
                try:
                    value = float(display.replace(",", "")) if display else 0.0
                except ValueError:
                    value = 0.0

                # Headshot: prefer ESPN CDN, fall back to embedded href
                hs_links = athlete.get("headshot") or {}
                headshot = hs_links.get("href") or (
                    cfg["headshot_base"].format(player_id=player_id) if player_id else ""
                )

                team_id   = str(team.get("id") or "")
                team_name = team.get("displayName") or team.get("name") or ""
                team_abbr = (team.get("abbreviation") or "").lower()
                logos     = team.get("logos") or []
                team_logo = logos[0].get("href") if logos else (
                    cfg["team_logo_base"].format(team_abbr=team_abbr) if team_abbr else ""
                )

                leaders.append({
                    "rank":      rank0 + 1,
                    "name":      name,
                    "value":     value,
                    "display":   display,
                    "player_id": player_id,
                    "headshot":  headshot,
                    "team_id":   team_id,
                    "team_name": team_name,
                    "team_logo": team_logo,
                })

        elif raw_leaders and "statistics" in raw_leaders[0]:
            # Shape B — statistics list inside each leader entry (rarer)
            for rank0, entry in enumerate(raw_leaders):
                athlete = entry.get("athlete") or {}
                team    = entry.get("team") or {}
                stats   = entry.get("statistics") or []
                # Use first stat value
                display = str(stats[0].get("displayValue") or "") if stats else ""
                try:
                    value = float(display.replace(",", "")) if display else 0.0
                except ValueError:
                    value = 0.0

                player_id = str(athlete.get("id") or "")
                name      = athlete.get("displayName") or ""
                if not name:
                    continue
                hs_links = athlete.get("headshot") or {}
                headshot = hs_links.get("href") or (
                    cfg["headshot_base"].format(player_id=player_id) if player_id else ""
                )
                team_id   = str(team.get("id") or "")
                team_name = team.get("displayName") or ""
                team_abbr = (team.get("abbreviation") or "").lower()
                logos     = team.get("logos") or []
                team_logo = logos[0].get("href") if logos else (
                    cfg["team_logo_base"].format(team_abbr=team_abbr) if team_abbr else ""
                )
                leaders.append({
                    "rank":      rank0 + 1,
                    "name":      name,
                    "value":     value,
                    "display":   display,
                    "player_id": player_id,
                    "headshot":  headshot,
                    "team_id":   team_id,
                    "team_name": team_name,
                    "team_logo": team_logo,
                })

        if leaders:
            cats.append({"name": cat_name, "abbr": cat_abbr, "leaders": leaders})

    return cats


# ── Fetcher ───────────────────────────────────────────────────────────────────

def fetch_league_leaders(league_key: str, season: int, timeout: int = 15) -> list[dict]:
    """
    Fetch top-player stats from ESPN for a single league.
    Returns list of LeaderCat dicts, or empty list on failure.
    """
    cfg = LEAGUE_CONFIGS.get(league_key)
    if not cfg:
        logger.warning(f"[PlayerStats] Unknown league_key: {league_key}")
        return []

    url = (
        f"{_ESPN_BASE}/{cfg['sport']}/{cfg['league']}/leaders"
        f"?season={season}&seasontype={cfg['season_type']}"
    )
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
        if resp.status_code != 200:
            logger.warning(f"[PlayerStats] ESPN {league_key} leaders → HTTP {resp.status_code}")
            return []
        data = resp.json()
        cats = _parse_espn_leaders(data, cfg)
        logger.info(f"[PlayerStats] {league_key} {season}: {len(cats)} categories fetched")
        return cats
    except Exception as e:
        logger.error(f"[PlayerStats] Fetch failed for {league_key}: {e}")
        return []


# ── DB upsert ─────────────────────────────────────────────────────────────────

def _upsert_cache(db, league_key: str, season: int, cats: list[dict]) -> bool:
    """Insert or update PlayerStatsCache row. Returns True on success."""
    try:
        existing = (
            db.query(PlayerStatsCache)
            .filter_by(league_key=league_key, season=season)
            .first()
        )
        payload = json.dumps(cats)
        if existing:
            existing.categories_json = payload
            existing.fetched_at      = datetime.utcnow()
        else:
            db.add(PlayerStatsCache(
                league_key=league_key,
                season=season,
                categories_json=payload,
            ))
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"[PlayerStats] DB upsert failed for {league_key}: {e}")
        return False


# ── Main entry point ──────────────────────────────────────────────────────────

def refresh_player_stats_cache(db, season: Optional[int] = None) -> dict[str, int]:
    """
    Fetch NBA and NFL top-player stats from ESPN and cache in DB.
    Called once per day by the scheduler.

    Returns { "nba": num_categories, "nfl": num_categories }.
    """
    from datetime import datetime as _dt
    if season is None:
        # ESPN seasons are year-based: 2024 = 2024-25 season
        season = _dt.utcnow().year

    results: dict[str, int] = {}
    for league_key in LEAGUE_CONFIGS:
        cats = fetch_league_leaders(league_key, season)
        if cats:
            _upsert_cache(db, league_key, season, cats)
            results[league_key] = len(cats)
        else:
            # Try previous season as fallback (e.g. NFL off-season in April)
            prev_cats = fetch_league_leaders(league_key, season - 1)
            if prev_cats:
                _upsert_cache(db, league_key, season - 1, prev_cats)
                results[league_key] = len(prev_cats)
                logger.info(f"[PlayerStats] Used {season-1} season data for {league_key} (current season unavailable)")
            else:
                results[league_key] = 0

    return results
