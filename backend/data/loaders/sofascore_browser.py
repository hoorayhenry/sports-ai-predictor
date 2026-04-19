"""
Sofascore browser-based fetcher using Playwright.

Why this exists:
  Python httpx has a different TLS fingerprint than a real browser.
  Sofascore's bot detection sees the server-side fingerprint and returns HTTP 403.
  Playwright launches a real Chromium browser — the TLS handshake is identical
  to a user visiting the site in Chrome. Sofascore cannot distinguish it.

  This is the server-side equivalent of what the frontend already does with
  browser-direct Sofascore calls.

Usage:
  with SofascoreBrowserFetcher() as fetcher:
      events = fetcher.fetch_day("cricket", "cricket", date(2026, 3, 15))
      events = fetcher.fetch_day("rugby",   "rugby",   date(2026, 3, 15))

  One browser instance is shared across all fetch_day() calls — reusing the
  session and cookies avoids repeated page loads and is much faster.

Sports that NEED this (no ESPN coverage):
  cricket, rugby, handball, volleyball, tennis (for non-ATP/WTA tournaments)

Sports already working via ESPN (don't need this for most data):
  basketball, baseball, american_football, ice_hockey
"""
from __future__ import annotations

import json
import time
import random
from datetime import date, datetime, timedelta
from loguru import logger

from data.loaders.multi_sport_ingest import _parse_ss_event, upsert_events, SPORTS_CONFIG


# Sports that have no ESPN coverage and need browser fetching
BROWSER_ONLY_SPORTS = {
    "cricket":    "cricket",
    "rugby":      "rugby",
    "handball":   "handball",
    "volleyball": "volleyball",
    "tennis":     "tennis",     # Sofascore has broader tennis coverage than ESPN
}

_SS_API = "https://api.sofascore.com/api/v1"
_SS_HOME = "https://www.sofascore.com/"


class SofascoreBrowserFetcher:
    """
    Context-manager that owns one Playwright Chromium browser for the
    lifetime of a backfill / ingestion run.

    The browser visits sofascore.com once on startup to acquire session
    cookies, then all subsequent API calls are made via page.evaluate()
    which runs fetch() inside the browser's JS context — same fingerprint,
    same cookies, same headers that a real user would send.
    """

    def __init__(self, headless: bool = True, slow_mo: int = 0):
        self._headless  = headless
        self._slow_mo   = slow_mo
        self._playwright = None
        self._browser    = None
        self._context    = None
        self._page       = None

    # ── Context manager ───────────────────────────────────────────────

    def __enter__(self) -> "SofascoreBrowserFetcher":
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless = self._headless,
            slow_mo  = self._slow_mo,
            args     = ["--no-sandbox", "--disable-dev-shm-usage"],
        )
        self._context = self._browser.new_context(
            user_agent = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport         = {"width": 1280, "height": 800},
            locale           = "en-US",
            timezone_id      = "Europe/London",
            extra_http_headers = {
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            },
        )
        self._page = self._context.new_page()
        self._warm_up()
        return self

    def __exit__(self, *_):
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass

    # ── Warm-up: visit the main page once to get session cookies ─────

    def _warm_up(self):
        """
        Navigate to sofascore.com so the browser picks up session cookies,
        CF clearance tokens, and any JS-set headers that the API expects.
        """
        try:
            logger.info("[BrowserFetcher] Warming up — visiting sofascore.com...")
            self._page.goto(_SS_HOME, wait_until="domcontentloaded", timeout=30_000)
            # Small pause to let any client-side JS run
            time.sleep(2)
            logger.info("[BrowserFetcher] Warm-up done.")
        except Exception as e:
            logger.warning(f"[BrowserFetcher] Warm-up navigation failed: {e} — continuing anyway")

    # ── Core fetch ────────────────────────────────────────────────────

    def fetch_day(self, ss_slug: str, sport_key: str, day: date, retries: int = 2) -> list[dict]:
        """
        Fetch all events for a sport on a given date.

        Strategy: navigate the browser directly to the API URL.
        This uses the browser's full HTTP stack (real TLS fingerprint + cookies
        from the warm-up visit to sofascore.com), bypassing the 403 that httpx
        gets. No CORS issues because the browser is making a first-party request.

        Returns a list of normalised event dicts (same format as multi_sport_ingest).
        """
        url = f"{_SS_API}/sport/{ss_slug}/scheduled-events/{day.isoformat()}"

        for attempt in range(retries + 1):
            try:
                resp = self._page.goto(url, wait_until="domcontentloaded", timeout=15_000)

                if resp is None or resp.status >= 400:
                    status = resp.status if resp else "no-response"
                    if attempt < retries:
                        wait = (attempt + 1) * 3 + random.uniform(1, 2)
                        logger.debug(f"[BrowserFetcher] {sport_key}/{day} HTTP {status} — retry in {wait:.1f}s")
                        time.sleep(wait)
                        # Re-warm if we get a 403 — cookies may have expired
                        if status == 403:
                            self._warm_up()
                        continue
                    logger.warning(f"[BrowserFetcher] {sport_key}/{day} HTTP {status} after {retries+1} attempts")
                    return []

                body = self._page.inner_text("body")
                data = json.loads(body)
                events = data.get("events", [])
                return [_parse_ss_event(e, sport_key) for e in events]

            except json.JSONDecodeError:
                logger.debug(f"[BrowserFetcher] {sport_key}/{day} invalid JSON — likely no events")
                return []
            except Exception as e:
                if attempt < retries:
                    wait = (attempt + 1) * 3
                    logger.debug(f"[BrowserFetcher] {sport_key}/{day} exception — retry in {wait}s: {e}")
                    time.sleep(wait)
                else:
                    logger.warning(f"[BrowserFetcher] {sport_key}/{day} gave up: {e}")
                    return []

        return []

    # ── Batch fetch for a date range ──────────────────────────────────

    def fetch_date_range(
        self,
        ss_slug:    str,
        sport_key:  str,
        start:      date,
        end:        date,
        delay_range: tuple[float, float] = (0.8, 2.0),
    ) -> list[dict]:
        """
        Fetch all events for a sport between start and end (inclusive).
        Uses a random delay between requests to avoid rate-limiting.
        """
        all_events: list[dict] = []
        cur = start
        total_days = (end - start).days + 1
        done = 0

        while cur <= end:
            events = self.fetch_day(ss_slug, sport_key, cur)
            all_events.extend(events)
            done += 1

            if done % 30 == 0:
                logger.info(
                    f"[BrowserFetcher] {sport_key}: {done}/{total_days} days fetched, "
                    f"{len(all_events)} events so far"
                )

            cur += timedelta(days=1)
            # Polite delay — random to look more human
            time.sleep(random.uniform(*delay_range))

        return all_events


# ── High-level ingestion helpers ──────────────────────────────────────────────

def browser_ingest_sport(
    db,
    ss_slug:   str,
    sport_key: str,
    start:     date,
    end:       date,
    fetcher:   SofascoreBrowserFetcher | None = None,
) -> int:
    """
    Fetch and upsert all events for one sport between start and end.

    If a fetcher is provided, reuse it (shared browser session).
    If not, create one just for this call.

    Returns number of new matches inserted.
    """
    from sqlalchemy import func
    from data.db_models.models import Match, Competition, Sport as SportModel

    # Find dates already in DB for this sport
    sport_row = db.query(SportModel).filter_by(key=sport_key).first()
    existing_dates: set[date] = set()
    if sport_row:
        rows = db.query(func.date(Match.match_date)).join(Competition).filter(
            Competition.sport_id == sport_row.id
        ).distinct().all()
        existing_dates = {r[0] for r in rows if r[0]}

    # Only fetch missing dates
    missing_days = []
    cur = start
    while cur <= end:
        if cur not in existing_dates:
            missing_days.append(cur)
        cur += timedelta(days=1)

    if not missing_days:
        logger.info(f"[BrowserIngest] {sport_key}: all dates already in DB")
        return 0

    logger.info(f"[BrowserIngest] {sport_key}: fetching {len(missing_days)} missing dates via browser")

    def _run(f: SofascoreBrowserFetcher) -> int:
        total = 0
        batch: list[dict] = []
        done = 0

        for d in missing_days:
            events = f.fetch_day(ss_slug, sport_key, d)
            batch.extend(events)
            done += 1

            # Commit every 30 days to avoid huge transactions
            if len(batch) >= 600:
                total += upsert_events(db, batch)
                batch = []

            if done % 30 == 0:
                logger.info(f"[BrowserIngest] {sport_key}: {done}/{len(missing_days)} days, {total} inserted so far")

            time.sleep(random.uniform(0.8, 1.8))

        if batch:
            total += upsert_events(db, batch)

        return total

    if fetcher is not None:
        inserted = _run(fetcher)
    else:
        with SofascoreBrowserFetcher() as f:
            inserted = _run(f)

    logger.info(f"[BrowserIngest] {sport_key}: done — {inserted} new matches inserted")
    return inserted


def run_browser_backfill(
    db,
    days_back:  int = 730,
    sports:     list[str] | None = None,
) -> dict[str, int]:
    """
    Full historical backfill for browser-only sports using a single shared
    browser session (warm-up paid once, reused for all sports).

    sports: list of sport_keys to backfill. Defaults to BROWSER_ONLY_SPORTS.
    days_back: how many days of history to fetch (default 2 years = 730 days).

    Returns {sport_key: new_matches_inserted}.
    """
    if sports is None:
        sports = list(BROWSER_ONLY_SPORTS.keys())

    end   = date.today() - timedelta(days=1)
    start = end - timedelta(days=days_back)

    # Build slug lookup
    slug_map = {sk: slug for slug, sk, *_ in SPORTS_CONFIG}

    results: dict[str, int] = {}

    with SofascoreBrowserFetcher() as fetcher:
        for sport_key in sports:
            ss_slug = slug_map.get(sport_key)
            if not ss_slug:
                logger.warning(f"[BrowserBackfill] No Sofascore slug for {sport_key} — skipping")
                continue
            try:
                n = browser_ingest_sport(db, ss_slug, sport_key, start, end, fetcher=fetcher)
                results[sport_key] = n
            except Exception as e:
                logger.error(f"[BrowserBackfill] {sport_key} failed: {e}")
                results[sport_key] = 0

    return results


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    days  = int(sys.argv[1]) if len(sys.argv) > 1 else 730
    sport_filter = sys.argv[2:] if len(sys.argv) > 2 else None

    from data.database import get_sync_session
    with get_sync_session() as db:
        results = run_browser_backfill(db, days_back=days, sports=sport_filter or None)

    print("\n=== Browser backfill complete ===")
    for sport, n in results.items():
        print(f"  {sport:<20}: {n:,} new matches inserted")
