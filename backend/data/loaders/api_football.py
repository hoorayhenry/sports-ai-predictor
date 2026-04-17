"""
API-Football client for pre-match intelligence.

Free tier: 100 requests/day (RapidAPI or direct api-sports.io key).
Set API_FOOTBALL_KEY in .env.

What this provides that no basic predictor has:
  • Confirmed starting lineups  (available ~1 hr before kickoff)
  • Current injury & suspension list per team
  • Post-match statistics — xG, shots, possession (for backfilling)

Strategy on free quota:
  - Only fetch lineups for matches we've decided are PLAY candidates
  - Cache all responses for 4 hours (lineup won't change once confirmed)
  - Post-match stats fetched once per completed match, then cached permanently
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

import httpx
from loguru import logger

BASE_URL = "https://v3.football.api-sports.io"
RAPIDAPI_URL = "https://api-football-v1.p.rapidapi.com/v3"

# In-memory cache: (endpoint, params_key) -> (timestamp, data)
_cache: dict[tuple, tuple[float, dict]] = {}
CACHE_TTL = 14_400   # 4 hours


def _get_client(api_key: str) -> tuple[httpx.Client, str]:
    """Return (httpx.Client, base_url) configured for the given key."""
    # Detect RapidAPI keys vs direct api-sports keys
    if len(api_key) > 40:
        headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com",
        }
        return httpx.Client(headers=headers, timeout=20), RAPIDAPI_URL
    headers = {"x-apisports-key": api_key}
    return httpx.Client(headers=headers, timeout=20), BASE_URL


def _fetch(api_key: str, endpoint: str, params: dict) -> dict:
    """Fetch with in-memory cache."""
    cache_key = (endpoint, str(sorted(params.items())))
    cached = _cache.get(cache_key)
    if cached and (time.time() - cached[0]) < CACHE_TTL:
        return cached[1]

    client, base = _get_client(api_key)
    try:
        with client:
            resp = client.get(f"{base}/{endpoint}", params=params)
            if resp.status_code == 200:
                data = resp.json()
                _cache[cache_key] = (time.time(), data)
                return data
            logger.warning(f"[API-Football] {endpoint} → HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[API-Football] {endpoint} error: {e}")
    return {}


# ── Public API ─────────────────────────────────────────────────────────────────

def get_lineups(api_key: str, fixture_id: int) -> dict:
    """
    Returns confirmed starting XIs for both teams.

    Response structure:
    {
      "home": {
        "team": {"id": 33, "name": "Manchester United"},
        "formation": "4-2-3-1",
        "startXI": [
          {"player": {"id": 629, "name": "D. De Gea", "number": 1, "pos": "G"}},
          ...
        ],
        "substitutes": [...],
        "coach": {"name": "Ten Hag"}
      },
      "away": { ... }
    }
    Returns {} if lineups not yet announced.
    """
    data = _fetch(api_key, "fixtures/lineups", {"fixture": fixture_id})
    raw = data.get("response", [])
    if len(raw) < 2:
        return {}

    out = {}
    for team_data in raw:
        side = "home" if team_data.get("team", {}).get("id") == raw[0].get("team", {}).get("id") else "away"
        out[side] = {
            "team":        team_data.get("team", {}),
            "formation":   team_data.get("formation", ""),
            "startXI":     team_data.get("startXI", []),
            "substitutes": team_data.get("substitutes", []),
            "coach":       team_data.get("coach", {}),
        }

    # Normalise to home/away by fixture order
    if len(raw) >= 2:
        out = {"home": _parse_team_lineup(raw[0]), "away": _parse_team_lineup(raw[1])}

    return out


def get_injuries(api_key: str, team_id: int, fixture_id: int | None = None) -> list[dict]:
    """
    Returns current injuries and suspensions for a team.
    Each entry: {"player": name, "type": "injury"|"suspension", "reason": str}

    Filters to fixture context when fixture_id is provided.
    """
    params: dict = {"team": team_id}
    if fixture_id:
        params["fixture"] = fixture_id

    data = _fetch(api_key, "injuries", params)
    raw = data.get("response", [])

    result = []
    for entry in raw:
        player = entry.get("player", {})
        injury_type = entry.get("type", "")
        result.append({
            "player_id":   player.get("id"),
            "player_name": player.get("name", ""),
            "type":        "suspension" if "suspension" in injury_type.lower() else "injury",
            "reason":      entry.get("reason", injury_type),
        })
    return result


def get_fixture_stats(api_key: str, fixture_id: int) -> dict:
    """
    Returns post-match statistics for both teams.
    Key stats extracted: xG, shots total, shots on target, possession.

    Response:
    {
      "home": {"xg": 1.8, "shots": 14, "shots_on_target": 6, "possession": 55},
      "away": {"xg": 0.9, "shots": 7,  "shots_on_target": 2, "possession": 45},
    }
    """
    data = _fetch(api_key, "fixtures/statistics", {"fixture": fixture_id})
    raw = data.get("response", [])
    if len(raw) < 2:
        return {}

    def _extract(team_stats: dict) -> dict:
        stats_list = team_stats.get("statistics", [])
        lookup = {s["type"]: s["value"] for s in stats_list}
        def _num(key, default=0.0):
            v = lookup.get(key)
            try:
                return float(str(v).replace("%", "")) if v is not None else default
            except (ValueError, TypeError):
                return default

        return {
            "xg":               _num("Expected Goals"),
            "shots":            int(_num("Total Shots")),
            "shots_on_target":  int(_num("Shots on Goal")),
            "possession":       _num("Ball Possession"),
            "corners":          int(_num("Corner Kicks")),
            "yellow_cards":     int(_num("Yellow Cards")),
            "red_cards":        int(_num("Red Cards")),
        }

    return {
        "home": _extract(raw[0]),
        "away": _extract(raw[1]),
    }


def get_upcoming_fixtures(
    api_key: str,
    league_id: int,
    season: int,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict]:
    """
    Returns upcoming fixtures for a league/season window.
    Useful for seeding the DB with fixture IDs matched to our Match rows.
    """
    params: dict = {"league": league_id, "season": season}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date

    data = _fetch(api_key, "fixtures", params)
    raw = data.get("response", [])

    result = []
    for fix in raw:
        fixture   = fix.get("fixture", {})
        teams     = fix.get("teams", {})
        goals     = fix.get("goals", {})
        result.append({
            "fixture_id":   fixture.get("id"),
            "date":         fixture.get("date"),
            "status":       fixture.get("status", {}).get("short", ""),
            "home_name":    teams.get("home", {}).get("name", ""),
            "home_api_id":  teams.get("home", {}).get("id"),
            "away_name":    teams.get("away", {}).get("name", ""),
            "away_api_id":  teams.get("away", {}).get("id"),
            "home_goals":   goals.get("home"),
            "away_goals":   goals.get("away"),
            "venue":        fixture.get("venue", {}).get("name", ""),
            "referee":      fixture.get("referee", ""),
        })
    return result


# ── Intelligence signal integration ──────────────────────────────────────────

def build_injury_signals(
    api_key: str,
    team_id: int,
    team_name: str,
    fixture_id: int | None = None,
) -> list[dict]:
    """
    Fetch injuries and format them as IntelligenceSignal-compatible dicts.
    Each signal has: team_name, signal_type, entity_name, impact_score, confidence.

    Impact score heuristics:
      -1.0 = star player confirmed out (GK or striker)
       -0.6 = key midfielder/defender out
       -0.3 = squad rotation player out
    """
    injuries = get_injuries(api_key, team_id, fixture_id)
    signals = []
    for inj in injuries:
        sig_type = inj["type"]
        # Conservative impact estimate — actual importance requires squad knowledge
        impact = -0.6   # default: meaningful player unavailable
        signals.append({
            "team_name":   team_name,
            "signal_type": sig_type,
            "entity_name": inj["player_name"],
            "impact_score": impact,
            "confidence":  0.85,           # confirmed official report
            "source_type": "api_football",
            "raw_text":    f"{inj['player_name']} — {inj['reason']}",
        })
    return signals


# ── Helper ────────────────────────────────────────────────────────────────────

def _parse_team_lineup(raw: dict) -> dict:
    return {
        "team":        raw.get("team", {}),
        "formation":   raw.get("formation", ""),
        "startXI":     [p["player"] for p in raw.get("startXI", []) if "player" in p],
        "substitutes": [p["player"] for p in raw.get("substitutes", []) if "player" in p],
        "coach":       raw.get("coach", {}),
    }
