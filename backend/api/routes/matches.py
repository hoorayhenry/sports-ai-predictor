"""Match listing and detail endpoints."""
import asyncio
import json as _json_mod
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from data.database import get_async_session, get_sync_session
from data.db_models.models import Match, Competition, Sport, MatchOdds, Prediction

router = APIRouter(prefix="/matches", tags=["matches"])


def _fmt_match(m: Match, odds: list = None, pred: Prediction = None, intelligence: dict = None) -> dict:
    o_dict: dict = {}
    for o in (odds or []):
        key = f"{o.market}_{o.outcome}"
        if key not in o_dict or o_dict[key]["price"] < o.price:
            o_dict[key] = {"bookmaker": o.bookmaker, "market": o.market,
                           "outcome": o.outcome, "price": o.price, "point": o.point}

    # Extract live_minute from extra_data JSON
    live_minute = None
    if m.status == "live" and m.extra_data:
        try:
            import json as _json
            extra = _json.loads(m.extra_data)
            live_minute = extra.get("live_minute")
        except Exception:
            pass

    return {
        "id": m.id,
        "external_id": m.external_id,
        "sport": m.competition.sport.key if m.competition and m.competition.sport else None,
        "sport_icon": m.competition.sport.icon if m.competition and m.competition.sport else "🏆",
        "competition": m.competition.name if m.competition else None,
        "country": m.competition.country if m.competition else None,
        "home_team": m.home.name if m.home else "TBD",
        "away_team": m.away.name if m.away else "TBD",
        "home_elo": m.home.elo_rating if m.home else 1500,
        "away_elo": m.away.elo_rating if m.away else 1500,
        "match_date": m.match_date.isoformat() if m.match_date else None,
        "status": m.status,
        "live_minute": live_minute,
        "home_score": m.home_score,
        "away_score": m.away_score,
        "result": m.result,
        "odds": list(o_dict.values()),
        "prediction": _fmt_pred(pred) if pred else None,
        "intelligence": intelligence or {"has_intelligence": False, "signals": []},
    }


def _fmt_pred(p: Prediction) -> dict:
    return {
        "predicted_result": p.predicted_result,
        "home_win_prob": p.home_win_prob,
        "draw_prob": p.draw_prob,
        "away_win_prob": p.away_win_prob,
        "over25_prob": p.over25_prob,
        "btts_prob": p.btts_prob,
        "is_value_bet": p.is_value_bet,
        "value_market": p.value_market,
        "value_outcome": p.value_outcome,
        "value_odds": p.value_odds,
        "expected_value": p.expected_value,
        "kelly_stake": p.kelly_stake,
        "confidence": p.confidence,
    }


@router.get("")
async def list_matches(
    sport: Optional[str] = Query(None),
    competition_id: Optional[int] = Query(None),
    status: Optional[str] = Query("scheduled"),
    days: int = Query(7),
    date_from: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_async_session),
):
    from sqlalchemy import func as sqlfunc

    base_q = (
        select(Match)
        .join(Competition, Match.competition_id == Competition.id)
        .join(Sport, Competition.sport_id == Sport.id)
    )

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Date range: explicit range takes priority over days filter
    if date_from or date_to:
        if date_from:
            base_q = base_q.where(Match.match_date >= datetime.fromisoformat(date_from))
        if date_to:
            # Include full day
            dt_to = datetime.fromisoformat(date_to).replace(hour=23, minute=59, second=59)
            base_q = base_q.where(Match.match_date <= dt_to)
        if status == "scheduled":
            base_q = base_q.where(Match.status == "scheduled")
    elif status == "scheduled":
        cutoff = today_start + timedelta(days=days)
        base_q = base_q.where(
            Match.status == "scheduled",
            Match.match_date >= today_start,
            Match.match_date <= cutoff,
        )
    elif status == "finished":
        base_q = base_q.where(Match.result.isnot(None))
    elif status:
        base_q = base_q.where(Match.status == status)

    if sport:
        base_q = base_q.where(Sport.key == sport)
    if competition_id:
        base_q = base_q.where(Match.competition_id == competition_id)

    # Count total for pagination
    count_q = select(sqlfunc.count()).select_from(base_q.subquery())
    total_res = await db.execute(count_q)
    total = total_res.scalar_one()

    # Fetch page
    q = (
        base_q
        .options(
            selectinload(Match.home),
            selectinload(Match.away),
            selectinload(Match.competition).selectinload(Competition.sport),
            selectinload(Match.predictions),
            selectinload(Match.odds),
        )
        .order_by(Match.match_date)
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(q)
    matches = result.scalars().all()

    # Load intelligence signals (sync, lightweight)
    match_ids = [m.id for m in matches]
    intel_map: dict = {}
    if match_ids:
        try:
            from intelligence.signals import get_match_intelligence_summary
            with get_sync_session() as sync_db:
                for mid in match_ids:
                    intel_map[mid] = get_match_intelligence_summary(sync_db, mid)
        except Exception:
            pass

    out = []
    for m in matches:
        pred = m.predictions[0] if m.predictions else None
        out.append(_fmt_match(m, list(m.odds), pred, intel_map.get(m.id)))

    return {
        "matches": out,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < total,
    }


@router.get("/live/scores")
async def get_live_scores(db: AsyncSession = Depends(get_async_session)):
    """Return all currently live matches with real-time scores."""
    result = await db.execute(
        select(Match)
        .join(Competition, Match.competition_id == Competition.id)
        .join(Sport, Competition.sport_id == Sport.id)
        .options(
            selectinload(Match.home),
            selectinload(Match.away),
            selectinload(Match.competition).selectinload(Competition.sport),
            selectinload(Match.predictions),
            selectinload(Match.odds),
        )
        .where(Match.status == "live")
        .order_by(Match.match_date)
    )
    matches = result.scalars().all()
    return {
        "live_count": len(matches),
        "matches": [_fmt_match(m, list(m.odds), m.predictions[0] if m.predictions else None) for m in matches],
    }


@router.get("/live/stream")
async def live_stream():
    """
    Server-Sent Events stream for live scores.

    Polls ESPN directly every 10 seconds — bypasses the DB entirely.
    Only pushes to the browser when scores actually change.
    Heartbeat every 30s when nothing changes (keeps connection alive).

    Latency: ~10-40s after a real goal (ESPN's own refresh rate is 30-60s).
    """

    def _fetch_from_espn() -> list[dict]:
        """Blocking ESPN fetch — called in a thread pool to avoid blocking the loop."""
        from data.live_scores import fetch_live_fixtures_espn
        return fetch_live_fixtures_espn()

    def _snapshot(fixtures: list[dict]) -> str:
        """Stable fingerprint of current scores for change detection."""
        key = sorted(
            f"{f['external_id']}:{f['home_score']}:{f['away_score']}:{f['live_minute']}:{f['status']}"
            for f in fixtures
        )
        return "|".join(key)

    def _to_payload(fixtures: list[dict]) -> dict:
        """Convert ESPN fixtures to the shape the frontend expects."""
        live = [f for f in fixtures if f["status"] == "live"]
        return {
            "live_count": len(live),
            "matches": [
                {
                    "id":           idx,
                    "external_id":  f["external_id"],
                    "sport":        "football",
                    "sport_icon":   "⚽",
                    "competition":  f["league_name"],
                    "country":      f.get("country", ""),
                    "home_team":    f["home_team"],
                    "away_team":    f["away_team"],
                    "home_score":   f["home_score"],
                    "away_score":   f["away_score"],
                    "status":       f["status"],
                    "live_minute":  f["live_minute"],
                    "match_date":   f["match_date"],
                    "home_elo":     1500,
                    "away_elo":     1500,
                    "result":       None,
                    "odds":         [],
                    "prediction":   None,
                    "intelligence": None,
                }
                for idx, f in enumerate(live)
            ],
            "source": "espn",
            "ts": __import__("time").time(),
        }

    async def _db_seed_payload() -> dict | None:
        """
        Read currently-live matches from the DB — but only ones that are
        plausibly still in play:
          • match_date within the last 4 hours (covers 90min + stoppages)
          • live_minute <= 120 (guard against the minute=900+ stale rows)
        """
        try:
            import json as _js
            from data.database import AsyncSessionLocal
            cutoff = datetime.utcnow() - timedelta(hours=4)
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Match)
                    .join(Competition, Match.competition_id == Competition.id)
                    .join(Sport, Competition.sport_id == Sport.id)
                    .options(
                        selectinload(Match.home),
                        selectinload(Match.away),
                        selectinload(Match.competition).selectinload(Competition.sport),
                        selectinload(Match.predictions),
                        selectinload(Match.odds),
                    )
                    .where(
                        Match.status == "live",
                        Match.match_date >= cutoff,
                    )
                    .order_by(Match.match_date)
                )
                db_matches = result.scalars().all()

            # Drop rows where live_minute is clearly stale (> 120)
            def _live_min(m: Match) -> int | None:
                if m.extra_data:
                    try:
                        return _js.loads(m.extra_data).get("live_minute")
                    except Exception:
                        pass
                return None

            valid = [m for m in db_matches if (_live_min(m) or 0) <= 120]
            if not valid:
                return None
            return {
                "live_count": len(valid),
                "matches": [_fmt_match(m, list(m.odds), m.predictions[0] if m.predictions else None) for m in valid],
                "source": "db_seed",
                "ts": __import__("time").time(),
            }
        except Exception:
            return None

    async def generate():
        try:
            prev_snapshot = ""
            last_push     = 0.0
            POLL_INTERVAL = 10   # seconds between ESPN checks
            HEARTBEAT     = 30   # push even if no change (keeps connection alive)

            # ── Seed immediately from DB so the page isn't blank ──────
            seed = await _db_seed_payload()
            if seed:
                yield f"data: {_json_mod.dumps(seed)}\n\n"
                last_push = __import__("time").time()

            while True:
                try:
                    # Run blocking ESPN fetch in thread pool
                    fixtures = await asyncio.get_event_loop().run_in_executor(
                        None, _fetch_from_espn
                    )
                    snap    = _snapshot(fixtures)
                    now     = __import__("time").time()
                    changed = snap != prev_snapshot
                    due     = (now - last_push) >= HEARTBEAT

                    # Only skip pushing if ESPN returned 0 AND we have DB seed
                    # data already showing — avoids blanking the screen on flaky fetches
                    espn_has_data = len(fixtures) > 0

                    if changed or due:
                        if espn_has_data or not seed:
                            payload       = _to_payload(fixtures)
                            payload["changed"] = changed
                            prev_snapshot = snap
                            last_push     = now
                            yield f"data: {_json_mod.dumps(payload)}\n\n"
                        else:
                            # ESPN returned 0 — re-push DB seed to keep connection alive
                            last_push = now
                            yield f"data: {_json_mod.dumps({**seed, 'ts': now})}\n\n"

                except Exception as e:
                    yield f"data: {_json_mod.dumps({'error': str(e), 'live_count': 0, 'matches': []})}\n\n"

                await asyncio.sleep(POLL_INTERVAL)

        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":    "keep-alive",
        },
    )


@router.get("/{match_id}")
async def get_match(match_id: int, db: AsyncSession = Depends(get_async_session)):
    result = await db.execute(
        select(Match)
        .options(
            selectinload(Match.home),
            selectinload(Match.away),
            selectinload(Match.competition).selectinload(Competition.sport),
            selectinload(Match.predictions),
            selectinload(Match.odds),
        )
        .where(Match.id == match_id)
    )
    m = result.scalar_one_or_none()
    if not m:
        from fastapi import HTTPException
        raise HTTPException(404, "Match not found")
    pred = m.predictions[0] if m.predictions else None
    intel = None
    try:
        from intelligence.signals import get_match_intelligence_summary
        with get_sync_session() as sync_db:
            intel = get_match_intelligence_summary(sync_db, match_id)
    except Exception:
        pass
    return _fmt_match(m, list(m.odds), pred, intel)
