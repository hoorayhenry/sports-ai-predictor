"""
Load real NBA historical game data from the official NBA Stats API.
No API key required — uses the public NBA stats endpoint.

Covers regular season + playoffs for 2021-22 through 2024-25.
"""
from __future__ import annotations
import time
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger

NBA_STATS_URL = "https://stats.nba.com/stats/leaguegamelog"

# NBA stats requires browser-like headers to avoid 403
NBA_HEADERS = {
    "User-Agent":          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer":             "https://stats.nba.com/",
    "Accept":              "application/json, text/plain, */*",
    "Accept-Language":     "en-US,en;q=0.9",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token":  "true",
    "Origin":              "https://stats.nba.com",
}

SEASONS = [
    ("2021-22", "Regular Season"),
    ("2021-22", "Playoffs"),
    ("2022-23", "Regular Season"),
    ("2022-23", "Playoffs"),
    ("2023-24", "Regular Season"),
    ("2023-24", "Playoffs"),
    ("2024-25", "Regular Season"),
]


def _fetch_game_log(season: str, season_type: str) -> list[dict]:
    """Fetch team game log from NBA stats API."""
    params = {
        "Counter":       "0",
        "Direction":     "ASC",
        "LeagueID":      "00",
        "PlayerOrTeam":  "T",
        "Season":        season,
        "SeasonType":    season_type,
        "Sorter":        "DATE",
    }
    try:
        with httpx.Client(timeout=30, headers=NBA_HEADERS, follow_redirects=True) as c:
            resp = c.get(NBA_STATS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"NBA stats API error [{season} {season_type}]: {e}")
        return []

    result_sets = data.get("resultSets", [])
    if not result_sets:
        return []

    rs     = result_sets[0]
    headers = rs.get("headers", [])
    rows    = rs.get("rowSet", [])

    try:
        idx = {h: i for i, h in enumerate(headers)}
        gi  = idx["GAME_ID"]
        tn  = idx["TEAM_NAME"]
        gd  = idx["GAME_DATE"]
        mu  = idx["MATCHUP"]
        pts = idx["PTS"]
        wl  = idx["WL"]
    except KeyError as e:
        logger.warning(f"NBA API missing column: {e}")
        return []

    # Group by GAME_ID — each game appears twice (once per team)
    games: dict[str, dict] = {}
    for row in rows:
        game_id = row[gi]
        team    = row[tn]
        matchup = row[mu]   # e.g. "BOS vs. MIA" or "BOS @ MIA"
        points  = row[pts] or 0
        date_s  = row[gd]
        is_home = "vs." in matchup

        if game_id not in games:
            games[game_id] = {"date": date_s, "home": None, "away": None, "home_pts": 0, "away_pts": 0}

        g = games[game_id]
        if is_home:
            g["home"]     = team
            g["home_pts"] = int(points)
        else:
            g["away"]     = team
            g["away_pts"] = int(points)

    events: list[dict] = []
    for game_id, g in games.items():
        if not g["home"] or not g["away"]:
            continue
        if g["home_pts"] == 0 and g["away_pts"] == 0:
            continue   # Game not yet played

        try:
            match_date = datetime.strptime(g["date"][:10], "%Y-%m-%d")
        except ValueError:
            continue

        hp     = g["home_pts"]
        ap     = g["away_pts"]
        result = "H" if hp > ap else "A"   # Basketball: no draw possible

        events.append({
            "external_id": f"nba_{game_id}",
            "sport":       "basketball",
            "competition": "NBA",
            "country":     "USA",
            "home_name":   g["home"],
            "away_name":   g["away"],
            "match_date":  match_date,
            "status":      "finished",
            "result":      result,
            "home_score":  hp,
            "away_score":  ap,
            "odds":        [],
        })

    return events


def fetch_all_nba_historical() -> list[dict]:
    """Fetch NBA historical game data for all configured seasons."""
    all_events: list[dict] = []

    for season, season_type in SEASONS:
        logger.info(f"Fetching NBA {season} {season_type}...")
        events = _fetch_game_log(season, season_type)
        all_events.extend(events)
        logger.info(f"  ✓ {len(events)} games")
        time.sleep(1.0)   # Respect rate limit

    logger.info(f"NBA total: {len(all_events)} historical games")
    return all_events
