"""Match listing and detail endpoints."""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from data.database import get_async_session
from data.db_models.models import Match, Competition, Sport, MatchOdds, Prediction

router = APIRouter(prefix="/matches", tags=["matches"])


def _fmt_match(m: Match, odds: list = None, pred: Prediction = None) -> dict:
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
    db: AsyncSession = Depends(get_async_session),
):
    q = (
        select(Match)
        .options(
            selectinload(Match.home),
            selectinload(Match.away),
            selectinload(Match.competition).selectinload(Competition.sport),
            selectinload(Match.predictions),
            selectinload(Match.odds),
        )
        .join(Competition, Match.competition_id == Competition.id)
        .join(Sport, Competition.sport_id == Sport.id)
        .order_by(Match.match_date)
    )

    if status == "scheduled":
        cutoff = datetime.utcnow() + timedelta(days=days)
        q = q.where(Match.status == "scheduled", Match.match_date >= datetime.utcnow(),
                    Match.match_date <= cutoff)
    elif status == "finished":
        q = q.where(Match.result.isnot(None))
    elif status:
        q = q.where(Match.status == status)

    if sport:
        q = q.where(Sport.key == sport)
    if competition_id:
        q = q.where(Match.competition_id == competition_id)

    result = await db.execute(q)
    matches = result.scalars().all()

    out = []
    for m in matches:
        pred = m.predictions[0] if m.predictions else None
        out.append(_fmt_match(m, list(m.odds), pred))
    return out


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
    return _fmt_match(m, list(m.odds), pred)
