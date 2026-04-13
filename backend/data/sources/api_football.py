"""
API-Football client (RapidAPI or direct api-football.com subscription).
Used for:
  - Fetching ALL fixtures for current season (full schedule)
  - Fetching completed match results
  - Upcoming fixture enrichment

Set API_FOOTBALL_KEY in .env to enable.
Free tier: 100 requests/day.  Standard: $10/month unlimited.

API docs: https://www.api-football.com/documentation-v3
"""
from __future__ import annotations
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx
from loguru import logger
from config.settings import get_settings

settings = get_settings()

BASE_RAPIDAPI = "https://api-football-v1.p.rapidapi.com/v3"
BASE_DIRECT   = "https://v3.football.api-sports.io"

# RapidAPI keys are long (50+ chars); direct api-football.com keys are 32-char hex
def _is_rapidapi_key(key: str) -> bool:
    return len(key) > 40

def _base() -> str:
    return BASE_RAPIDAPI if _is_rapidapi_key(settings.api_football_key) else BASE_DIRECT

def _headers() -> dict:
    if _is_rapidapi_key(settings.api_football_key):
        return {
            "X-RapidAPI-Key":  settings.api_football_key,
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com",
        }
    return {
        "x-apisports-key": settings.api_football_key,
    }


# Major league IDs  →  (display name, country, sport_key)
LEAGUES: dict[int, tuple[str, str, str]] = {
    # Football / Soccer
    39:  ("Premier League",           "England",      "football"),
    140: ("La Liga",                  "Spain",        "football"),
    78:  ("Bundesliga",               "Germany",      "football"),
    135: ("Serie A",                  "Italy",        "football"),
    61:  ("Ligue 1",                  "France",       "football"),
    2:   ("UEFA Champions League",    "Europe",       "football"),
    3:   ("UEFA Europa League",       "Europe",       "football"),
    848: ("UEFA Conference League",   "Europe",       "football"),
    88:  ("Eredivisie",               "Netherlands",  "football"),
    94:  ("Primeira Liga",            "Portugal",     "football"),
    203: ("Süper Lig",                "Turkey",       "football"),
    144: ("Jupiler Pro League",       "Belgium",      "football"),
    218: ("NPFL",                     "Nigeria",      "football"),
    253: ("Major League Soccer",      "USA",          "football"),
    71:  ("Série A",                  "Brazil",       "football"),
    128: ("Liga Profesional",         "Argentina",    "football"),
    # Basketball
    12:  ("NBA",                      "USA",          "basketball"),
}

CURRENT_FOOTBALL_SEASON = 2024   # 2024/25 season
CURRENT_NBA_SEASON      = 2024   # 2024-25 season


class APIFootballClient:
    def __init__(self):
        self.key = settings.api_football_key

    def _get(self, endpoint: str, params: dict) -> dict:
        if not self.key:
            return {}
        url = f"{_base()}/{endpoint}"
        logger.debug(f"API-Football GET {url} params={params}")
        try:
            with httpx.Client(timeout=25) as c:
                resp = c.get(url, params=params, headers=_headers())
                logger.debug(f"API-Football response {resp.status_code}: {resp.text[:500]}")
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500]
            if e.response.status_code == 429:
                logger.warning(f"API-Football rate limit hit — sleeping 60s. Body: {body}")
                time.sleep(60)
            else:
                logger.warning(f"API-Football [{endpoint}]: HTTP {e.response.status_code} — {body}")
        except Exception as e:
            logger.warning(f"API-Football [{endpoint}]: {e}")
        return {}

    # ── Fixture helpers ───────────────────────────────────────────────

    def _parse_fixtures(self, data: dict, league_id: int) -> list[dict]:
        league_name, country, sport_key = LEAGUES.get(league_id, ("Unknown League", "", "football"))
        events: list[dict] = []

        for fix in data.get("response", []):
            try:
                f      = fix.get("fixture", {})
                teams  = fix.get("teams",   {})
                goals  = fix.get("goals",   {})
                status = f.get("status", {}).get("short", "NS")

                home_name = teams.get("home", {}).get("name", "")
                away_name = teams.get("away", {}).get("name", "")
                if not home_name or not away_name:
                    continue

                date_str = f.get("date", "")
                try:
                    match_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    continue

                if status == "FT":
                    db_status  = "finished"
                    home_score = goals.get("home") or 0
                    away_score = goals.get("away") or 0
                    result     = "H" if home_score > away_score else ("A" if away_score > home_score else "D")
                elif status in ("NS", "TBD", "PST"):
                    db_status  = "scheduled"
                    home_score = away_score = result = None
                elif status in ("1H", "2H", "HT", "ET", "BT", "P", "LIVE"):
                    db_status  = "live"
                    home_score = goals.get("home") or 0
                    away_score = goals.get("away") or 0
                    result     = None
                elif status in ("CANC", "ABD", "AWD", "WO"):
                    continue   # Skip cancelled/abandoned
                else:
                    continue

                ext_id = f"af_{f['id']}"

                events.append({
                    "external_id": ext_id,
                    "sport":       sport_key,
                    "competition": league_name,
                    "country":     country,
                    "home_name":   home_name,
                    "away_name":   away_name,
                    "match_date":  match_date,
                    "status":      db_status,
                    "result":      result,
                    "home_score":  home_score,
                    "away_score":  away_score,
                    "odds":        [],
                })
            except Exception as e:
                logger.debug(f"Fixture parse error: {e}")

        return events

    # ── Public methods ────────────────────────────────────────────────

    def get_season_fixtures(self, league_id: int, season: int) -> list[dict]:
        """All fixtures for a league season (scheduled + finished)."""
        data = self._get("fixtures", {"league": league_id, "season": season})
        return self._parse_fixtures(data, league_id)

    def get_recent_results(self, league_id: int, last_n: int = 50) -> list[dict]:
        """Recently completed fixtures."""
        season = CURRENT_FOOTBALL_SEASON if league_id != 12 else CURRENT_NBA_SEASON
        data = self._get("fixtures", {
            "league":  league_id,
            "season":  season,
            "status":  "FT",
            "last":    last_n,
        })
        return self._parse_fixtures(data, league_id)

    def get_fixtures_by_date(self, date_str: str) -> list[dict]:
        """All fixtures on a given date (YYYY-MM-DD) across all leagues."""
        data = self._get("fixtures", {"date": date_str})
        events: list[dict] = []
        # We don't know league_id here, infer from response
        for fix in data.get("response", []):
            league_id = fix.get("league", {}).get("id", 0)
            if league_id in LEAGUES:
                parsed = self._parse_fixtures({"response": [fix]}, league_id)
                events.extend(parsed)
        return events

    def fetch_all_current_season(self) -> list[dict]:
        """
        Fetch ALL fixtures for every configured league in the current season.
        This gives the full season schedule (scheduled + played).
        """
        if not self.key:
            logger.warning("API_FOOTBALL_KEY not set — skipping full season fetch")
            return []

        all_events: list[dict] = []
        for league_id, (name, country, sport_key) in LEAGUES.items():
            season = CURRENT_FOOTBALL_SEASON if sport_key != "basketball" else CURRENT_NBA_SEASON
            logger.info(f"API-Football: {name} season {season}...")
            events = self.get_season_fixtures(league_id, season)
            all_events.extend(events)
            logger.info(f"  ✓ {len(events)} fixtures")
            time.sleep(0.6)   # Stay within rate limits

        logger.info(f"API-Football total: {len(all_events)} fixtures fetched")
        return all_events

    def fetch_results_last_n_days(self, days: int = 3) -> list[dict]:
        """
        Fetch recently completed fixtures across all leagues.
        Used by the result-resolution job every 2 hours.
        """
        if not self.key:
            return []

        all_events: list[dict] = []
        today = datetime.utcnow().date()
        for delta in range(days):
            date_str = (today - timedelta(days=delta)).strftime("%Y-%m-%d")
            events = self.get_fixtures_by_date(date_str)
            finished = [e for e in events if e["status"] == "finished"]
            all_events.extend(finished)
            time.sleep(0.4)

        logger.info(f"API-Football: fetched {len(all_events)} completed fixtures from last {days} days")
        return all_events
