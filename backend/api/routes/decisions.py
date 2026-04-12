"""
Decision Engine API — daily picks, smart sets, performance tracking.
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from loguru import logger

from data.database import get_async_session, get_sync_session
from data.db_models.models import (
    Match, MatchDecision, Prediction, SmartSet,
    PerformanceLog, OptimizationWeight, Competition, Sport,
)

router = APIRouter(prefix="/decisions", tags=["decisions"])


def _fmt_decision(m: Match, md: MatchDecision, pred: Optional[Prediction]) -> dict:
    return {
        "match_id":          m.id,
        "sport":             m.competition.sport.key if m.competition and m.competition.sport else None,
        "sport_icon":        m.competition.sport.icon if m.competition and m.competition.sport else "🏆",
        "competition":       m.competition.name if m.competition else None,
        "country":           m.competition.country if m.competition else None,
        "home_team":         m.home.name if m.home else "TBD",
        "away_team":         m.away.name if m.away else "TBD",
        "match_date":        m.match_date.isoformat() if m.match_date else None,
        "status":            m.status,
        # Decision fields
        "ai_decision":       md.ai_decision,
        "confidence_score":  md.confidence_score,
        "prob_tag":          md.prob_tag,
        "top_prob":          md.top_prob,
        "predicted_outcome": md.predicted_outcome,
        "has_volatility":    md.has_volatility,
        "volatility_reason": md.volatility_reason,
        "recommended_odds":  md.recommended_odds,
        "recommended_stake_pct": md.recommended_stake_pct,
        # Score breakdown
        "score_breakdown": {
            "probability":   round(md.prob_component, 1),
            "expected_value": round(md.ev_component, 1),
            "form":          round(md.form_component, 1),
            "consistency":   round(md.consistency_component, 1),
        },
        # Prediction fields
        "home_win_prob":  pred.home_win_prob if pred else None,
        "draw_prob":      pred.draw_prob if pred else None,
        "away_win_prob":  pred.away_win_prob if pred else None,
        "over25_prob":    pred.over25_prob if pred else None,
        "btts_prob":      pred.btts_prob if pred else None,
        "is_value_bet":   pred.is_value_bet if pred else False,
        "expected_value": pred.expected_value if pred else None,
    }


@router.get("/daily-picks")
async def daily_picks(
    sport: Optional[str] = Query(None),
    limit: int = Query(10),
    days: int = Query(7, description="Look-ahead window in days (default 7)"),
    db: AsyncSession = Depends(get_async_session),
):
    """Top PLAY decisions within the next N days, sorted by confidence."""
    cutoff = datetime.utcnow() + timedelta(days=days)

    q = (
        select(Match)
        .join(MatchDecision, Match.id == MatchDecision.match_id)
        .join(Prediction, Match.id == Prediction.match_id)
        .join(Competition, Match.competition_id == Competition.id)
        .join(Sport, Competition.sport_id == Sport.id)
        .options(
            selectinload(Match.home),
            selectinload(Match.away),
            selectinload(Match.competition).selectinload(Competition.sport),
            selectinload(Match.predictions),
        )
        .where(
            Match.status == "scheduled",
            Match.match_date >= datetime.utcnow(),
            Match.match_date <= cutoff,
            MatchDecision.ai_decision == "PLAY",
        )
        .order_by(MatchDecision.confidence_score.desc())
        .limit(limit)
    )
    if sport:
        q = q.where(Sport.key == sport)

    result  = await db.execute(q)
    matches = result.scalars().all()

    out = []
    for m in matches:
        md_res = await db.execute(
            select(MatchDecision).where(MatchDecision.match_id == m.id)
        )
        md   = md_res.scalar_one_or_none()
        pred = m.predictions[0] if m.predictions else None
        if md:
            out.append(_fmt_decision(m, md, pred))
    return out


@router.get("/all")
async def all_decisions(
    sport: Optional[str] = Query(None),
    decision: Optional[str] = Query(None),
    prob_tag: Optional[str] = Query(None),
    days: int = Query(2),
    db: AsyncSession = Depends(get_async_session),
):
    """All decisions for upcoming matches, with optional filters."""
    cutoff = datetime.utcnow() + timedelta(days=days)
    q = (
        select(Match)
        .join(MatchDecision, Match.id == MatchDecision.match_id)
        .join(Prediction, Match.id == Prediction.match_id)
        .join(Competition, Match.competition_id == Competition.id)
        .join(Sport, Competition.sport_id == Sport.id)
        .options(
            selectinload(Match.home),
            selectinload(Match.away),
            selectinload(Match.competition).selectinload(Competition.sport),
            selectinload(Match.predictions),
        )
        .where(
            Match.status == "scheduled",
            Match.match_date >= datetime.utcnow(),
            Match.match_date <= cutoff,
        )
        .order_by(MatchDecision.confidence_score.desc())
    )
    if sport:
        q = q.where(Sport.key == sport)
    if decision:
        q = q.where(MatchDecision.ai_decision == decision.upper())
    if prob_tag:
        q = q.where(MatchDecision.prob_tag == prob_tag.upper())

    result  = await db.execute(q)
    matches = result.scalars().all()

    out = []
    for m in matches:
        md_res = await db.execute(
            select(MatchDecision).where(MatchDecision.match_id == m.id)
        )
        md   = md_res.scalar_one_or_none()
        pred = m.predictions[0] if m.predictions else None
        if md:
            out.append(_fmt_decision(m, md, pred))
    return out


@router.get("/smart-sets")
async def smart_sets(
    date_str: Optional[str] = Query(None, description="YYYY-MM-DD, default=today"),
    db: AsyncSession = Depends(get_async_session),
):
    """Return the 10 Smart Sets generated for a given date."""
    if date_str:
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")
    else:
        target = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(SmartSet)
        .where(SmartSet.generated_date >= target)
        .order_by(SmartSet.set_number)
    )
    sets = result.scalars().all()

    out = []
    for ss in sets:
        matches = json.loads(ss.matches_json) if ss.matches_json else []
        out.append({
            "id":                   ss.id,
            "set_number":           ss.set_number,
            "generated_date":       ss.generated_date.isoformat(),
            "match_count":          ss.match_count,
            "overall_confidence":   ss.overall_confidence,
            "combined_probability": ss.combined_probability,
            "avg_odds":             ss.avg_odds,
            "risk_level":           ss.risk_level,
            "status":               ss.status,
            "wins":                 ss.wins,
            "losses":               ss.losses,
            "roi":                  ss.roi,
            "matches":              matches,
        })
    return out


@router.get("/performance")
async def performance(
    sport: Optional[str] = Query(None),
    days: int = Query(30),
    db: AsyncSession = Depends(get_async_session),
):
    """Aggregated performance stats for the last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    q = select(PerformanceLog).where(
        PerformanceLog.log_date >= cutoff,
        PerformanceLog.is_correct.isnot(None),
    )
    if sport:
        q = q.where(PerformanceLog.sport_key == sport)

    result = await db.execute(q)
    logs   = result.scalars().all()

    play_logs  = [l for l in logs if l.ai_decision == "PLAY"]
    total      = len(play_logs)
    wins       = sum(1 for l in play_logs if l.is_correct)
    total_pnl  = sum((l.profit_loss_units or 0) for l in play_logs)

    # By sport
    sport_stats: dict = {}
    for l in play_logs:
        s = l.sport_key
        if s not in sport_stats:
            sport_stats[s] = {"wins": 0, "total": 0, "pnl": 0.0}
        sport_stats[s]["wins"]  += int(l.is_correct)
        sport_stats[s]["total"] += 1
        sport_stats[s]["pnl"]   += l.profit_loss_units or 0

    # Top competitions by win rate (min 5 samples)
    comp_stats: dict = {}
    for l in play_logs:
        c = l.competition
        if c not in comp_stats:
            comp_stats[c] = {"wins": 0, "total": 0}
        comp_stats[c]["wins"]  += int(l.is_correct)
        comp_stats[c]["total"] += 1

    top_comps = sorted(
        [{"competition": k, "win_rate": v["wins"]/v["total"], "sample": v["total"]}
         for k, v in comp_stats.items() if v["total"] >= 5],
        key=lambda x: -x["win_rate"],
    )[:10]

    return {
        "period_days":      days,
        "total_picks":      total,
        "wins":             wins,
        "losses":           total - wins,
        "win_rate":         round(wins / total, 4) if total else 0,
        "total_pnl_units":  round(total_pnl, 4),
        "roi_pct":          round((total_pnl / total) * 100, 2) if total else 0,
        "by_sport":         {k: {**v, "win_rate": round(v["wins"]/v["total"], 3)} for k, v in sport_stats.items() if v["total"] > 0},
        "top_competitions": top_comps,
    }


@router.get("/optimization-weights")
async def optimization_weights(db: AsyncSession = Depends(get_async_session)):
    """Return current self-optimization weights per sport/competition."""
    result = await db.execute(
        select(OptimizationWeight).order_by(OptimizationWeight.weight.desc())
    )
    rows = result.scalars().all()
    return [
        {
            "scope_key":    r.scope_key,
            "scope_type":   r.scope_type,
            "weight":       r.weight,
            "success_rate": r.success_rate,
            "sample_size":  r.sample_size,
            "updated_at":   r.updated_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/run-now")
async def run_decisions_now(
    background_tasks: BackgroundTasks,
    send_email: bool = Query(False),
):
    """Manually trigger the decision engine + smart set generator."""
    def _run(send_email_: bool):
        from data.database import get_sync_session
        from betting.decision_engine import process_decisions, generate_smart_sets
        from scheduler import _get_daily_picks_dicts, _get_smart_sets_dicts
        from mailer.daily_email import send_daily_email

        with get_sync_session() as db:
            play_count = process_decisions(db)
            sets       = generate_smart_sets(db)
            if send_email_:
                picks  = _get_daily_picks_dicts(db)
                sets_d = _get_smart_sets_dicts(db)
            else:
                picks, sets_d = [], []

        if send_email_:
            send_daily_email(picks, sets_d)
        logger.info(f"Manual run: {play_count} PLAY, {len(sets)} sets")

    background_tasks.add_task(_run, send_email)
    return {"status": "queued", "send_email": send_email}


@router.post("/resolve-all")
async def resolve_all(background_tasks: BackgroundTasks):
    """Manually trigger resolution of finished matches."""
    def _run():
        from data.database import get_sync_session
        from betting.decision_engine import resolve_finished_matches
        with get_sync_session() as db:
            resolve_finished_matches(db)

    background_tasks.add_task(_run)
    return {"status": "queued"}
