"""Match listing and detail endpoints."""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
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
