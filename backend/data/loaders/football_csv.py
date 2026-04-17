"""
Download and ingest real historical football data from football-data.co.uk.
Free — no API key required. Updated throughout the season.

Leagues covered:
  E0  Premier League (England)
  SP1 La Liga (Spain)
  D1  Bundesliga (Germany)
  I1  Serie A (Italy)
  F1  Ligue 1 (France)
  N1  Eredivisie (Netherlands)
  P1  Primeira Liga (Portugal)
  T1  Süper Lig (Turkey)
  SC0 Scottish Premiership
  B1  First Division A (Belgium)
  G1  Super League (Greece)
  E1  Championship (England)

Seasons: 2021/22, 2022/23, 2023/24, 2024/25
"""
from __future__ import annotations
import csv
import io
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger

BASE_URL = "https://www.football-data.co.uk/mmz4281"

LEAGUES: dict[str, tuple[str, str]] = {
    "E0":  ("Premier League",        "England"),
    "SP1": ("La Liga",               "Spain"),
    "D1":  ("Bundesliga",            "Germany"),
    "I1":  ("Serie A",               "Italy"),
    "F1":  ("Ligue 1",               "France"),
    "N1":  ("Eredivisie",            "Netherlands"),
    "P1":  ("Primeira Liga",         "Portugal"),
    "T1":  ("Süper Lig",             "Turkey"),
    "SC0": ("Scottish Premiership",  "Scotland"),
    "B1":  ("First Division A",      "Belgium"),
    "G1":  ("Super League",          "Greece"),
    "E1":  ("Championship",          "England"),
}

SEASONS = ["1718", "1819", "1920", "2021", "2122", "2223", "2324", "2425"]


def _parse_date(s: str) -> Optional[datetime]:
    s = s.strip()
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _safe_float(val: str) -> Optional[float]:
    try:
        v = float(val)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def _download_csv(season: str, league_code: str) -> Optional[str]:
    url = f"{BASE_URL}/{season}/{league_code}.csv"
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as c:
            resp = c.get(url)
            if resp.status_code == 200 and len(resp.text) > 100:
                return resp.text
    except Exception as e:
        logger.debug(f"CSV download failed [{league_code} {season}]: {e}")
    return None


def _parse_csv(content: str, league_name: str, country: str) -> list[dict]:
    events: list[dict] = []
    try:
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            home = row.get("HomeTeam", "").strip()
            away = row.get("AwayTeam", "").strip()
            if not home or not away:
                continue

            match_date = _parse_date(row.get("Date", ""))
            if not match_date:
                continue

            ftr = row.get("FTR", "").strip().upper()
            if ftr not in ("H", "D", "A"):
                continue  # Match not yet played or abandoned

            try:
                home_score = int(float(row.get("FTHG") or row.get("HG") or 0))
                away_score = int(float(row.get("FTAG") or row.get("AG") or 0))
            except (ValueError, TypeError):
                continue

            # Collect real odds from multiple bookmakers in the CSV
            odds_list: list[dict] = []
            for bm, hk, dk, ak in [
                ("bet365",      "B365H", "B365D", "B365A"),
                ("pinnacle",    "PSH",   "PSD",   "PSA"),
                ("williamhill", "WHH",   "WHD",   "WHA"),
                ("betway",      "BWH",   "BWD",   "BWA"),
                ("market_avg",  "AvgH",  "AvgD",  "AvgA"),
                ("max_odds",    "MaxH",  "MaxD",  "MaxA"),
            ]:
                h_o = _safe_float(row.get(hk, ""))
                d_o = _safe_float(row.get(dk, ""))
                a_o = _safe_float(row.get(ak, ""))
                if h_o and h_o > 1.0:
                    odds_list.append({"bookmaker": bm, "market": "h2h", "outcome": "home", "price": h_o, "point": None})
                if d_o and d_o > 1.0:
                    odds_list.append({"bookmaker": bm, "market": "h2h", "outcome": "draw", "price": d_o, "point": None})
                if a_o and a_o > 1.0:
                    odds_list.append({"bookmaker": bm, "market": "h2h", "outcome": "away", "price": a_o, "point": None})

            # Over/Under 2.5
            for bm, ok, uk in [
                ("bet365",     "B365>2.5", "B365<2.5"),
                ("market_avg", "Avg>2.5",  "Avg<2.5"),
                ("max_odds",   "Max>2.5",  "Max<2.5"),
            ]:
                o_o = _safe_float(row.get(ok, ""))
                u_o = _safe_float(row.get(uk, ""))
                if o_o and o_o > 1.0:
                    odds_list.append({"bookmaker": bm, "market": "totals", "outcome": "over", "price": o_o, "point": 2.5})
                if u_o and u_o > 1.0:
                    odds_list.append({"bookmaker": bm, "market": "totals", "outcome": "under", "price": u_o, "point": 2.5})

            # BTTS (Both Teams To Score)
            for bm, yk, nk in [
                ("bet365",     "B365CH", "B365CA"),  # Mapping varies by CSV version
                ("market_avg", "AvgCH",  "AvgCA"),
            ]:
                y_o = _safe_float(row.get(yk, ""))
                n_o = _safe_float(row.get(nk, ""))
                if y_o and 1.0 < y_o < 5.0:
                    odds_list.append({"bookmaker": bm, "market": "btts", "outcome": "yes", "price": y_o, "point": None})
                if n_o and 1.0 < n_o < 5.0:
                    odds_list.append({"bookmaker": bm, "market": "btts", "outcome": "no", "price": n_o, "point": None})

            # ── Shot + card + referee data ──────────────────────────
            def _si(key: str) -> int | None:
                """Safe int from CSV cell."""
                try:
                    v = int(float(row.get(key) or ""))
                    return v if v >= 0 else None
                except (ValueError, TypeError):
                    return None

            extra: dict = {}
            # Shots
            for dest, keys in [
                ("hs",  ["HS"]),
                ("as_", ["AS"]),
                ("hst", ["HST"]),
                ("ast", ["AST"]),
                # Yellow / Red cards
                ("hy",  ["HY"]),
                ("ay",  ["AY"]),
                ("hr",  ["HR"]),
                ("ar",  ["AR"]),
            ]:
                for k in keys:
                    v = _si(k)
                    if v is not None:
                        extra[dest] = v
                        break
            # Referee
            ref = row.get("Referee", "").strip()
            if ref:
                extra["ref"] = ref

            date_slug = match_date.strftime("%Y%m%d")
            h_slug = home.replace(" ", "_").lower()[:20]
            a_slug = away.replace(" ", "_").lower()[:20]
            ext_id = f"fdc_{league_name.replace(' ', '_').lower()[:15]}_{date_slug}_{h_slug}_{a_slug}"[:128]

            events.append({
                "external_id":  ext_id,
                "sport":        "football",
                "competition":  league_name,
                "country":      country,
                "home_name":    home,
                "away_name":    away,
                "match_date":   match_date,
                "status":       "finished",
                "result":       ftr,
                "home_score":   home_score,
                "away_score":   away_score,
                "odds":         odds_list,
                "extra":        extra,          # shots / cards / referee
            })
    except Exception as e:
        logger.error(f"CSV parse error for {league_name}: {e}")
    return events


def download_all_historical(seasons: list[str] | None = None) -> list[dict]:
    """
    Download CSV data for all configured leagues and seasons.
    Returns normalized event dicts ready for ingest_events().
    """
    seasons = seasons or SEASONS
    all_events: list[dict] = []

    for league_code, (league_name, country) in LEAGUES.items():
        for season in seasons:
            logger.info(f"Downloading {league_name} {season}...")
            content = _download_csv(season, league_code)
            if content:
                events = _parse_csv(content, league_name, country)
                all_events.extend(events)
                logger.info(f"  ✓ {len(events)} matches — {league_name} {season}")
            else:
                logger.debug(f"  ✗ No data — {league_name} {season}")

    logger.info(f"Football CSV total: {len(all_events)} historical matches")
    return all_events
