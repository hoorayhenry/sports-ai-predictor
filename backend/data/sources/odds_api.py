"""Odds API fallback client — supplements Sportybet when key is configured."""
import time
from datetime import datetime
from typing import Optional
import httpx
from loguru import logger
from config.settings import get_settings

settings = get_settings()
BASE = "https://api.the-odds-api.com/v4"

SPORT_KEYS = [
    # Football
    "soccer_epl", "soccer_spain_la_liga", "soccer_germany_bundesliga",
    "soccer_italy_serie_a", "soccer_france_ligue_one", "soccer_uefa_champs_league",
    "soccer_uefa_europa_league", "soccer_nigeria_npfl", "soccer_africa_cup_of_nations",
    "soccer_conmebol_copa_libertadores", "soccer_brazil_campeonato",
    "soccer_argentina_primera_division", "soccer_mls",
    # Basketball
    "basketball_nba", "basketball_ncaab", "basketball_euroleague",
    # Tennis
    "tennis_atp_french_open", "tennis_wta_french_open",
    "tennis_atp_us_open", "tennis_wta_us_open",
    "tennis_atp_wimbledon", "tennis_atp_australian_open",
    # American Football
    "americanfootball_nfl",
]

SPORT_CATEGORY = {
    "soccer_": "football", "basketball_": "basketball",
    "tennis_": "tennis", "americanfootball_": "american_football",
}


class OddsAPIClient:
    def __init__(self):
        self.key = settings.odds_api_key
        self.remaining = 500

    def fetch_all(self) -> list[dict]:
        if not self.key:
            return []
        all_events = []
        for sport_key in SPORT_KEYS:
            sport_cat = next((v for k, v in SPORT_CATEGORY.items() if sport_key.startswith(k)), "other")
            events = self._get_odds(sport_key, sport_cat)
            all_events.extend(events)
            time.sleep(0.3)
        return all_events

    def _get_odds(self, sport_key: str, sport_cat: str) -> list[dict]:
        try:
            with httpx.Client(timeout=15) as c:
                resp = c.get(f"{BASE}/sports/{sport_key}/odds", params={
                    "apiKey": self.key,
                    "regions": "eu,uk,us",
                    "markets": "h2h,totals,btts",
                    "oddsFormat": "decimal",
                })
                self.remaining = int(resp.headers.get("x-requests-remaining", self.remaining))
                resp.raise_for_status()
                events = resp.json()
        except Exception as e:
            logger.debug(f"Odds API [{sport_key}]: {e}")
            return []

        results = []
        for ev in events:
            odds_list = []
            home = ev.get("home_team", "")
            away = ev.get("away_team", "")
            for bm in ev.get("bookmakers", []):
                for mkt in bm.get("markets", []):
                    for o in mkt.get("outcomes", []):
                        n = o.get("name", "").lower()
                        if home.lower()[:4] in n or n == "home":
                            ok = "home"
                        elif away.lower()[:4] in n or n == "away":
                            ok = "away"
                        elif "draw" in n or "tie" in n:
                            ok = "draw"
                        elif "over" in n:
                            ok = "over"
                        elif "under" in n:
                            ok = "under"
                        elif n in ("yes",):
                            ok = "yes"
                        elif n in ("no",):
                            ok = "no"
                        else:
                            ok = n
                        odds_list.append({
                            "bookmaker": bm["key"],
                            "market": mkt["key"],
                            "outcome": ok,
                            "price": float(o["price"]),
                            "point": o.get("point"),
                        })

            try:
                start = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                continue

            results.append({
                "external_id": f"oa_{ev['id']}",
                "sport": sport_cat,
                "competition": ev.get("sport_title", sport_key),
                "country": "",
                "home_name": home,
                "away_name": away,
                "match_date": start,
                "status": "scheduled",
                "odds": odds_list,
            })
        return results
