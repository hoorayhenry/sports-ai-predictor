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
    markets = None
    if p.markets_json:
        try:
            markets = _json_mod.loads(p.markets_json)
        except Exception:
            pass
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
        "markets": markets,
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
    """
    Return all currently live matches with real-time scores.

    Combines two sources so the count always matches the Live page:
      1. DB matches marked status='live' (have prediction/odds/intelligence data)
      2. Sofascore cache fixtures not yet in the DB (teams not ingested yet)
    """
    from data.live_scores import get_cached_live_fixtures

    # ── DB live matches (rich — includes predictions, odds) ──────────────
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
    db_matches = result.scalars().all()
    db_ext_ids = {m.external_id for m in db_matches if m.external_id}

    db_formatted = [
        _fmt_match(m, list(m.odds), m.predictions[0] if m.predictions else None)
        for m in db_matches
    ]

    # ── Sofascore cache fixtures not in DB (MLB, NHL, etc. not yet ingested) ─
    cache_fixtures = get_cached_live_fixtures()
    orphan_formatted = []
    for idx, f in enumerate(cache_fixtures):
        if f.get("external_id") in db_ext_ids:
            continue  # already represented by the DB record above
        orphan_formatted.append({
            "id":           -(idx + 1),   # negative ID signals no DB record
            "home_team":    f.get("home_team", ""),
            "away_team":    f.get("away_team", ""),
            "competition":  f.get("competition") or f.get("league_name", ""),
            "country":      f.get("country", ""),
            "sport_icon":   f.get("sport_icon", "🏆"),
            "sport_key":    f.get("sport_key", ""),
            "home_score":   f.get("home_score"),
            "away_score":   f.get("away_score"),
            "status":       "live",
            "live_minute":  f.get("live_minute"),
            "clock_str":    f.get("clock_str", ""),
            "match_date":   str(f.get("match_date", "")),
            "home_elo":     1500,
            "away_elo":     1500,
            "prediction":   None,
            "intelligence": None,
            "odds":         [],
            "result":       None,
            "extra_data":   None,
            "source":       f.get("source", "sofascore"),
        })

    all_matches = db_formatted + orphan_formatted
    return {
        "live_count": len(all_matches),
        "matches":    all_matches,
    }


@router.get("/live/stream")
async def live_stream():
    """
    Server-Sent Events stream for live scores.

    Reads the shared Sofascore live cache (updated by the scheduler every 30 s)
    rather than calling ESPN directly — this keeps the navbar count and the Live
    page perfectly in sync (same data source).

    Heartbeat every 30 s when nothing changes (keeps connection alive).
    Falls back to a direct Sofascore fetch when the cache is cold on first connect.
    """

    def _build_payload(cache_fixtures: list[dict]) -> dict:
        """
        Merge rich DB records (predictions/odds) with lightweight Sofascore fixtures
        into the shape the Live page frontend expects.
        """
        from data.database import get_sync_session
        from data.db_models.models import Match as _Match

        # Collect external IDs in the cache for quick lookup
        cache_by_extid = {f.get("external_id"): f for f in cache_fixtures if f.get("external_id")}

        # Load any DB matches whose external_id overlaps with the cache
        db_rows: dict[str, dict] = {}
        try:
            with get_sync_session() as _db:
                ext_ids = list(cache_by_extid.keys())
                db_m = _db.query(_Match).filter(
                    _Match.external_id.in_(ext_ids),
                    _Match.status == "live",
                ).all()
                for m in db_m:
                    db_rows[m.external_id] = _fmt_match(m, list(m.odds), m.predictions[0] if m.predictions else None)
        except Exception:
            pass

        matches = []
        for idx, f in enumerate(cache_fixtures):
            ext_id = f.get("external_id", "")
            if ext_id in db_rows:
                # Use the rich DB record but overlay current live scores from cache
                entry = {**db_rows[ext_id]}
                entry["home_score"]  = f.get("home_score", entry.get("home_score"))
                entry["away_score"]  = f.get("away_score", entry.get("away_score"))
                entry["live_minute"] = f.get("live_minute", entry.get("live_minute"))
            else:
                # Lightweight orphan — not in DB yet
                entry = {
                    "id":           -(idx + 1),
                    "external_id":  ext_id,
                    "home_team":    f.get("home_team", ""),
                    "away_team":    f.get("away_team", ""),
                    "competition":  f.get("competition") or f.get("league_name", ""),
                    "country":      f.get("country", ""),
                    "sport_icon":   f.get("sport_icon", "🏆"),
                    "sport_key":    f.get("sport_key", ""),
                    "home_score":   f.get("home_score"),
                    "away_score":   f.get("away_score"),
                    "status":       "live",
                    "live_minute":  f.get("live_minute"),
                    "clock_str":    f.get("clock_str", ""),
                    "match_date":   str(f.get("match_date", "")),
                    "home_elo":     1500,
                    "away_elo":     1500,
                    "result":       None,
                    "odds":         [],
                    "prediction":   None,
                    "intelligence": None,
                    "source":       f.get("source", "sofascore"),
                }
            matches.append(entry)

        return {
            "live_count": len(matches),
            "matches":    matches,
            "source":     "sofascore_cache",
            "ts":         __import__("time").time(),
        }

    def _snapshot(fixtures: list[dict]) -> str:
        """Stable fingerprint for change detection."""
        parts = sorted(
            f"{f.get('external_id','')}:{f.get('home_score')}:{f.get('away_score')}:{f.get('live_minute')}"
            for f in fixtures
        )
        return "|".join(parts)

    async def generate():
        import time as _t
        from data.live_scores import get_cached_live_fixtures

        try:
            prev_snapshot = ""
            last_push     = 0.0
            POLL_INTERVAL = 10   # check cache every 10 s (cache updates every 30 s)
            HEARTBEAT     = 30   # force push at least every 30 s (keeps connection alive)

            while True:
                try:
                    fixtures = await asyncio.get_event_loop().run_in_executor(
                        None, get_cached_live_fixtures
                    )
                    snap    = _snapshot(fixtures)
                    now     = _t.time()
                    changed = snap != prev_snapshot
                    due     = (now - last_push) >= HEARTBEAT

                    if changed or due:
                        payload = await asyncio.get_event_loop().run_in_executor(
                            None, _build_payload, fixtures
                        )
                        payload["changed"] = changed
                        prev_snapshot = snap
                        last_push     = now
                        yield f"data: {_json_mod.dumps(payload)}\n\n"

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
