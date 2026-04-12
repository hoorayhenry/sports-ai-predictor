"""
Sportybet odds client — uses their internal REST API (no Playwright needed).
Sportybet's mobile app talks to public REST endpoints we can replicate.

Covers: Football, Basketball, Tennis, Table Tennis, American Football, Rugby,
        Volleyball, Cricket, Ice Hockey, and more.
"""
import time
from datetime import datetime
from typing import Optional
import httpx
from loguru import logger


BASE = "https://www.sportybet.com/api/ng/factsCenter"

SPORT_IDS = {
    "football":         "sr:sport:1",
    "basketball":       "sr:sport:2",
    "baseball":         "sr:sport:3",
    "ice_hockey":       "sr:sport:4",
    "tennis":           "sr:sport:5",
    "handball":         "sr:sport:6",
    "volleyball":       "sr:sport:23",
    "american_football":"sr:sport:16",
    "table_tennis":     "sr:sport:20",
    "cricket":          "sr:sport:21",
    "rugby":            "sr:sport:12",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Accept": "application/json",
    "Origin": "https://www.sportybet.com",
    "Referer": "https://www.sportybet.com/ng/",
}


class SportybetClient:
    def __init__(self, timeout: int = 20):
        self.timeout = timeout

    def _get(self, path: str, params: dict = None) -> Optional[dict]:
        url = f"{BASE}{path}"
        try:
            with httpx.Client(timeout=self.timeout, headers=HEADERS, follow_redirects=True) as c:
                resp = c.get(url, params=params or {})
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning(f"Sportybet API error [{path}]: {e}")
            return None

    def get_matches(self, sport_key: str = "football", hours_ahead: int = 72) -> list[dict]:
        """Fetch upcoming + live matches for a sport."""
        sport_id = SPORT_IDS.get(sport_key)
        if not sport_id:
            return []

        params = {
            "sportId": sport_id,
            "marketId": "1_0,1_1,1_2,18_6",   # 1X2, both teams score, over/under
            "hours": hours_ahead,
            "_t": int(time.time() * 1000),
        }
        data = self._get("/pcoupons", params)
        if not data:
            return []

        matches = []
        for tournament in data.get("data", {}).get("tournaments", []):
            comp_name = tournament.get("name", "")
            country = tournament.get("category", {}).get("name", "")
            for event in tournament.get("events", []):
                parsed = self._parse_event(event, sport_key, comp_name, country)
                if parsed:
                    matches.append(parsed)
        return matches

    def get_all_sports(self, hours_ahead: int = 48) -> list[dict]:
        """Fetch matches across all configured sports."""
        all_matches = []
        for sport_key in SPORT_IDS:
            logger.info(f"Sportybet: fetching {sport_key}...")
            matches = self.get_matches(sport_key, hours_ahead)
            all_matches.extend(matches)
            time.sleep(0.4)
        logger.info(f"Sportybet: total {len(all_matches)} matches fetched")
        return all_matches

    @staticmethod
    def _parse_event(event: dict, sport_key: str, comp_name: str, country: str) -> Optional[dict]:
        try:
            home = event.get("homeTeamName") or event.get("home", {}).get("name", "")
            away = event.get("awayTeamName") or event.get("away", {}).get("name", "")
            if not home or not away:
                return None

            event_id = str(event.get("eventId") or event.get("id", ""))
            start_time = event.get("estimateStartTime") or event.get("startTime")
            if start_time:
                match_date = datetime.utcfromtimestamp(int(start_time) / 1000)
            else:
                match_date = datetime.utcnow()

            odds_list = []
            for market in event.get("markets", []):
                market_id = str(market.get("id", ""))
                market_name = market.get("name", "")
                for outcome in market.get("outcomes", []):
                    o_name = outcome.get("desc", outcome.get("name", ""))
                    o_odds = outcome.get("odds", outcome.get("price"))
                    if not o_odds:
                        continue
                    try:
                        price = float(o_odds)
                    except (ValueError, TypeError):
                        continue
                    if price < 1.01:
                        continue

                    # Normalize outcome names
                    n = o_name.lower()
                    if n in ("1", "home", "w1") or home.lower()[:5] in n:
                        outcome_key = "home"
                    elif n in ("2", "away", "w2") or away.lower()[:5] in n:
                        outcome_key = "away"
                    elif n in ("x", "draw", "tie"):
                        outcome_key = "draw"
                    elif "over" in n:
                        outcome_key = "over"
                    elif "under" in n:
                        outcome_key = "under"
                    elif n in ("yes", "gg"):
                        outcome_key = "yes"
                    elif n in ("no", "ng"):
                        outcome_key = "no"
                    else:
                        outcome_key = n

                    # Map market names
                    if market_id in ("1_0", "1") or "match result" in market_name.lower() or "1x2" in market_name.lower():
                        mkt = "h2h"
                    elif "over" in market_name.lower() or "goals" in market_name.lower() or market_id == "18_6":
                        mkt = "totals"
                    elif "both" in market_name.lower() or "btts" in market_name.lower():
                        mkt = "btts"
                    elif "handicap" in market_name.lower():
                        mkt = "handicap"
                    else:
                        mkt = "h2h"

                    odds_list.append({
                        "bookmaker": "sportybet",
                        "market": mkt,
                        "outcome": outcome_key,
                        "price": price,
                        "point": outcome.get("specialOddsValue"),
                    })

            return {
                "external_id": f"sb_{event_id}",
                "sport": sport_key,
                "competition": comp_name,
                "country": country,
                "home_name": home,
                "away_name": away,
                "match_date": match_date,
                "status": "live" if event.get("status") == "LIVE" else "scheduled",
                "odds": odds_list,
            }
        except Exception as e:
            logger.debug(f"Event parse error: {e}")
            return None
