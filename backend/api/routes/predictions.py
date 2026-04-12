"""On-demand prediction and value bets endpoints."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from loguru import logger
from data.database import get_async_session, get_sync_session
from data.db_models.models import Match, Competition, Sport, Prediction

router = APIRouter(prefix="/predictions", tags=["predictions"])


def _run_prediction(match_id: int, sport_key: str):
    """Synchronous prediction runner (called from background task)."""
    from ml.models.sport_model import SportModel
    from features.engineering import build_inference_row
    from betting.value_engine import evaluate_match, save_predictions

    try:
        model = SportModel.load(sport_key)
    except FileNotFoundError:
        logger.warning(f"No trained model for {sport_key} — skipping prediction")
        return

    with get_sync_session() as db:
        match = db.query(Match).get(match_id)
        if not match:
            return
        X = build_inference_row(db, match, sport_key)
        if X.empty:
            return
        pred_probs = model.predict(X)
        value_bets = evaluate_match(db, match_id, pred_probs)
        save_predictions(db, match, pred_probs, value_bets)
        logger.info(f"Predicted match {match_id}: {pred_probs}")


@router.post("/run/{match_id}")
async def predict_match(
    match_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_session),
):
    """Trigger prediction for a single match (async background)."""
    result = await db.execute(
        select(Match)
        .options(selectinload(Match.competition).selectinload(Competition.sport))
        .where(Match.id == match_id)
    )
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Match not found")
    sport_key = m.competition.sport.key if m.competition and m.competition.sport else None
    if not sport_key:
        raise HTTPException(400, "Cannot determine sport for this match")

    background_tasks.add_task(_run_prediction, match_id, sport_key)
    return {"status": "queued", "match_id": match_id}


@router.post("/run-all")
async def predict_all_upcoming(
    sport: Optional[str] = Query(None),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_async_session),
):
    """Queue predictions for all upcoming matches."""
    from datetime import datetime, timedelta
    q = (
        select(Match)
        .options(selectinload(Match.competition).selectinload(Competition.sport))
        .join(Competition).join(Sport)
        .where(Match.status == "scheduled")
    )
    if sport:
        q = q.where(Sport.key == sport)

    result = await db.execute(q)
    matches = result.scalars().all()

    queued = 0
    for m in matches:
        sk = m.competition.sport.key if m.competition and m.competition.sport else None
        if sk:
            background_tasks.add_task(_run_prediction, m.id, sk)
            queued += 1

    return {"status": "queued", "count": queued}


@router.get("/value-bets")
async def value_bets(
    sport: Optional[str] = Query(None),
    min_ev: float = Query(0.04),
    db: AsyncSession = Depends(get_async_session),
):
    """Return all scheduled matches with positive EV bets."""
    q = (
        select(Match)
        .options(
            selectinload(Match.home),
            selectinload(Match.away),
            selectinload(Match.competition).selectinload(Competition.sport),
            selectinload(Match.predictions),
            selectinload(Match.odds),
        )
        .join(Competition).join(Sport)
        .join(Prediction, Match.id == Prediction.match_id)
        .where(
            Match.status == "scheduled",
            Prediction.is_value_bet == True,
            Prediction.expected_value >= min_ev,
        )
        .order_by(Prediction.expected_value.desc())
    )
    if sport:
        q = q.where(Sport.key == sport)

    result = await db.execute(q)
    matches = result.scalars().all()

    out = []
    for m in matches:
        pred = m.predictions[0] if m.predictions else None
        if not pred:
            continue
        out.append({
            "match_id": m.id,
            "sport": m.competition.sport.key if m.competition and m.competition.sport else None,
            "sport_icon": m.competition.sport.icon if m.competition and m.competition.sport else "🏆",
            "competition": m.competition.name if m.competition else None,
            "home_team": m.home.name if m.home else "TBD",
            "away_team": m.away.name if m.away else "TBD",
            "match_date": m.match_date.isoformat() if m.match_date else None,
            "predicted_result": pred.predicted_result,
            "home_win_prob": pred.home_win_prob,
            "draw_prob": pred.draw_prob,
            "away_win_prob": pred.away_win_prob,
            "over25_prob": pred.over25_prob,
            "btts_prob": pred.btts_prob,
            "value_market": pred.value_market,
            "value_outcome": pred.value_outcome,
            "value_odds": pred.value_odds,
            "expected_value": pred.expected_value,
            "kelly_stake": pred.kelly_stake,
            "confidence": pred.confidence,
        })
    return out


@router.get("/stats")
async def prediction_stats(db: AsyncSession = Depends(get_async_session)):
    """Overall prediction accuracy statistics."""
    from sqlalchemy import func
    result = await db.execute(
        select(
            func.count(Prediction.id).label("total"),
        )
        .join(Match, Prediction.match_id == Match.id)
        .where(Match.result.isnot(None))
    )
    total = result.scalar() or 0

    correct_res = await db.execute(
        select(func.count(Prediction.id))
        .join(Match, Prediction.match_id == Match.id)
        .where(
            Match.result.isnot(None),
            Prediction.predicted_result == Match.result,
        )
    )
    correct = correct_res.scalar() or 0

    return {
        "total_predicted": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0,
    }
