"""Odds API client — fetches real upcoming fixtures with odds."""
import time
from datetime import datetime
import httpx
from loguru import logger
from config.settings import get_settings

settings = get_settings()
BASE = "https://api.the-odds-api.com/v4"

SPORT_CATEGORY = {
    "soccer_":          "football",
    "basketball_":      "basketball",
    "tennis_":          "tennis",
    "americanfootball_":"american_football",
    "icehockey_":       "ice_hockey",
    "baseball_":        "baseball",
    "rugbyleague_":     "rugby",
    "rugbyunion_":      "rugby",
    "volleyball_":      "volleyball",
    "cricket_":         "cricket",
}

# Markets that work for each sport category (btts/totals cause 422 on many sports)
SPORT_MARKETS = {
    "football":         "h2h,totals",
    "basketball":       "h2h,spreads",
    "tennis":           "h2h",
    "american_football":"h2h,spreads",
    "ice_hockey":       "h2h,totals",
    "baseball":         "h2h,spreads",
    "rugby":            "h2h",
    "volleyball":       "h2h",
    "cricket":          "h2h",
}


class OddsAPIClient:
    def __init__(self):
        self.key = settings.odds_api_key
        self.remaining = 500

    def _active_sports(self) -> list[dict]:
        """Fetch currently active (in-season) sports from the API."""
        try:
            with httpx.Client(timeout=15) as c:
                resp = c.get(f"{BASE}/sports", params={"apiKey": self.key, "all": "false"})
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning(f"Odds API /sports: {e}")
            return []

    def fetch_all(self) -> list[dict]:
        if not self.key:
            return []

        active = self._active_sports()
        if not active:
            logger.warning("Odds API: no active sports returned")
            return []

        logger.info(f"Odds API: {len(active)} active sports found")
        all_events = []
        for sport in active:
            sport_key = sport.get("key", "")
            sport_cat = next((v for k, v in SPORT_CATEGORY.items() if sport_key.startswith(k)), "other")
            if sport_cat == "other":
                continue
            markets = SPORT_MARKETS.get(sport_cat, "h2h")
            events = self._get_odds(sport_key, sport_cat, markets)
            if events:
                logger.info(f"  {sport_key}: {len(events)} upcoming matches")
            all_events.extend(events)
            time.sleep(0.25)

        logger.info(f"Odds API total: {len(all_events)} upcoming matches")
        return all_events

    def _get_odds(self, sport_key: str, sport_cat: str, markets: str = "h2h") -> list[dict]:
        try:
            with httpx.Client(timeout=15) as c:
                resp = c.get(f"{BASE}/sports/{sport_key}/odds", params={
                    "apiKey": self.key,
                    "regions": "eu,uk,us",
                    "markets": markets,
                    "oddsFormat": "decimal",
                })
                remaining = resp.headers.get("x-requests-remaining")
                if remaining:
                    self.remaining = int(remaining)
                    if self.remaining < 20:
                        logger.warning(f"Odds API: only {self.remaining} requests remaining this month!")
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
                        elif n == "yes":
                            ok = "yes"
                        elif n == "no":
                            ok = "no"
                        else:
                            ok = n
                        odds_list.append({
                            "bookmaker": bm["key"],
                            "market":    mkt["key"],
                            "outcome":   ok,
                            "price":     float(o["price"]),
                            "point":     o.get("point"),
                        })

            try:
                start = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                continue

            results.append({
                "external_id": f"oa_{ev['id']}",
                "sport":       sport_cat,
                "competition": ev.get("sport_title", sport_key),
                "country":     "",
                "home_name":   home,
                "away_name":   away,
                "match_date":  start,
                "status":      "scheduled",
                "odds":        odds_list,
            })
        return results
