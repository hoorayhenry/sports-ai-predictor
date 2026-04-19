"""
API-Football Odds Fetcher
=========================
Fetches pre-match odds for upcoming fixtures across 20+ market types.

Markets returned (mapped to our internal keys):
  Match Result       → market="h2h"         outcome=home/draw/away
  Double Chance      → market="double_chance" outcome=home_draw/away_draw/home_away
  Asian Handicap     → market="asian_handicap" outcome=home/away  point=handicap_line
  Goals Over/Under   → market="totals"       outcome=over/under  point=1.5/2.5/3.5/4.5
  Both Teams Score   → market="btts"         outcome=yes/no
  Win to Nil (Home)  → market="win_to_nil"   outcome=home/away
  Clean Sheet        → market="clean_sheet"  outcome=home/away   (yes/no implied)
  HT/FT             → market="ht_ft"         outcome=home_home/draw_draw/away_away etc.

API-Football endpoint: GET /odds
  Params: league, season, fixture (one of these required)
  Rate limit: 100 req/day (free tier) | unlimited (paid)

This fetcher uses the fixture-level endpoint for maximum precision.
We batch upcoming matches (next 7 days) and fetch odds per fixture.
"""
from __future__ import annotations
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from config.settings import get_settings
from data.sources.api_football import _base, _headers, LEAGUES

settings = get_settings()

# ── Market ID → internal market key + outcome normaliser ─────────────────────
#
# API-Football returns numeric bet IDs. These are the ones we care about.
# Full list: https://www.api-football.com/documentation-v3#tag/Odds/operation/get-odds
#
# Format: BET_ID → (internal_market_key, outcome_normaliser_fn)
#   outcome_normaliser_fn(raw_name: str, home: str, away: str) → str

def _norm_result(n: str, home: str, away: str) -> str:
    """1X2 match result."""
    nl = n.lower()
    if "home" in nl or nl == home.lower()[:6]:
        return "home"
    if "away" in nl or nl == away.lower()[:6]:
        return "away"
    return "draw"

def _norm_dc(n: str, home: str, away: str) -> str:
    """Double Chance: Home/Draw → home_draw, Draw/Away → away_draw, Home/Away → home_away."""
    nl = n.lower()
    if "home" in nl and "draw" in nl:
        return "home_draw"
    if "away" in nl and "draw" in nl:
        return "away_draw"
    if "home" in nl and "away" in nl:
        return "home_away"
    return nl

def _norm_over_under(n: str, home: str, away: str) -> str:
    return "over" if "over" in n.lower() else "under"

def _norm_btts(n: str, home: str, away: str) -> str:
    return "yes" if "yes" in n.lower() else "no"

def _norm_home_away(n: str, home: str, away: str) -> str:
    nl = n.lower()
    if "home" in nl:
        return "home"
    if "away" in nl:
        return "away"
    return nl

def _norm_ht_ft(n: str, home: str, away: str) -> str:
    """Half-time/Full-time: normalise to ht_home/ft_home style."""
    return n.lower().replace("/", "_").replace(" ", "_")

# BET_ID → (internal_market_key, normaliser)
BET_MAP: dict[int, tuple[str, callable]] = {
    1:   ("h2h",             _norm_result),      # Match Winner
    2:   ("h2h",             _norm_result),      # Home/Away (no draw)
    3:   ("double_chance",   _norm_dc),           # Double Chance
    4:   ("h2h",             _norm_result),      # 1st Half Winner
    5:   ("double_chance",   _norm_dc),           # 1st Half Double Chance
    12:  ("btts",            _norm_btts),         # Both Teams Score
    13:  ("totals",          _norm_over_under),   # Goals Over/Under
    17:  ("totals",          _norm_over_under),   # 1st Half Goals Over/Under
    45:  ("btts",            _norm_btts),         # Both Teams Score - 1st Half
    55:  ("win_to_nil",      _norm_home_away),    # Win to Nil
    57:  ("clean_sheet",     _norm_home_away),    # Clean Sheet
    64:  ("asian_handicap",  _norm_home_away),    # Asian Handicap
    65:  ("asian_handicap",  _norm_home_away),    # Asian Handicap 1st Half
    68:  ("draw_no_bet",     _norm_home_away),    # Draw No Bet
    69:  ("draw_no_bet",     _norm_home_away),    # Draw No Bet 1st Half
    77:  ("total_goals",     _norm_over_under),   # Total Goals (exact bands — skip)
    78:  ("ht_ft",           _norm_ht_ft),        # Half Time / Full Time
    88:  ("total_corners",   _norm_over_under),   # Corner Over/Under (bonus signal)
}

# Markets we want to store (skip noisy/exact-guess ones)
WANTED_MARKETS = {
    "h2h", "double_chance", "btts", "totals",
    "win_to_nil", "clean_sheet", "asian_handicap",
    "draw_no_bet", "ht_ft",
}


# ── Core fetcher ──────────────────────────────────────────────────────────────

class APIFootballOddsClient:
    """
    Fetch pre-match odds from API-Football for all upcoming fixtures.

    Strategy:
      1. Identify fixtures in the next `days_ahead` days that have an
         external_id starting with "af_" (ingested via API-Football).
      2. Batch-fetch odds per fixture ID.
      3. Normalise and return a list of MatchOdds-compatible dicts.

    Rate limit budget: we skip fixtures already having fresh odds (<6 hours old)
    to conserve the 100 req/day free-tier quota.
    """

    def __init__(self):
        self.key = settings.api_football_key

    def _get(self, params: dict) -> dict:
        if not self.key:
            return {}
        url = f"{_base()}/odds"
        try:
            with httpx.Client(timeout=20) as c:
                resp = c.get(url, params=params, headers=_headers())
                if resp.status_code == 429:
                    logger.warning("API-Football odds: rate limit — sleeping 60s")
                    time.sleep(60)
                    return {}
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.debug(f"API-Football odds request failed: {e}")
            return {}

    def fetch_odds_for_fixture(
        self,
        fixture_id: int,
        home: str,
        away: str,
    ) -> list[dict]:
        """
        Fetch all odds for a single fixture. Returns list of normalised dicts:
          { market, outcome, price, point }
        """
        data = self._get({"fixture": fixture_id, "bookmaker": 8})  # 8 = Bet365 (widest coverage)
        if not data:
            # Retry without bookmaker filter to get any available bookmaker
            data = self._get({"fixture": fixture_id})

        rows = []
        for item in data.get("response", []):
            for bk in item.get("bookmakers", []):
                bookmaker_name = bk.get("name", "unknown").lower().replace(" ", "_")
                for bet in bk.get("bets", []):
                    bet_id = bet.get("id")
                    if bet_id not in BET_MAP:
                        continue
                    mkt_key, normaliser = BET_MAP[bet_id]
                    if mkt_key not in WANTED_MARKETS:
                        continue

                    for val in bet.get("values", []):
                        raw_name = val.get("value", "")
                        # API-Football encodes handicap lines as "Over 2.5", "Under 2.5"
                        # or for AH: "Home -1", "Away +1" — extract float point
                        point = _extract_point(raw_name)
                        outcome = normaliser(raw_name, home, away)

                        try:
                            price = float(val.get("odd", 0))
                        except (ValueError, TypeError):
                            continue
                        if price <= 1.0:
                            continue

                        rows.append({
                            "bookmaker": bookmaker_name,
                            "market":    mkt_key,
                            "outcome":   outcome,
                            "price":     round(price, 3),
                            "point":     point,
                        })

        return rows

    def fetch_upcoming_odds(
        self,
        db: Session,
        days_ahead: int = 7,
        max_fixtures: int = 80,
    ) -> dict[int, list[dict]]:
        """
        Return { match_db_id: [odds_dict, ...] } for upcoming matches.

        Only fetches matches with an API-Football external_id ("af_XXXXXX")
        and skips those that already have fresh odds from this source (<6h ago).
        """
        if not self.key:
            return {}

        from data.db_models.models import Match, MatchOdds
        from sqlalchemy import func

        cutoff    = datetime.utcnow() + timedelta(days=days_ahead)
        stale_at  = datetime.utcnow() - timedelta(hours=6)

        # Get upcoming AF matches
        matches = (
            db.query(Match)
            .filter(
                Match.status == "scheduled",
                Match.match_date >= datetime.utcnow(),
                Match.match_date <= cutoff,
                Match.external_id.like("af_%"),
            )
            .order_by(Match.match_date)
            .limit(max_fixtures)
            .all()
        )

        if not matches:
            logger.debug("API-Football odds: no upcoming AF matches found")
            return {}

        # Skip matches with fresh odds (conserve quota)
        fresh_ids = set(
            row[0] for row in db.query(MatchOdds.match_id)
            .filter(
                MatchOdds.match_id.in_([m.id for m in matches]),
                MatchOdds.recorded_at >= stale_at,
                MatchOdds.bookmaker.like("bet%"),  # AF bookmakers
            )
            .distinct()
            .all()
        )

        result: dict[int, list[dict]] = {}
        fetched = 0

        for m in matches:
            if m.id in fresh_ids:
                continue

            # Extract fixture_id from external_id "af_12345"
            try:
                fixture_id = int(m.external_id.split("_", 1)[1])
            except (IndexError, ValueError):
                continue

            home_name = m.home.name if m.home else ""
            away_name = m.away.name if m.away else ""

            odds = self.fetch_odds_for_fixture(fixture_id, home_name, away_name)
            if odds:
                result[m.id] = odds
                fetched += 1
                logger.debug(
                    f"  AF odds: {home_name} vs {away_name} — "
                    f"{len(odds)} price lines across {len({o['market'] for o in odds})} markets"
                )

            # Rate limit: 1 req per 0.7s keeps us well within 100/day on free tier
            time.sleep(0.7)

            # Hard cap to never burn quota in one run
            if fetched >= max_fixtures:
                break

        logger.info(
            f"API-Football odds: fetched {fetched} fixtures, "
            f"{sum(len(v) for v in result.values())} price lines total"
        )
        return result


# ── Point extraction helper ───────────────────────────────────────────────────

def _extract_point(raw: str) -> Optional[float]:
    """
    Extract the numeric line from strings like:
      "Over 2.5" → 2.5
      "Under 1.5" → 1.5
      "Home -1"   → -1.0
      "Away +0.5" → 0.5
      "Home"      → None
    """
    import re
    # Match signed or unsigned floats
    m = re.search(r'([+-]?\d+(?:\.\d+)?)', raw)
    if m:
        return float(m.group(1))
    return None


# ── Convenience: fetch + save in one call ─────────────────────────────────────

def fetch_and_save_af_odds(db: Session, days_ahead: int = 7) -> int:
    """
    Fetch API-Football odds for upcoming matches and persist to MatchOdds table.
    Returns total number of price lines saved.
    """
    from data.db_models.models import MatchOdds

    client = APIFootballOddsClient()
    odds_map = client.fetch_upcoming_odds(db, days_ahead=days_ahead)

    saved = 0
    for match_id, odds_list in odds_map.items():
        for o in odds_list:
            db.add(MatchOdds(
                match_id  = match_id,
                bookmaker = o["bookmaker"],
                market    = o["market"],
                outcome   = o["outcome"],
                price     = o["price"],
                point     = o.get("point"),
            ))
            saved += 1

    if saved:
        db.commit()
        logger.info(f"API-Football odds saved: {saved} price lines")

    return saved
