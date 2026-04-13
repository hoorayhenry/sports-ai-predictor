"""
Load real ATP and WTA tennis match history from Jeff Sackmann's open dataset.
GitHub: https://github.com/JeffSackmann/tennis_atp
        https://github.com/JeffSackmann/tennis_wta

No API key required. Data is updated regularly throughout each season.
Covers 2020-2025 ATP + 2020-2024 WTA.
"""
from __future__ import annotations
import csv
import io
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger

ATP_BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
WTA_BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"

ATP_SEASONS = ["2020", "2021", "2022", "2023", "2024", "2025"]
WTA_SEASONS = ["2020", "2021", "2022", "2023", "2024"]

# Surface → competition suffix for better categorisation
SURFACE_LABELS = {
    "Hard":  "Hard Court",
    "Clay":  "Clay Court",
    "Grass": "Grass Court",
    "Carpet": "Indoor",
}


def _download(url: str) -> Optional[str]:
    try:
        with httpx.Client(timeout=30) as c:
            resp = c.get(url)
            if resp.status_code == 200 and len(resp.text) > 200:
                return resp.text
    except Exception as e:
        logger.debug(f"Tennis download error [{url}]: {e}")
    return None


def _parse_matches(content: str, tour: str) -> list[dict]:
    """
    Parse Jeff Sackmann ATP/WTA CSV.
    Key columns: tourney_id, tourney_name, surface, tourney_date,
                 winner_name, loser_name, score, round, best_of
    Winner is always treated as 'home' (H result).
    """
    events: list[dict] = []
    try:
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            winner = row.get("winner_name", "").strip()
            loser  = row.get("loser_name",  "").strip()
            if not winner or not loser:
                continue

            tourney_name = row.get("tourney_name", f"{tour} Tour").strip()
            surface      = row.get("surface", "Hard").strip()
            tourney_date = row.get("tourney_date", "").strip()
            score        = row.get("score", "").strip()
            tourney_id   = row.get("tourney_id", "").strip()
            match_num    = row.get("match_num", "0").strip()

            # Skip walkovers, retirements, byes
            if not score or any(x in score.upper() for x in ["W/O", "ABN", "DEF", "BYE", "RET"]):
                continue

            try:
                match_date = datetime.strptime(tourney_date, "%Y%m%d")
            except ValueError:
                continue

            surface_label = SURFACE_LABELS.get(surface, surface)
            competition   = f"{tourney_name} ({surface_label})"
            ext_id        = f"{tour.lower()}_{tourney_id}_{match_num}".replace(" ", "_").lower()[:128]

            events.append({
                "external_id":  ext_id,
                "sport":        "tennis",
                "competition":  competition,
                "country":      "International",
                "home_name":    winner,   # winner = home side (always wins)
                "away_name":    loser,
                "match_date":   match_date,
                "status":       "finished",
                "result":       "H",      # winner always H
                "home_score":   1,
                "away_score":   0,
                "odds":         [],
            })
    except Exception as e:
        logger.error(f"Tennis CSV parse error: {e}")
    return events


def fetch_all_tennis_historical() -> list[dict]:
    """Download ATP + WTA historical match data. Returns normalised event dicts."""
    all_events: list[dict] = []

    for season in ATP_SEASONS:
        url = f"{ATP_BASE}/atp_matches_{season}.csv"
        logger.info(f"Downloading ATP {season}...")
        content = _download(url)
        if content:
            events = _parse_matches(content, "ATP")
            all_events.extend(events)
            logger.info(f"  ✓ {len(events)} ATP matches for {season}")
        else:
            logger.debug(f"  ✗ No ATP data for {season}")

    for season in WTA_SEASONS:
        url = f"{WTA_BASE}/wta_matches_{season}.csv"
        logger.info(f"Downloading WTA {season}...")
        content = _download(url)
        if content:
            events = _parse_matches(content, "WTA")
            all_events.extend(events)
            logger.info(f"  ✓ {len(events)} WTA matches for {season}")
        else:
            logger.debug(f"  ✗ No WTA data for {season}")

    logger.info(f"Tennis total: {len(all_events)} historical matches")
    return all_events
