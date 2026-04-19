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
    markets = None
    if pred and pred.markets_json:
        try:
            markets = json.loads(pred.markets_json)
        except Exception:
            pass

    # Market implied probability and edge
    market_prob = getattr(md, "market_prob", None)
    edge        = getattr(md, "edge", None)
    edge_pct    = round(edge * 100, 1) if edge is not None else None

    # Market-implied prob as percentage for display
    market_prob_pct = round(market_prob * 100, 1) if market_prob is not None else None
    model_prob_pct  = round(md.top_prob * 100, 1) if md.top_prob else None

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
        # Decision
        "ai_decision":           md.ai_decision,
        "confidence_score":      md.confidence_score,
        "prob_tag":              md.prob_tag,
        "top_prob":              md.top_prob,
        "predicted_outcome":     md.predicted_outcome,
        "has_volatility":        md.has_volatility,
        "volatility_reason":     md.volatility_reason,
        "recommended_odds":      md.recommended_odds,
        "recommended_stake_pct": md.recommended_stake_pct,
        # SKIP reason (null on PLAY picks)
        "skip_reason":           getattr(md, "skip_reason", None),
        # Value intelligence
        "market_prob":     market_prob,
        "market_prob_pct": market_prob_pct,
        "model_prob_pct":  model_prob_pct,
        "edge":            edge,
        "edge_pct":        edge_pct,
        "value_label":     getattr(md, "value_label", None),
        # CLV
        "clv":             getattr(md, "clv", None),
        # Score breakdown
        "score_breakdown": {
            "probability":    round(md.prob_component, 1),
            "expected_value": round(md.ev_component, 1),
            "form":           round(md.form_component, 1),
            "consistency":    round(md.consistency_component, 1),
        },
        # Prediction fields
        "home_win_prob":  pred.home_win_prob if pred else None,
        "draw_prob":      pred.draw_prob if pred else None,
        "away_win_prob":  pred.away_win_prob if pred else None,
        "over25_prob":    pred.over25_prob if pred else None,
        "btts_prob":      pred.btts_prob if pred else None,
        "is_value_bet":   pred.is_value_bet if pred else False,
        "expected_value": pred.expected_value if pred else None,
        "markets":        markets,
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

    # ── Total analysed count (all decisions in window) ────────────────
    total_q = (
        select(func.count())
        .select_from(Match)
        .join(MatchDecision, Match.id == MatchDecision.match_id)
        .join(Competition, Match.competition_id == Competition.id)
        .join(Sport, Competition.sport_id == Sport.id)
        .where(
            Match.status == "scheduled",
            Match.match_date >= datetime.utcnow(),
            Match.match_date <= cutoff,
        )
    )
    if sport:
        total_q = total_q.where(Sport.key == sport)
    total_analysed = (await db.execute(total_q)).scalar_one()

    # ── PLAY picks ────────────────────────────────────────────────────
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

    return {
        "picks":          out,
        "total_analysed": total_analysed,
        "total_plays":    len(out),
        "total_skipped":  total_analysed - len(out),
        "selection_rate": round(len(out) / total_analysed * 100, 1) if total_analysed else 0,
    }


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
    sport: Optional[str] = Query(None, description="Filter by sport key, e.g. 'football'"),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Return all active Smart Sets (window_end in the future or within last 24h).
    Grouped by window_label + sport_key so the frontend can render per-window sections.
    """
    # Include sets whose window ends within the last 24h (recently finished window)
    cutoff = datetime.utcnow() - timedelta(hours=24)

    q = (
        select(SmartSet)
        .where(SmartSet.window_end >= cutoff)
        .order_by(SmartSet.window_start, SmartSet.sport_key, SmartSet.set_number)
    )
    # Fall back to today-generated sets if no windowed sets exist yet
    result = await db.execute(q)
    sets = result.scalars().all()

    if not sets:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await db.execute(
            select(SmartSet)
            .where(SmartSet.generated_date >= today)
            .order_by(SmartSet.set_number)
        )
        sets = result.scalars().all()

    if sport:
        sets = [s for s in sets if s.sport_key == sport]

    out = []
    for ss in sets:
        matches = json.loads(ss.matches_json) if ss.matches_json else []
        out.append({
            "id":                   ss.id,
            "set_number":           ss.set_number,
            "generated_date":       ss.generated_date.isoformat(),
            "window_label":         ss.window_label,
            "window_start":         ss.window_start.isoformat() if ss.window_start else None,
            "window_end":           ss.window_end.isoformat() if ss.window_end else None,
            "sport_key":            ss.sport_key or "football",
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


@router.get("/history")
async def prediction_history(
    sport:    Optional[str] = Query(None),
    days:     int           = Query(90),
    decision: Optional[str] = Query(None, description="PLAY or SKIP"),
    limit:    int           = Query(200),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Full prediction history — every resolved match with:
      - what the AI predicted
      - the actual result
      - whether the prediction was correct
      - profit/loss in units
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    q = (
        select(PerformanceLog)
        .where(
            PerformanceLog.log_date >= cutoff,
            PerformanceLog.is_correct.isnot(None),
        )
        .order_by(PerformanceLog.log_date.desc())
        .limit(limit)
    )
    if sport:
        q = q.where(PerformanceLog.sport_key == sport)
    if decision:
        q = q.where(PerformanceLog.ai_decision == decision.upper())

    result = await db.execute(q)
    logs   = result.scalars().all()

    # Enrich with match team names
    out = []
    for lg in logs:
        match_res = await db.execute(
            select(Match)
            .options(
                selectinload(Match.home),
                selectinload(Match.away),
                selectinload(Match.competition).selectinload(Competition.sport),
            )
            .where(Match.id == lg.match_id)
        )
        m = match_res.scalar_one_or_none()

        outcome_map = {"H": "Home Win", "D": "Draw", "A": "Away Win"}
        out.append({
            "match_id":          lg.match_id,
            "sport":             lg.sport_key,
            "sport_icon":        (m.competition.sport.icon if m and m.competition and m.competition.sport else "🏆"),
            "competition":       lg.competition,
            "home_team":         (m.home.name if m and m.home else "—"),
            "away_team":         (m.away.name if m and m.away else "—"),
            "match_date":        (m.match_date.isoformat() if m else None),
            # Prediction
            "ai_decision":       lg.ai_decision,
            "confidence_score":  lg.confidence_score,
            "predicted_outcome": lg.predicted_outcome,
            "predicted_outcome_label": outcome_map.get(lg.predicted_outcome, lg.predicted_outcome),
            "predicted_prob":    round(lg.predicted_prob, 4) if lg.predicted_prob else None,
            "recommended_odds":  round(lg.odds_used, 2) if lg.odds_used else None,
            # Actual result
            "actual_result":     lg.actual_result,
            "actual_result_label": outcome_map.get(lg.actual_result or "", lg.actual_result or ""),
            # Outcome
            "is_correct":        lg.is_correct,
            "profit_loss_units": round(lg.profit_loss_units, 4) if lg.profit_loss_units is not None else 0,
            "resolved_at":       lg.log_date.isoformat(),
        })

    return out


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


@router.get("/analytics/calibration")
async def calibration(
    sport: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Probability calibration — are our confidence buckets honest?

    Groups resolved PLAY bets by predicted probability bucket and compares
    the predicted win rate vs actual win rate.

    A well-calibrated model: 70% confidence bucket wins ~70% of the time.
    If the 80% bucket only wins 55%, the model is overconfident.
    """
    q = select(PerformanceLog).where(
        PerformanceLog.ai_decision == "PLAY",
        PerformanceLog.is_correct.isnot(None),
        PerformanceLog.predicted_prob.isnot(None),
    )
    if sport:
        q = q.where(PerformanceLog.sport_key == sport)

    result = await db.execute(q)
    logs   = result.scalars().all()

    # Group into 5-point probability buckets
    buckets: dict[str, dict] = {}
    for lg in logs:
        prob = lg.predicted_prob
        if prob is None:
            continue
        lo   = int(prob * 100 // 5) * 5
        hi   = lo + 5
        key  = f"{lo}-{hi}%"
        if key not in buckets:
            buckets[key] = {"lo": lo, "wins": 0, "total": 0}
        buckets[key]["total"] += 1
        if lg.is_correct:
            buckets[key]["wins"] += 1

    calibration_rows = []
    for key, v in sorted(buckets.items(), key=lambda x: x[1]["lo"]):
        total        = v["total"]
        wins         = v["wins"]
        actual_rate  = wins / total if total > 0 else 0
        predicted    = (v["lo"] + 2.5) / 100  # midpoint
        gap          = actual_rate - predicted  # positive = better than expected
        calibration_rows.append({
            "bucket":          key,
            "predicted_rate":  round(predicted, 3),
            "actual_rate":     round(actual_rate, 3),
            "gap":             round(gap, 3),
            "wins":            wins,
            "total":           total,
            "well_calibrated": abs(gap) <= 0.05,
        })

    total_resolved = sum(v["total"] for v in buckets.values())
    total_wins     = sum(v["wins"] for v in buckets.values())

    return {
        "calibration":      calibration_rows,
        "total_resolved":   total_resolved,
        "overall_accuracy": round(total_wins / total_resolved, 3) if total_resolved else None,
        "note": "Gap = actual - predicted. Positive = better than model predicted. Well-calibrated = gap within ±5%.",
    }


@router.get("/analytics/clv")
async def clv_stats(
    sport: Optional[str] = Query(None),
    days: int = Query(30),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Closing Line Value stats — did we consistently beat the market?

    Positive average CLV means we got better odds than the market's final
    assessment. This is the strongest proof that edge is real, not noise.

    CLV = (odds_at_decision / closing_odds) - 1
    Positive = we beat the closing line (got better odds than market closed at).
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    q = (
        select(PerformanceLog)
        .where(
            PerformanceLog.log_date >= cutoff,
            PerformanceLog.ai_decision == "PLAY",
            PerformanceLog.clv.isnot(None),
        )
        .order_by(PerformanceLog.log_date.desc())
    )
    if sport:
        q = q.where(PerformanceLog.sport_key == sport)

    result = await db.execute(q)
    logs   = result.scalars().all()

    if not logs:
        return {
            "message": "No CLV data yet — CLV is computed when matches resolve.",
            "period_days": days,
            "total": 0,
        }

    clv_vals   = [lg.clv for lg in logs if lg.clv is not None]
    avg_clv    = sum(clv_vals) / len(clv_vals) if clv_vals else 0
    beat_market = sum(1 for v in clv_vals if v > 0)

    # By sport
    by_sport: dict = {}
    for lg in logs:
        s = lg.sport_key
        if s not in by_sport:
            by_sport[s] = {"clv_sum": 0.0, "count": 0, "beat": 0}
        by_sport[s]["clv_sum"] += lg.clv or 0
        by_sport[s]["count"]   += 1
        if (lg.clv or 0) > 0:
            by_sport[s]["beat"] += 1

    return {
        "period_days":       days,
        "total_picks":       len(clv_vals),
        "avg_clv_pct":       round(avg_clv * 100, 2),
        "beat_market_pct":   round(beat_market / len(clv_vals) * 100, 1) if clv_vals else 0,
        "verdict":           "Real edge detected" if avg_clv > 0.02 else ("Marginal" if avg_clv > 0 else "No CLV edge"),
        "by_sport": {
            s: {
                "avg_clv_pct": round(v["clv_sum"] / v["count"] * 100, 2),
                "beat_market_pct": round(v["beat"] / v["count"] * 100, 1),
                "total": v["count"],
            }
            for s, v in by_sport.items()
        },
    }


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

        from datetime import datetime as _dt, timedelta as _td
        # Use next 7 days as default window for manual trigger
        _now = _dt.utcnow()
        with get_sync_session() as db:
            play_count = process_decisions(db)
            sets       = generate_smart_sets(db, _now, _now + _td(days=7))
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


@router.get("/analytics/system")
async def system_analytics(db: AsyncSession = Depends(get_async_session)):
    """System health and intelligence pipeline stats for the analytics dashboard."""
    from data.db_models.models import IntelligenceSignal, NewsArticle

    now = datetime.utcnow()
    last_24h = now - timedelta(hours=24)
    last_48h = now - timedelta(hours=48)

    # Prediction counts
    total_predictions = (await db.execute(
        select(func.count()).select_from(Prediction)
    )).scalar_one()

    predictions_today = (await db.execute(
        select(func.count()).select_from(Prediction).where(
            Prediction.created_at >= now.replace(hour=0, minute=0, second=0)
        )
    )).scalar_one()

    # Decision counts — join Match to filter by date
    play_count = (await db.execute(
        select(func.count()).select_from(MatchDecision)
        .join(Match, Match.id == MatchDecision.match_id)
        .where(
            MatchDecision.ai_decision == "PLAY",
            Match.match_date >= now,
            Match.status == "scheduled",
        )
    )).scalar_one()

    # Intelligence signals last 24h
    intel_q = await db.execute(
        select(IntelligenceSignal).where(IntelligenceSignal.created_at >= last_24h)
    )
    intel_signals = intel_q.scalars().all()
    signal_counts = {}
    for s in intel_signals:
        signal_counts[s.signal_type] = signal_counts.get(s.signal_type, 0) + 1

    latest_intel = (await db.execute(
        select(IntelligenceSignal.created_at).order_by(IntelligenceSignal.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    # News articles
    try:
        news_total = (await db.execute(
            select(func.count()).select_from(NewsArticle)
        )).scalar_one()
        news_last_24h = (await db.execute(
            select(func.count()).select_from(NewsArticle).where(
                NewsArticle.created_at >= last_24h
            )
        )).scalar_one()
        latest_news_time = (await db.execute(
            select(NewsArticle.created_at).order_by(NewsArticle.created_at.desc()).limit(1)
        )).scalar_one_or_none()
    except Exception:
        news_total = 0
        news_last_24h = 0
        latest_news_time = None

    # Recent performance (last 30 days)
    perf_logs = (await db.execute(
        select(PerformanceLog).where(
            PerformanceLog.log_date >= now - timedelta(days=30),
            PerformanceLog.ai_decision == "PLAY",
            PerformanceLog.is_correct.isnot(None),
        )
    )).scalars().all()
    resolved = len(perf_logs)
    wins_30d = sum(1 for l in perf_logs if l.is_correct)

    # Confidence distribution from active decisions
    conf_buckets = {"high": 0, "medium": 0, "low": 0}
    active_decisions = (await db.execute(
        select(MatchDecision)
        .join(Match, Match.id == MatchDecision.match_id)
        .where(
            MatchDecision.ai_decision == "PLAY",
            Match.match_date >= now,
            Match.status == "scheduled",
        )
    )).scalars().all()
    for d in active_decisions:
        if d.confidence_score >= 75:
            conf_buckets["high"] += 1
        elif d.confidence_score >= 60:
            conf_buckets["medium"] += 1
        else:
            conf_buckets["low"] += 1

    return {
        "predictions": {
            "total": total_predictions,
            "today": predictions_today,
            "active_plays": play_count,
        },
        "intelligence": {
            "signals_last_24h": len(intel_signals),
            "by_type": signal_counts,
            "last_run": latest_intel.isoformat() if latest_intel else None,
        },
        "news": {
            "total_articles": news_total,
            "articles_last_24h": news_last_24h,
            "last_fetched": latest_news_time.isoformat() if latest_news_time else None,
        },
        "performance": {
            "resolved_30d": resolved,
            "wins_30d": wins_30d,
            "win_rate_30d": round(wins_30d / resolved, 3) if resolved else None,
        },
        "confidence_distribution": conf_buckets,
        "model_info": {
            "type": "XGBoost + LightGBM ensemble (isotonic calibrated)",
            "training": "2-year rolling window — time-based split, recency-weighted samples",
            "markets": "7 ML markets (1X2, O1.5/2.5/3.5, BTTS, Home CS, Away CS) + 25+ Poisson-derived",
            "decision_gate": "Value-driven: probability + confidence + EV ≥ 3% + edge ≥ 5% + low-odds penalty",
            "kelly": "Tiered Kelly — full/75%/50%/25% based on confidence + edge tier",
            "clv": "Closing Line Value tracked per pick to verify real edge",
            "drift": "Automatic drift detection — confidence penalised if log_loss degrades > 5%",
            "real_time": "Intelligence signals (news/injuries) adjust confidence ±15 pts",
            "retraining": "Automatic weekly retraining every Sunday 03:00 UTC",
            "features": [
                "ELO ratings", "H2H form", "Goals scored/conceded (last 5)",
                "Home/away advantage", "Competition tier", "Rest days",
                "Betting market odds (edge vs implied prob)", "Over 2.5 history",
                "Dixon-Coles Poisson strength model",
            ],
        },
    }


@router.get("/analytics/training-history")
async def training_history(db: AsyncSession = Depends(get_async_session)):
    """Return model training log — shows continuous learning progress."""
    import json as _json
    from data.db_models.models import ModelTrainingLog

    try:
        result = await db.execute(
            select(ModelTrainingLog).order_by(ModelTrainingLog.trained_at.desc()).limit(50)
        )
        logs = result.scalars().all()
    except Exception:
        return {"logs": [], "message": "Training log table not yet created — restart backend"}

    return {
        "logs": [
            {
                "id": l.id,
                "sport": l.sport_key,
                "status": l.status,
                "training_rows": l.training_rows,
                "accuracy": _json.loads(l.accuracy_json) if l.accuracy_json else {},
                "trained_at": l.trained_at.isoformat(),
            }
            for l in logs
        ]
    }


@router.post("/analytics/trigger-retrain")
async def trigger_retrain(background_tasks: BackgroundTasks):
    """Manually trigger a full model retrain (runs in background, takes ~5-10 min)."""
    def _run():
        from data.database import get_sync_session
        from ml.continuous_learner import run_full_retrain
        with get_sync_session() as db:
            run_full_retrain(db)

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Retraining all sport models in background. Check /analytics after ~10 minutes."}
