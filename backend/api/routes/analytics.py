"""
Comprehensive analytics API for the PlaySigma Intelligence Dashboard.

Endpoints:
  GET /overview              — KPI snapshot (accuracy, ROI, signals, picks)
  GET /accuracy-timeline     — Rolling accuracy over time (daily, last 90 days)
  GET /roi-timeline          — Cumulative P&L over time
  GET /market-performance    — Accuracy + ROI by market (1X2, BTTS, Over/Under)
  GET /league-performance    — Accuracy + ROI by competition (top 12)
  GET /calibration           — Calibration curve: predicted prob vs actual win rate
  GET /feature-importance    — Top features from trained XGBoost model
  GET /signals-feed          — Recent intelligence signals (last 7 days)
  GET /confidence-histogram  — Distribution of prediction confidence scores
  GET /model-health          — Model versions, training freshness, data stats
"""
from __future__ import annotations

import json
import pickle
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from data.database import get_async_session

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ── Overview ──────────────────────────────────────────────────────────────────

@router.get("/overview")
async def analytics_overview(db: AsyncSession = Depends(get_async_session)):
    """
    Master KPI card data.
    Returns overall accuracy, ROI, active picks, signal counts, data volume.
    """
    from data.db_models.models import (
        PerformanceLog, MatchDecision, IntelligenceSignal, Match,
        ModelTrainingLog, NewsArticle,
    )

    now = datetime.utcnow()
    d30 = now - timedelta(days=30)
    d7  = now - timedelta(days=7)
    d1  = now - timedelta(days=1)

    # ── Performance (all time) ────────────────────────────────────────
    perf_all = (await db.execute(
        select(
            func.count(PerformanceLog.id).label("total"),
            func.sum(case((PerformanceLog.is_correct == True, 1), else_=0)).label("wins"),
            func.sum(PerformanceLog.profit_loss_units).label("roi"),
        )
        .where(PerformanceLog.ai_decision == "PLAY")
    )).one()

    # ── Performance (last 30 days) ────────────────────────────────────
    perf_30 = (await db.execute(
        select(
            func.count(PerformanceLog.id).label("total"),
            func.sum(case((PerformanceLog.is_correct == True, 1), else_=0)).label("wins"),
            func.sum(PerformanceLog.profit_loss_units).label("roi"),
        )
        .where(PerformanceLog.ai_decision == "PLAY", PerformanceLog.log_date >= d30)
    )).one()

    # ── Active PLAY picks ─────────────────────────────────────────────
    active_plays = (await db.execute(
        select(func.count(MatchDecision.id))
        .join(Match, Match.id == MatchDecision.match_id)
        .where(MatchDecision.ai_decision == "PLAY", Match.status == "scheduled")
    )).scalar() or 0

    # ── Intel signals ─────────────────────────────────────────────────
    signals_7d = (await db.execute(
        select(func.count(IntelligenceSignal.id))
        .where(IntelligenceSignal.created_at >= d7)
    )).scalar() or 0

    signals_24h = (await db.execute(
        select(func.count(IntelligenceSignal.id))
        .where(IntelligenceSignal.created_at >= d1)
    )).scalar() or 0

    # ── Training ──────────────────────────────────────────────────────
    last_train = (await db.execute(
        select(ModelTrainingLog)
        .order_by(ModelTrainingLog.trained_at.desc())
        .limit(1)
    )).scalars().first()

    # ── Matches in DB ─────────────────────────────────────────────────
    total_matches = (await db.execute(select(func.count(Match.id)))).scalar() or 0
    finished_matches = (await db.execute(
        select(func.count(Match.id)).where(Match.status == "finished")
    )).scalar() or 0

    total   = perf_all.total or 0
    wins    = perf_all.wins  or 0
    roi_all = float(perf_all.roi or 0)

    return {
        "accuracy": {
            "all_time":    round(wins / total, 4) if total > 0 else None,
            "total_picks": total,
            "total_wins":  wins,
        },
        "roi": {
            "all_time_units":  round(roi_all, 2),
            "last_30d_units":  round(float(perf_30.roi or 0), 2),
            "last_30d_picks":  perf_30.total or 0,
        },
        "active_plays":   active_plays,
        "signals": {
            "last_7d":  signals_7d,
            "last_24h": signals_24h,
        },
        "data": {
            "total_matches":    total_matches,
            "finished_matches": finished_matches,
        },
        "last_retrain": last_train.trained_at.isoformat() if last_train else None,
    }


# ── Accuracy timeline ─────────────────────────────────────────────────────────

@router.get("/accuracy-timeline")
async def accuracy_timeline(
    days: int = 90,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Daily accuracy rate for the last `days` days.
    Uses a 14-day rolling window so single-day variance is smoothed.
    Returns list of {date, accuracy, picks, cumulative_roi}.
    """
    from data.db_models.models import PerformanceLog

    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (await db.execute(
        select(PerformanceLog)
        .where(
            PerformanceLog.ai_decision == "PLAY",
            PerformanceLog.log_date >= cutoff,
            PerformanceLog.is_correct.isnot(None),
        )
        .order_by(PerformanceLog.log_date)
    )).scalars().all()

    if not rows:
        return {"data": [], "total": 0}

    # Group by date
    by_date: dict[str, list] = defaultdict(list)
    for r in rows:
        day = r.log_date.strftime("%Y-%m-%d")
        by_date[day].append(r)

    # Build daily + rolling cumulative series
    result = []
    all_rows_sorted = sorted(rows, key=lambda x: x.log_date)
    cumulative_roi = 0.0

    for day in sorted(by_date.keys()):
        day_rows = by_date[day]
        correct = sum(1 for r in day_rows if r.is_correct)
        cumulative_roi += sum(r.profit_loss_units or 0 for r in day_rows)
        result.append({
            "date":           day,
            "accuracy":       round(correct / len(day_rows), 4) if day_rows else None,
            "picks":          len(day_rows),
            "cumulative_roi": round(cumulative_roi, 2),
        })

    # Add 14-day rolling accuracy
    window = 14
    for i, point in enumerate(result):
        slice_ = result[max(0, i - window + 1): i + 1]
        total  = sum(p["picks"] for p in slice_)
        wins   = sum(round(p["accuracy"] * p["picks"]) for p in slice_ if p["accuracy"] is not None)
        point["rolling_accuracy"] = round(wins / total, 4) if total > 0 else None

    return {"data": result, "total": len(rows)}


# ── ROI timeline ──────────────────────────────────────────────────────────────

@router.get("/roi-timeline")
async def roi_timeline(
    days: int = 90,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Cumulative P&L over time, broken down by market.
    Returns list of {date, cumulative_roi, daily_roi, by_market}.
    """
    from data.db_models.models import PerformanceLog

    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (await db.execute(
        select(PerformanceLog)
        .where(
            PerformanceLog.ai_decision == "PLAY",
            PerformanceLog.log_date >= cutoff,
            PerformanceLog.profit_loss_units.isnot(None),
        )
        .order_by(PerformanceLog.log_date)
    )).scalars().all()

    if not rows:
        return {"data": []}

    by_date: dict[str, list] = defaultdict(list)
    for r in rows:
        by_date[r.log_date.strftime("%Y-%m-%d")].append(r)

    cumulative = 0.0
    result = []
    for day in sorted(by_date.keys()):
        day_rows = by_date[day]
        daily = sum(r.profit_loss_units or 0 for r in day_rows)
        cumulative += daily

        by_market: dict[str, float] = defaultdict(float)
        for r in day_rows:
            market = _classify_market(r.predicted_outcome or "")
            by_market[market] += r.profit_loss_units or 0

        result.append({
            "date":           day,
            "daily_roi":      round(daily, 2),
            "cumulative_roi": round(cumulative, 2),
            "by_market":      {k: round(v, 2) for k, v in by_market.items()},
        })

    return {"data": result}


# ── Market performance ────────────────────────────────────────────────────────

@router.get("/market-performance")
async def market_performance(db: AsyncSession = Depends(get_async_session)):
    """
    Accuracy, ROI and pick count broken down by betting market.
    Markets: 1X2 (result), Over/Under, BTTS.
    """
    from data.db_models.models import PerformanceLog

    rows = (await db.execute(
        select(PerformanceLog)
        .where(
            PerformanceLog.ai_decision == "PLAY",
            PerformanceLog.is_correct.isnot(None),
        )
    )).scalars().all()

    buckets: dict[str, dict] = defaultdict(lambda: {"picks": 0, "wins": 0, "roi": 0.0})
    for r in rows:
        m = _classify_market(r.predicted_outcome or "")
        buckets[m]["picks"] += 1
        if r.is_correct:
            buckets[m]["wins"] += 1
        buckets[m]["roi"] += r.profit_loss_units or 0

    result = []
    for market, stats in sorted(buckets.items()):
        picks = stats["picks"]
        wins  = stats["wins"]
        result.append({
            "market":   market,
            "picks":    picks,
            "wins":     wins,
            "accuracy": round(wins / picks, 4) if picks > 0 else None,
            "roi":      round(stats["roi"], 2),
        })

    return {"data": result}


# ── League performance ────────────────────────────────────────────────────────

@router.get("/league-performance")
async def league_performance(db: AsyncSession = Depends(get_async_session)):
    """
    Accuracy + ROI per competition, top 15 by pick volume.
    """
    from data.db_models.models import PerformanceLog

    rows = (await db.execute(
        select(PerformanceLog)
        .where(
            PerformanceLog.ai_decision == "PLAY",
            PerformanceLog.is_correct.isnot(None),
        )
    )).scalars().all()

    buckets: dict[str, dict] = defaultdict(lambda: {"picks": 0, "wins": 0, "roi": 0.0})
    for r in rows:
        comp = r.competition or "Unknown"
        buckets[comp]["picks"] += 1
        if r.is_correct:
            buckets[comp]["wins"] += 1
        buckets[comp]["roi"] += r.profit_loss_units or 0

    result = []
    for comp, stats in sorted(buckets.items(), key=lambda x: -x[1]["picks"])[:15]:
        picks = stats["picks"]
        wins  = stats["wins"]
        result.append({
            "competition": comp,
            "picks":       picks,
            "wins":        wins,
            "accuracy":    round(wins / picks, 4) if picks > 0 else None,
            "roi":         round(stats["roi"], 2),
        })

    return {"data": result}


# ── Calibration curve ─────────────────────────────────────────────────────────

@router.get("/calibration")
async def calibration_curve(db: AsyncSession = Depends(get_async_session)):
    """
    Calibration curve: predicted probability bucket vs actual win rate.
    Perfect calibration = diagonal (predicted 0.6 → actual 60% win rate).
    Deviations reveal over/under-confidence in specific ranges.

    Returns list of {bucket_low, bucket_high, predicted_avg, actual_rate, count}.
    """
    from data.db_models.models import PerformanceLog

    rows = (await db.execute(
        select(PerformanceLog)
        .where(
            PerformanceLog.ai_decision == "PLAY",
            PerformanceLog.is_correct.isnot(None),
            PerformanceLog.predicted_prob.isnot(None),
        )
    )).scalars().all()

    # 10 buckets: 0-10%, 10-20%, ... 90-100%
    buckets: dict[int, dict] = {i: {"predicted_sum": 0.0, "wins": 0, "count": 0} for i in range(10)}

    for r in rows:
        prob = float(r.predicted_prob)
        bucket = min(9, int(prob * 10))
        buckets[bucket]["predicted_sum"] += prob
        buckets[bucket]["count"]         += 1
        if r.is_correct:
            buckets[bucket]["wins"] += 1

    result = []
    for i, b in buckets.items():
        if b["count"] < 3:
            continue
        result.append({
            "bucket_label":   f"{i*10}–{(i+1)*10}%",
            "bucket_mid":     (i * 10 + 5) / 100,
            "predicted_avg":  round(b["predicted_sum"] / b["count"], 4),
            "actual_rate":    round(b["wins"] / b["count"], 4),
            "count":          b["count"],
        })

    return {"data": result}


# ── Feature importance ────────────────────────────────────────────────────────

@router.get("/feature-importance")
async def feature_importance(sport: str = "football"):
    """
    Extract feature importance from the trained XGBoost model.
    Returns top 20 features sorted by importance score.
    Color-coded by feature group for the chart.
    """
    from ml.models.sport_model import MODEL_DIR
    from features.engineering import COMMON_FEATURES
    import numpy as np

    model_path = MODEL_DIR / f"{sport}_model.pkl"
    if not model_path.exists():
        return {"data": [], "status": "no_model"}

    try:
        with open(model_path, "rb") as f:
            model = pickle.load(f)

        # Get result model's XGBoost component
        result_clf = model.models.get("result")
        if not result_clf:
            return {"data": [], "status": "no_result_model"}

        # Handle ensemble vs single classifier
        xgb_clf = getattr(result_clf, "clf1", result_clf)
        if not hasattr(xgb_clf, "feature_importances_"):
            return {"data": [], "status": "no_importances"}

        importances = xgb_clf.feature_importances_
        features    = COMMON_FEATURES

        pairs = sorted(
            zip(features, importances),
            key=lambda x: -x[1]
        )[:20]

        result = []
        for name, score in pairs:
            result.append({
                "feature":   name,
                "importance": round(float(score), 5),
                "group":     _feature_group(name),
                "label":     _feature_label(name),
            })

        return {"data": result, "sport": sport}

    except Exception as e:
        return {"data": [], "status": f"error: {e}"}


# ── Intelligence signals feed ─────────────────────────────────────────────────

@router.get("/signals-feed")
async def signals_feed(
    days: int = 7,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Recent intelligence signals with daily volume breakdown.
    Returns recent entries + daily histogram for the last `days` days.
    """
    from data.db_models.models import IntelligenceSignal

    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (await db.execute(
        select(IntelligenceSignal)
        .where(IntelligenceSignal.created_at >= cutoff)
        .order_by(IntelligenceSignal.created_at.desc())
        .limit(50)
    )).scalars().all()

    # Daily volume
    daily: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        day = r.created_at.strftime("%Y-%m-%d")
        daily[day][r.signal_type] += 1

    feed = [
        {
            "id":          r.id,
            "team":        r.team_name,
            "type":        r.signal_type,
            "entity":      r.entity_name or "",
            "impact":      r.impact_score,
            "confidence":  r.confidence,
            "time":        r.created_at.isoformat(),
        }
        for r in rows[:20]
    ]

    daily_chart = [
        {"date": d, **counts}
        for d, counts in sorted(daily.items())
    ]

    return {"feed": feed, "daily": daily_chart}


# ── Confidence histogram ──────────────────────────────────────────────────────

@router.get("/confidence-histogram")
async def confidence_histogram(db: AsyncSession = Depends(get_async_session)):
    """
    Distribution of confidence scores for all PLAY decisions.
    Returns histogram buckets: [50-55, 55-60, 60-65, 65-70, 70-75, 75-80, 80-85, 85-90, 90+]
    """
    from data.db_models.models import MatchDecision

    rows = (await db.execute(
        select(MatchDecision.confidence_score, MatchDecision.ai_decision)
        .where(MatchDecision.ai_decision == "PLAY")
    )).all()

    buckets = [
        {"range": "50–55", "min": 50, "max": 55, "count": 0},
        {"range": "55–60", "min": 55, "max": 60, "count": 0},
        {"range": "60–65", "min": 60, "max": 65, "count": 0},
        {"range": "65–70", "min": 65, "max": 70, "count": 0},
        {"range": "70–75", "min": 70, "max": 75, "count": 0},
        {"range": "75–80", "min": 75, "max": 80, "count": 0},
        {"range": "80–85", "min": 80, "max": 85, "count": 0},
        {"range": "85–90", "min": 85, "max": 90, "count": 0},
        {"range": "90+",   "min": 90, "max": 101, "count": 0},
    ]

    for score, _ in rows:
        s = float(score or 0)
        for b in buckets:
            if b["min"] <= s < b["max"]:
                b["count"] += 1
                break

    # Also count SKIP decisions for ratio
    skip_count = (await db.execute(
        select(func.count(MatchDecision.id))
        .where(MatchDecision.ai_decision == "SKIP")
    )).scalar() or 0

    play_count = len(rows)

    return {
        "histogram":    buckets,
        "play_count":   play_count,
        "skip_count":   skip_count,
        "play_rate":    round(play_count / (play_count + skip_count), 4) if (play_count + skip_count) > 0 else None,
    }


# ── Training progress (live) ──────────────────────────────────────────────────

@router.get("/training-progress")
async def training_progress():
    """Live training progress — poll this while is_training=true."""
    from ml.training_progress import get_state
    return get_state()


# ── Model health ──────────────────────────────────────────────────────────────

@router.get("/model-health")
async def model_health(db: AsyncSession = Depends(get_async_session)):
    """
    Model file status, training history summary, data freshness.
    """
    from data.db_models.models import ModelTrainingLog, Match, PerformanceLog
    from ml.models.sport_model import MODEL_DIR

    # Training logs (last 10 per sport)
    logs = (await db.execute(
        select(ModelTrainingLog)
        .order_by(ModelTrainingLog.trained_at.desc())
        .limit(20)
    )).scalars().all()

    # Model files on disk
    model_files = []
    for f in MODEL_DIR.glob("*_model.pkl"):
        sport = f.stem.replace("_model", "")
        try:
            size_kb = round(f.stat().st_size / 1024)
            mtime   = datetime.fromtimestamp(f.stat().st_mtime).isoformat()
        except Exception:
            size_kb = 0
            mtime   = None
        model_files.append({"sport": sport, "size_kb": size_kb, "modified": mtime})

    # Latest match date in DB (data freshness)
    latest_match = (await db.execute(
        select(func.max(Match.match_date))
    )).scalar()

    # Total performance logs
    perf_count = (await db.execute(select(func.count(PerformanceLog.id)))).scalar() or 0

    training_history = [
        {
            "id":            l.id,
            "sport":         l.sport_key,
            "status":        l.status,
            "training_rows": l.training_rows,
            "accuracy":      json.loads(l.accuracy_json) if l.accuracy_json else {},
            "trained_at":    l.trained_at.isoformat(),
        }
        for l in logs
    ]

    return {
        "model_files":       model_files,
        "training_history":  training_history,
        "latest_match_date": latest_match.isoformat() if latest_match else None,
        "performance_logs":  perf_count,
        "features_count":    _get_feature_count(),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _classify_market(outcome: str) -> str:
    outcome = (outcome or "").upper()
    if outcome in ("H", "D", "A"):
        return "1X2"
    if outcome in ("OVER", "UNDER"):
        return "Over/Under"
    if outcome in ("YES", "NO"):
        return "BTTS"
    return "Other"


def _feature_group(name: str) -> str:
    if name.startswith("elo") or name in ("home_elo", "away_elo"):
        return "Elo"
    if name.startswith("dc_"):
        return "Poisson"
    if name.startswith("imp_") or name == "market_margin":
        return "Market Odds"
    if "shot" in name or "sot" in name or "xg" in name or "conv" in name:
        return "Shots / xG"
    if "ref_" in name:
        return "Referee"
    if "injury" in name:
        return "Intelligence"
    if "h2h" in name:
        return "H2H"
    if "win_rate" in name or "goals_avg" in name or "btts" in name or "over25" in name:
        return "Form"
    if "attack" in name or "defence" in name or "exp_" in name:
        return "Strength"
    if "league" in name or "form_points" in name or "pts_rate" in name:
        return "Table"
    if "days_rest" in name:
        return "Fatigue"
    return "Other"


def _feature_label(name: str) -> str:
    """Human-readable label for a feature."""
    labels = {
        "home_elo": "Home Elo",
        "away_elo": "Away Elo",
        "elo_diff": "Elo Difference",
        "elo_home_prob": "Elo: Home Win Prob",
        "elo_draw_prob": "Elo: Draw Prob",
        "elo_away_prob": "Elo: Away Win Prob",
        "imp_home_prob": "Market: Home Prob",
        "imp_draw_prob": "Market: Draw Prob",
        "imp_away_prob": "Market: Away Prob",
        "market_margin": "Bookmaker Margin",
        "home_win_rate_5": "Home Win Rate (L5)",
        "away_win_rate_5": "Away Win Rate (L5)",
        "home_goals_avg_5": "Home Goals/Game (L5)",
        "away_goals_avg_5": "Away Goals/Game (L5)",
        "home_goals_conceded_avg_5": "Home Conceded/Game (L5)",
        "away_goals_conceded_avg_5": "Away Conceded/Game (L5)",
        "h2h_home_win_rate": "H2H Home Win Rate",
        "h2h_avg_goals": "H2H Avg Goals",
        "home_attack_str": "Home Attack Strength",
        "away_attack_str": "Away Attack Strength",
        "home_defence_str": "Home Defence Strength",
        "away_defence_str": "Away Defence Strength",
        "exp_home_goals": "Expected Home Goals",
        "exp_away_goals": "Expected Away Goals",
        "exp_total_goals": "Expected Total Goals",
        "home_xg_proxy_5": "Home xG Proxy (L5)",
        "away_xg_proxy_5": "Away xG Proxy (L5)",
        "home_sot_avg_5": "Home Shots on Target (L5)",
        "away_sot_avg_5": "Away Shots on Target (L5)",
        "home_shot_conv_5": "Home Shot Conversion",
        "away_shot_conv_5": "Away Shot Conversion",
        "ref_avg_goals": "Referee Avg Goals",
        "ref_avg_cards": "Referee Avg Cards",
        "dc_home_win": "DC: Home Win Prob",
        "dc_draw": "DC: Draw Prob",
        "dc_away_win": "DC: Away Win Prob",
        "dc_over_2_5": "DC: Over 2.5",
        "dc_btts_yes": "DC: BTTS Yes",
        "home_injury_impact": "Home Injury Impact",
        "away_injury_impact": "Away Injury Impact",
        "home_days_rest": "Home Days Rest",
        "away_days_rest": "Away Days Rest",
        "home_league_pts_rate": "Home League Pts/Game",
        "away_league_pts_rate": "Away League Pts/Game",
        "home_form_points": "Home Form Points (L5)",
        "away_form_points": "Away Form Points (L5)",
        "pts_rate_diff": "Points Rate Differential",
        "form_points_diff": "Form Points Differential",
    }
    return labels.get(name, name.replace("_", " ").title())


def _get_feature_count() -> int:
    try:
        from features.engineering import COMMON_FEATURES
        return len(COMMON_FEATURES)
    except Exception:
        return 50


# ── Per-sport breakdown ───────────────────────────────────────────────────────

@router.get("/sport-breakdown")
async def sport_breakdown(db: AsyncSession = Depends(get_async_session)):
    """
    Accuracy, ROI, pick count, and training data volume broken down by sport.
    Gives a holistic view of how well the AI performs across each sport.
    """
    from data.db_models.models import PerformanceLog, Match, Competition, Sport, ModelTrainingLog

    # Performance per sport
    perf_rows = (await db.execute(
        select(PerformanceLog)
        .where(
            PerformanceLog.ai_decision == "PLAY",
            PerformanceLog.is_correct.isnot(None),
        )
    )).scalars().all()

    perf_by_sport: dict[str, dict] = {}
    for r in perf_rows:
        sk = r.sport_key or "unknown"
        if sk not in perf_by_sport:
            perf_by_sport[sk] = {"picks": 0, "wins": 0, "roi": 0.0}
        perf_by_sport[sk]["picks"] += 1
        if r.is_correct:
            perf_by_sport[sk]["wins"] += 1
        perf_by_sport[sk]["roi"] += r.profit_loss_units or 0

    # Match counts per sport
    match_rows = (await db.execute(
        select(Sport.key, func.count(Match.id).label("total"),
               func.sum(case((Match.status == "finished", 1), else_=0)).label("finished"))
        .join(Competition, Competition.sport_id == Sport.id)
        .join(Match, Match.competition_id == Competition.id)
        .group_by(Sport.key)
    )).all()
    match_counts = {r.key: {"total": r.total, "finished": r.finished} for r in match_rows}

    # Latest training log per sport
    train_rows = (await db.execute(
        select(ModelTrainingLog)
        .order_by(ModelTrainingLog.trained_at.desc())
        .limit(50)
    )).scalars().all()
    last_train: dict[str, dict] = {}
    for t in train_rows:
        if t.sport_key not in last_train:
            last_train[t.sport_key] = {
                "trained_at":    t.trained_at.isoformat(),
                "training_rows": t.training_rows,
                "accuracy":      json.loads(t.accuracy_json) if t.accuracy_json else {},
            }

    # Merge into sport summary
    all_sports = set(list(perf_by_sport.keys()) + list(match_counts.keys()) + list(last_train.keys()))
    result = []
    for sk in sorted(all_sports):
        perf = perf_by_sport.get(sk, {"picks": 0, "wins": 0, "roi": 0.0})
        mc   = match_counts.get(sk, {"total": 0, "finished": 0})
        tr   = last_train.get(sk)
        picks = perf["picks"]
        wins  = perf["wins"]

        # Convert log_loss to rough accuracy % (lower log_loss = better)
        # result market log_loss of 1.0 ≈ 33% acc (random); 0.8 ≈ ~55%
        model_accuracy = None
        if tr and tr["accuracy"].get("result") is not None:
            ll = float(tr["accuracy"]["result"])
            # Heuristic conversion: log_loss 1.0 → 33%, 0.5 → 65%, 0.3 → 80%
            model_accuracy = max(0.0, min(1.0, 1.0 - (ll / 1.5)))

        result.append({
            "sport":           sk,
            "display_name":    sk.replace("_", " ").title(),
            "matches_total":   mc["total"],
            "matches_finished": mc["finished"],
            "picks":           picks,
            "wins":            wins,
            "accuracy":        round(wins / picks, 4) if picks > 0 else None,
            "roi":             round(perf["roi"], 2),
            "model_accuracy":  round(model_accuracy, 4) if model_accuracy is not None else None,
            "training_rows":   tr["training_rows"] if tr else 0,
            "last_trained":    tr["trained_at"] if tr else None,
        })

    # Sort: sports with most training data first
    result.sort(key=lambda x: -(x["training_rows"] or 0))
    return {"data": result}


# ── Learning curve ────────────────────────────────────────────────────────────

@router.get("/learning-curve")
async def learning_curve(db: AsyncSession = Depends(get_async_session)):
    """
    Shows how model accuracy improves over time as more data is consumed.
    Uses ModelTrainingLog — each weekly retrain is one data point.
    Returns {sport -> [{trained_at, training_rows, log_loss_result, log_loss_over25, log_loss_btts}]}
    """
    from data.db_models.models import ModelTrainingLog

    logs = (await db.execute(
        select(ModelTrainingLog)
        .where(ModelTrainingLog.status == "trained")
        .order_by(ModelTrainingLog.trained_at)
    )).scalars().all()

    by_sport: dict[str, list] = {}
    for log in logs:
        sk = log.sport_key
        if sk not in by_sport:
            by_sport[sk] = []
        acc = json.loads(log.accuracy_json) if log.accuracy_json else {}
        by_sport[sk].append({
            "trained_at":    log.trained_at.isoformat(),
            "training_rows": log.training_rows,
            "ll_result":     round(acc.get("result",  1.0), 4) if acc.get("result")  is not None else None,
            "ll_over25":     round(acc.get("over25",  1.0), 4) if acc.get("over25")  is not None else None,
            "ll_btts":       round(acc.get("btts",    1.0), 4) if acc.get("btts")    is not None else None,
            # Rough accuracy estimate from log_loss (lower is better)
            "accuracy_est":  round(max(0.0, min(1.0, 1.0 - (acc.get("result", 1.0) / 1.5))), 4)
                             if acc.get("result") is not None else None,
        })

    return {"data": by_sport, "sports": list(by_sport.keys())}
