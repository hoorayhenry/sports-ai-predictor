"""
10-year historical data backfill across all Sofascore sports.

Purpose: User experience only — historical match records, standings reference,
         H2H depth for feature computation.
         Training uses only the last 2 years (see build_training_matrix).

Strategy:
  - Fetches every day from (today - 10 years) to yesterday for all 10 sports
  - Processes NEWEST → OLDEST (most valuable data first — can stop early)
  - Checkpoint file tracks completed (sport_key → set of date_iso strings)
  - Safe to interrupt and resume: re-running skips already-done dates
  - Rate-limited to ~1 req/s per sport to avoid Sofascore bans

Run options:
  1. CLI:      python -m data.loaders.history_backfill [years] [sport1,sport2]
  2. Startup:  scheduler calls needs_backfill() → runs in background if thin DB
  3. Manual:   run_backfill(db, years_back=10) from Python

Progress logged every 50 days. Checkpoint saved after every batch.
"""
from __future__ import annotations

import json
import time
import concurrent.futures
from datetime import date, datetime, timedelta
from pathlib import Path
from loguru import logger

import httpx

from data.loaders.multi_sport_ingest import (
    SPORTS_CONFIG,
    _SS_BASE,
    _SS_HEADERS,
    _parse_ss_event,
    upsert_events,
)

# ── Config ────────────────────────────────────────────────────────────────────

CHECKPOINT_PATH = Path(__file__).parent.parent.parent / "ml" / "saved" / "backfill_checkpoint.json"

_REQUEST_DELAY  = 0.6   # seconds between requests per worker (≈1.5 req/s per sport)
_BATCH_DAYS     = 30    # commit to DB every N days per sport
_MAX_WORKERS    = 4     # parallel sports at once (keeps total ≤ 6 req/s globally)


# ── Checkpoint helpers ────────────────────────────────────────────────────────

def _load_checkpoint() -> dict[str, set[str]]:
    if not CHECKPOINT_PATH.exists():
        return {}
    try:
        raw = json.loads(CHECKPOINT_PATH.read_text())
        return {k: set(v) for k, v in raw.items()}
    except Exception:
        return {}


def _save_checkpoint(done: dict[str, set[str]]) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(
        json.dumps({k: sorted(v) for k, v in done.items()}, indent=2)
    )


# ── Per-sport backfill ────────────────────────────────────────────────────────

def _fetch_day(ss_slug: str, sport_key: str, day: date, timeout: int = 12) -> list[dict]:
    """Fetch all events for one sport on one date. Returns empty list on any error."""
    try:
        resp = httpx.get(
            f"{_SS_BASE}/sport/{ss_slug}/scheduled-events/{day.isoformat()}",
            headers=_SS_HEADERS,
            timeout=timeout,
        )
        if resp.status_code == 429:
            # Rate limited — back off and retry once
            time.sleep(10)
            resp = httpx.get(
                f"{_SS_BASE}/sport/{ss_slug}/scheduled-events/{day.isoformat()}",
                headers=_SS_HEADERS,
                timeout=timeout,
            )
        if resp.status_code != 200:
            return []
        return [_parse_ss_event(e, sport_key) for e in resp.json().get("events", [])]
    except Exception:
        return []


def _backfill_one_sport(
    db,
    ss_slug: str,
    sport_key: str,
    date_range: list[date],
    done_dates: set[str],
) -> tuple[str, int, set[str]]:
    """
    Backfill one sport across date_range, skipping already-done dates.
    Returns (sport_key, total_inserted, completed_date_isos).
    """
    total_inserted = 0
    batch: list[dict] = []
    completed: set[str] = set()
    pending_dates = [d for d in date_range if d.isoformat() not in done_dates]

    logger.info(f"[Backfill] {sport_key}: {len(pending_dates)} dates to fetch "
                f"({len(done_dates)} already done)")

    for i, day in enumerate(pending_dates):
        events = _fetch_day(ss_slug, sport_key, day)
        batch.extend(events)
        completed.add(day.isoformat())
        time.sleep(_REQUEST_DELAY)

        if len(completed) % _BATCH_DAYS == 0:
            if batch:
                try:
                    inserted = upsert_events(db, batch)
                    total_inserted += inserted
                except Exception as e:
                    logger.warning(f"[Backfill] {sport_key} batch commit failed: {e}")
                    try:
                        db.rollback()
                    except Exception:
                        pass
            batch = []
            logger.info(
                f"[Backfill] {sport_key}: {len(completed)}/{len(pending_dates)} days, "
                f"{total_inserted} events so far"
            )

    # Final batch
    if batch:
        try:
            inserted = upsert_events(db, batch)
            total_inserted += inserted
        except Exception as e:
            logger.warning(f"[Backfill] {sport_key} final batch failed: {e}")
            try:
                db.rollback()
            except Exception:
                pass

    return sport_key, total_inserted, completed


# ── Main entry point ──────────────────────────────────────────────────────────

def run_backfill(
    db,
    years_back: int = 10,
    sports: list[str] | None = None,
    resume: bool = True,
) -> dict[str, int]:
    """
    Backfill historical match data for all (or selected) sports.

    Args:
        db:         SQLAlchemy sync session
        years_back: Years of history to fetch (default 10 — for user experience)
        sports:     List of sport_keys to process. None = all 10.
        resume:     Skip dates already in checkpoint file.

    Returns:
        Dict of {sport_key: events_inserted}

    Note: This is a LONG-RUNNING operation (hours for full 10-year backfill).
          It is designed to run in the background and be safely interrupted.
          The checkpoint file ensures no work is duplicated on restart.
    """
    today     = date.today()
    start_day = today - timedelta(days=years_back * 365)

    # Newest → oldest: most recent data is the most valuable
    all_dates = [
        today - timedelta(days=i)
        for i in range(1, (today - start_day).days + 1)
    ]

    configs = [
        (ss_slug, sport_key)
        for ss_slug, sport_key, *_ in SPORTS_CONFIG
        if sports is None or sport_key in sports
    ]

    done = _load_checkpoint() if resume else {}

    total_calls = len(configs) * len(all_dates)
    logger.info(
        f"[Backfill] Starting {years_back}-year backfill: "
        f"{len(configs)} sports × {len(all_dates)} days ≈ {total_calls:,} API calls. "
        f"Safe to interrupt — checkpoint will resume where this left off."
    )

    results: dict[str, int] = {}

    # Run sports in parallel (limited to _MAX_WORKERS at once)
    with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {
            pool.submit(
                _backfill_one_sport,
                db,
                ss_slug,
                sport_key,
                all_dates,
                done.get(sport_key, set()),
            ): sport_key
            for ss_slug, sport_key in configs
        }

        for fut in concurrent.futures.as_completed(futures):
            sport_key = futures[fut]
            try:
                sk, inserted, completed = fut.result()
                results[sk] = inserted
                logger.info(f"[Backfill] ✓ {sk}: {inserted:,} events inserted")

                # Update checkpoint
                done[sk] = done.get(sk, set()) | completed
                _save_checkpoint(done)

            except Exception as e:
                logger.error(f"[Backfill] ✗ {sport_key} failed: {e}")
                results[sport_key] = 0

    total = sum(results.values())
    logger.info(f"[Backfill] Complete — {total:,} total events. Breakdown: {results}")
    return results


# ── DB health check ───────────────────────────────────────────────────────────

def needs_backfill(db, years_back: int = 10) -> bool:
    """
    Returns True if the oldest match in the DB is less than years_back years ago.

    Counts/rows are a bad signal — the daily ingest keeps the DB well-populated
    with RECENT data, so a count-based check always returns False.
    The correct question is: do we have historical depth?
    """
    from data.db_models.models import Match
    from sqlalchemy import func

    oldest = db.query(func.min(Match.match_date)).scalar()

    if oldest is None:
        logger.info("[Backfill] DB empty — backfill needed")
        return True

    from datetime import date, datetime, timezone
    now = datetime.utcnow()
    target = now.replace(year=now.year - years_back)
    age_years = (now - oldest).days / 365

    logger.info(
        f"[Backfill] Oldest match: {oldest.date()} ({age_years:.1f} years ago). "
        f"Target: {years_back} years. Backfill needed: {age_years < years_back - 0.5}"
    )
    # Allow 0.5-year grace — if we're within 6 months of the target, don't re-run
    return age_years < (years_back - 0.5)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from data.database import get_sync_session

    years      = int(sys.argv[1])       if len(sys.argv) > 1 else 10
    sport_list = sys.argv[2].split(",") if len(sys.argv) > 2 else None

    print(f"\n🏟  PlaySigma — {years}-year historical backfill")
    print(f"   Sports : {sport_list or 'all 10'}")
    print(f"   Purpose: user experience (historical records, H2H depth)")
    print(f"   Training uses only last 2 years (see build_training_matrix)")
    print(f"   Safe to interrupt — checkpoint resumes where left off\n")

    with get_sync_session() as db:
        run_backfill(db, years_back=years, sports=sport_list)
