"""
Sofascore-based sports data for all sports.
Used by the frontend Sports page for all non-football leagues, and for
football tournaments not covered by ESPN (e.g. World Cup, Africa Cup).

Sofascore unofficial API — no auth required, covers all major sports.
Data is cached in LeagueSeasonCache keyed by (ss_{tournament_id}, season_id, data_type).

Endpoints:
  GET /sports-data/seasons?tournament_id=132
  GET /sports-data/standings?tournament_id=132&season_id=57890
  GET /sports-data/fixtures?tournament_id=132&season_id=57890
  GET /sports-data/leaders?tournament_id=132&season_id=57890
"""
from __future__ import annotations
import json as _json
from datetime import datetime as _dt
from typing import Optional

import httpx
from fastapi import APIRouter, Query, HTTPException
from loguru import logger

router = APIRouter(prefix="/sports-data", tags=["sports-data"])

_SS_BASE = "https://api.sofascore.com/api/v1"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.sofascore.com/",
}
_TIMEOUT = 15


# ── Sofascore fetch helpers ───────────────────────────────────────────────────

async def _ss_get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        r = await client.get(f"{_SS_BASE}{path}", headers=_HEADERS)
        r.raise_for_status()
        return r.json()


# ── DB cache helpers ─────────────────────────────────────────────────────────

def _slug(tournament_id: int) -> str:
    return f"ss_{tournament_id}"


async def _db_get(tournament_id: int, season_id: int, data_type: str, max_age_s: int | None = None) -> dict | None:
    from data.database import AsyncSessionLocal
    from data.db_models.models import LeagueSeasonCache
    from sqlalchemy import select
    slug = _slug(tournament_id)
    try:
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(LeagueSeasonCache).where(
                    LeagueSeasonCache.league_slug == slug,
                    LeagueSeasonCache.season      == season_id,
                    LeagueSeasonCache.data_type   == data_type,
                )
            )
            rec = row.scalar_one_or_none()
            if rec:
                if max_age_s is not None:
                    age = (_dt.utcnow() - rec.fetched_at).total_seconds()
                    if age > max_age_s:
                        return None
                return _json.loads(rec.json_data)
    except Exception as e:
        logger.debug(f"sports_data _db_get error: {e}")
    return None


async def _db_put(tournament_id: int, season_id: int, data_type: str, payload: dict) -> None:
    from data.database import AsyncSessionLocal
    from data.db_models.models import LeagueSeasonCache
    from sqlalchemy import select
    slug = _slug(tournament_id)
    try:
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(LeagueSeasonCache).where(
                    LeagueSeasonCache.league_slug == slug,
                    LeagueSeasonCache.season      == season_id,
                    LeagueSeasonCache.data_type   == data_type,
                )
            )
            rec = row.scalar_one_or_none()
            if rec:
                rec.json_data  = _json.dumps(payload)
                rec.fetched_at = _dt.utcnow()
            else:
                db.add(LeagueSeasonCache(
                    league_slug=slug,
                    season=season_id,
                    data_type=data_type,
                    json_data=_json.dumps(payload),
                    fetched_at=_dt.utcnow(),
                ))
            await db.commit()
    except Exception as e:
        logger.debug(f"sports_data _db_put error: {e}")


# ── Season resolution ─────────────────────────────────────────────────────────

async def _get_current_season_id(tournament_id: int) -> int | None:
    """
    Fetch season list from Sofascore, return the most recent season ID.
    Cached for 7 days (season IDs change once a year).
    """
    _SEASONS_SENTINEL = -1  # use season=-1 to store the seasons list
    cached = await _db_get(tournament_id, _SEASONS_SENTINEL, "seasons", max_age_s=7 * 86400)
    if cached:
        seasons = cached.get("seasons", [])
        if seasons:
            return seasons[0]["id"]

    try:
        data = await _ss_get(f"/unique-tournament/{tournament_id}/seasons")
        seasons = data.get("seasons", [])
        if seasons:
            await _db_put(tournament_id, _SEASONS_SENTINEL, "seasons", {"seasons": seasons})
            return seasons[0]["id"]
    except Exception as e:
        logger.warning(f"Sofascore seasons fetch failed for tournament {tournament_id}: {e}")
    return None


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _normalise_standings(data: dict, sport_key: str) -> list[dict]:
    """
    Normalise Sofascore standings into a consistent format understood by the frontend.
    Returns a list of groups, each group is a list of team rows.
    """
    raw_standings = data.get("standings", [])
    groups = []

    for group in raw_standings:
        group_name = group.get("name") or group.get("type") or "Standings"
        rows = []
        for row in group.get("rows", []):
            team = row.get("team", {})
            # Build team_logo from Sofascore CDN
            team_id = team.get("id")
            logo_url = f"https://api.sofascore.com/api/v1/team/{team_id}/image" if team_id else ""

            entry: dict = {
                "rank":        row.get("position", 0),
                "team_id":     str(team_id) if team_id else "",
                "team_name":   team.get("name", ""),
                "team_short":  team.get("shortName") or team.get("nameCode") or team.get("name", "")[:3].upper(),
                "team_logo":   logo_url,
                "description": row.get("description"),
                "group":       group_name if len(raw_standings) > 1 else None,
            }

            if sport_key in ("football",):
                entry.update({
                    "points":        row.get("points", 0),
                    "played":        row.get("matches", 0),
                    "win":           row.get("wins", 0),
                    "draw":          row.get("draws", 0),
                    "lose":          row.get("losses", 0),
                    "goals_for":     row.get("scoresFor", 0),
                    "goals_against": row.get("scoresAgainst", 0),
                    "goal_diff":     row.get("scoreDiffFormatted", 0),
                    "form":          _parse_form(row.get("promotion", {}).get("text", "")),
                })
            elif sport_key in ("basketball", "american_football", "ice_hockey", "baseball"):
                # W-L-based sports
                wins   = row.get("wins", 0)
                losses = row.get("losses", 0)
                played = wins + losses
                pct    = round(wins / played, 3) if played > 0 else 0.0
                entry.update({
                    "points":        wins,          # reuse "points" as wins for consistency
                    "played":        played,
                    "win":           wins,
                    "draw":          row.get("draws", 0),
                    "lose":          losses,
                    "goals_for":     row.get("scoresFor", 0),
                    "goals_against": row.get("scoresAgainst", 0),
                    "goal_diff":     wins - losses,
                    "pct":           pct,
                    "form":          [],
                })
            elif sport_key in ("cricket",):
                # Cricket points table: NR counted as half-point
                entry.update({
                    "points":        row.get("points", 0),
                    "played":        row.get("matches", 0),
                    "win":           row.get("wins", 0),
                    "draw":          row.get("draws", 0),   # no result
                    "lose":          row.get("losses", 0),
                    "goals_for":     row.get("scoresFor", 0),
                    "goals_against": row.get("scoresAgainst", 0),
                    "goal_diff":     0,
                    "nrr":           row.get("percentage", 0.0),  # net run rate
                    "form":          [],
                })
            else:
                # Rugby, handball, volleyball — points-based
                entry.update({
                    "points":        row.get("points", 0),
                    "played":        row.get("matches", 0),
                    "win":           row.get("wins", 0),
                    "draw":          row.get("draws", 0),
                    "lose":          row.get("losses", 0),
                    "goals_for":     row.get("scoresFor", 0),
                    "goals_against": row.get("scoresAgainst", 0),
                    "goal_diff":     row.get("scoreDiffFormatted", 0),
                    "form":          [],
                })
            rows.append(entry)
        if rows:
            groups.append({"name": group_name, "rows": rows})

    return groups


def _parse_form(text: str) -> list[str]:
    """Convert form string like 'W W L D W' → ['W','W','L','D','W']."""
    if not text:
        return []
    return [c for c in text.split() if c in ("W", "L", "D")][:5]


def _normalise_event(event: dict, sport_key: str) -> dict | None:
    """Normalise a Sofascore event into the frontend fixture shape."""
    try:
        home = event.get("homeTeam", {})
        away = event.get("awayTeam", {})
        score = event.get("homeScore", {})
        away_score = event.get("awayScore", {})

        status_code = event.get("status", {}).get("type", "notstarted")
        if status_code in ("inprogress",):
            status = "live"
        elif status_code in ("finished",):
            status = "finished"
        else:
            status = "scheduled"

        home_id = home.get("id")
        away_id = away.get("id")

        # Score
        home_pts = score.get("current") if status != "scheduled" else None
        away_pts = away_score.get("current") if status != "scheduled" else None

        # Start time
        start_ts = event.get("startTimestamp")
        start_iso = _dt.utcfromtimestamp(start_ts).isoformat() if start_ts else ""

        return {
            "id":          str(event.get("id", "")),
            "date":        start_iso,
            "status":      status,
            "live_minute": event.get("time", {}).get("played") if status == "live" else None,
            "home": {
                "id":    str(home_id) if home_id else "",
                "name":  home.get("name", ""),
                "short": home.get("shortName") or home.get("nameCode", ""),
                "logo":  f"https://api.sofascore.com/api/v1/team/{home_id}/image" if home_id else "",
                "score": home_pts,
            },
            "away": {
                "id":    str(away_id) if away_id else "",
                "name":  away.get("name", ""),
                "short": away.get("shortName") or away.get("nameCode", ""),
                "logo":  f"https://api.sofascore.com/api/v1/team/{away_id}/image" if away_id else "",
                "score": away_pts,
            },
            "venue": event.get("venue", {}).get("name", ""),
            "tournament_id": str(event.get("tournament", {}).get("uniqueTournament", {}).get("id", "")),
        }
    except Exception:
        return None


# ── API Endpoints ─────────────────────────────────────────────────────────────

@router.get("/seasons")
async def get_seasons(tournament_id: int = Query(...)):
    """Return available seasons for a Sofascore tournament."""
    _SENTINEL = -1
    cached = await _db_get(tournament_id, _SENTINEL, "seasons")
    if cached:
        return cached

    try:
        data = await _ss_get(f"/unique-tournament/{tournament_id}/seasons")
        seasons = data.get("seasons", [])
        result = {"seasons": [{"id": s["id"], "year": s.get("year", str(s["id"]))} for s in seasons]}
        if result["seasons"]:
            await _db_put(tournament_id, _SENTINEL, "seasons", result)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sofascore seasons fetch failed: {e}")


@router.get("/standings")
async def get_standings(
    tournament_id: int = Query(...),
    season_id: Optional[int] = Query(None),
    sport_key: str = Query("football"),
):
    """Return league standings from Sofascore."""
    if season_id is None:
        season_id = await _get_current_season_id(tournament_id)
        if season_id is None:
            raise HTTPException(status_code=404, detail="Could not resolve current season")

    # Current season — cache 5 min; historical — cache forever (no max_age)
    current_season = await _get_current_season_id(tournament_id)
    is_current = (season_id == current_season)
    max_age = 300 if is_current else None

    cached = await _db_get(tournament_id, season_id, "standings", max_age_s=max_age)
    if cached:
        return cached

    try:
        data = await _ss_get(f"/unique-tournament/{tournament_id}/season/{season_id}/standings/total")
        groups = _normalise_standings(data, sport_key)
        result = {
            "tournament_id": tournament_id,
            "season_id":     season_id,
            "sport_key":     sport_key,
            "groups":        groups,
        }
        await _db_put(tournament_id, season_id, "standings", result)
        return result
    except Exception as e:
        logger.warning(f"Sofascore standings failed tournament={tournament_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Sofascore standings fetch failed: {e}")


@router.get("/fixtures")
async def get_fixtures(
    tournament_id: int = Query(...),
    season_id: Optional[int] = Query(None),
    sport_key: str = Query("football"),
):
    """Return recent + upcoming fixtures from Sofascore."""
    if season_id is None:
        season_id = await _get_current_season_id(tournament_id)
        if season_id is None:
            raise HTTPException(status_code=404, detail="Could not resolve current season")

    cached = await _db_get(tournament_id, season_id, "fixtures", max_age_s=120)  # 2 min cache
    if cached:
        return cached

    events: list[dict] = []
    try:
        # Fetch last 3 pages of recent results
        for page in range(3):
            try:
                data = await _ss_get(f"/unique-tournament/{tournament_id}/season/{season_id}/events/last/{page}")
                for ev in data.get("events", []):
                    norm = _normalise_event(ev, sport_key)
                    if norm:
                        events.append(norm)
            except Exception:
                break

        # Fetch next 3 pages of upcoming
        for page in range(3):
            try:
                data = await _ss_get(f"/unique-tournament/{tournament_id}/season/{season_id}/events/next/{page}")
                for ev in data.get("events", []):
                    norm = _normalise_event(ev, sport_key)
                    if norm:
                        events.append(norm)
            except Exception:
                break

        # Sort by date, deduplicate by id
        seen: set[str] = set()
        unique: list[dict] = []
        for ev in sorted(events, key=lambda e: e["date"]):
            if ev["id"] not in seen:
                seen.add(ev["id"])
                unique.append(ev)

        result = {
            "tournament_id": tournament_id,
            "season_id":     season_id,
            "fixtures":      unique,
            "total":         len(unique),
        }
        await _db_put(tournament_id, season_id, "fixtures", result)
        return result
    except Exception as e:
        logger.warning(f"Sofascore fixtures failed tournament={tournament_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Sofascore fixtures fetch failed: {e}")


@router.get("/leaders")
async def get_leaders(
    tournament_id: int = Query(...),
    season_id: Optional[int] = Query(None),
    sport_key: str = Query("football"),
):
    """Return top performers (scorers, assists, points, etc.) from Sofascore."""
    if season_id is None:
        season_id = await _get_current_season_id(tournament_id)
        if season_id is None:
            raise HTTPException(status_code=404, detail="Could not resolve current season")

    cached = await _db_get(tournament_id, season_id, "leaders", max_age_s=1800)  # 30 min
    if cached:
        return cached

    categories: list[dict] = []
    # Sofascore top players endpoint
    stat_endpoints = {
        "football":         [("goals", "Goals"), ("assists", "Assists"), ("yellowCards", "Yellow Cards")],
        "basketball":       [("points", "Points"), ("rebounds", "Rebounds"), ("assists", "Assists")],
        "ice_hockey":       [("goals", "Goals"), ("assists", "Assists"), ("points", "Points")],
        "american_football":[("passingYards", "Pass Yards"), ("rushingYards", "Rush Yards"), ("touchdowns", "TDs")],
        "baseball":         [("homeRuns", "Home Runs"), ("battingAverage", "Batting Avg"), ("rbi", "RBI")],
        "cricket":          [("runs", "Runs"), ("wickets", "Wickets"), ("centuries", "Centuries")],
        "rugby":            [("points", "Points"), ("tries", "Tries"), ("conversions", "Conversions")],
        "handball":         [("goals", "Goals"), ("saves", "Saves"), ("assists", "Assists")],
        "volleyball":       [("points", "Points"), ("kills", "Kills"), ("aces", "Aces")],
        "tennis":           [("wins", "Wins"), ("titles", "Titles")],
    }

    stat_list = stat_endpoints.get(sport_key, [("goals", "Goals")])
    for stat_key, stat_name in stat_list:
        try:
            data = await _ss_get(
                f"/unique-tournament/{tournament_id}/season/{season_id}/statistics/regularSeason/overall/{stat_key}/desc/0"
            )
            players = data.get("results", data.get("players", []))[:10]
            entries = []
            for p in players:
                player = p.get("player", p)
                team   = p.get("team", {})
                pid    = player.get("id")
                tid    = team.get("id")
                entries.append({
                    "rank":       players.index(p) + 1,
                    "value":      p.get(stat_key, p.get("statistics", {}).get(stat_key, 0)),
                    "display":    str(p.get(stat_key, p.get("statistics", {}).get(stat_key, 0))),
                    "player_id":  str(pid) if pid else "",
                    "name":       player.get("name", player.get("shortName", "")),
                    "headshot":   f"https://api.sofascore.com/api/v1/player/{pid}/image" if pid else "",
                    "team_id":    str(tid) if tid else "",
                    "team_name":  team.get("name", ""),
                    "team_logo":  f"https://api.sofascore.com/api/v1/team/{tid}/image" if tid else "",
                    "tournament_id": str(tournament_id),
                })
            if entries:
                categories.append({"name": stat_name, "abbr": stat_key, "leaders": entries})
        except Exception as e:
            logger.debug(f"Leaders stat {stat_key} failed for tournament {tournament_id}: {e}")

    result = {"tournament_id": tournament_id, "season_id": season_id, "categories": categories}
    if categories:
        await _db_put(tournament_id, season_id, "leaders", result)
    return result


@router.get("/teams")
async def get_teams(
    tournament_id: int = Query(...),
    season_id: Optional[int] = Query(None),
):
    """Return all teams in a tournament season from Sofascore."""
    if season_id is None:
        season_id = await _get_current_season_id(tournament_id)
        if season_id is None:
            raise HTTPException(status_code=404, detail="Could not resolve current season")

    cached = await _db_get(tournament_id, season_id, "teams", max_age_s=86400)  # 1 day
    if cached:
        return cached

    try:
        data = await _ss_get(f"/unique-tournament/{tournament_id}/season/{season_id}/teams")
        raw_teams = data.get("teams", [])
        teams = []
        for t in raw_teams:
            tid = t.get("id")
            teams.append({
                "id":      str(tid) if tid else "",
                "name":    t.get("name", ""),
                "short":   t.get("shortName") or t.get("nameCode", ""),
                "logo":    f"https://api.sofascore.com/api/v1/team/{tid}/image" if tid else "",
                "country": t.get("country", {}).get("name", ""),
                "venue":   t.get("venue", {}).get("name", ""),
            })
        result = {"tournament_id": tournament_id, "season_id": season_id, "teams": teams}
        await _db_put(tournament_id, season_id, "teams", result)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sofascore teams fetch failed: {e}")
