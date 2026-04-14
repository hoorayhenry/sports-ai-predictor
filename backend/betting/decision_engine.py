"""
AI Decision Engine — the brain of the autonomous betting assistant.

Responsibilities:
  - Compute confidence scores (0-100) for each match prediction
  - Issue PLAY / SKIP decisions based on multi-factor logic
  - Detect volatile / uncertain matches
  - Generate 10 daily Smart Sets (curated 10-match packages)
  - Self-optimize via per-competition/sport weights from historical results
"""
from __future__ import annotations
import json
import math
import random
from datetime import datetime, date, timedelta
from typing import Optional
from loguru import logger
from sqlalchemy.orm import Session

from data.db_models.models import (
    Match, Prediction, MatchDecision, SmartSet,
    PerformanceLog, OptimizationWeight, Competition, Sport,
)

# ──────────────────────────── thresholds ────────────────────────────
PLAY_PROB_THRESHOLD      = 0.65   # minimum top-outcome probability to PLAY
PLAY_CONFIDENCE_THRESHOLD = 70.0  # minimum confidence score to PLAY
VOLATILITY_MARGIN        = 0.15   # gap between top two outcomes must exceed this
RISKY_FORM_RATE          = 0.30   # form win-rate below this triggers volatility flag
HIGH_PROB_THRESHOLD      = 0.75
MEDIUM_PROB_THRESHOLD    = 0.60

NUM_SETS       = 10
SET_SIZE       = 10
MIN_SET_CONF   = 60.0   # minimum average confidence for a valid set
# ────────────────────────────────────────────────────────────────────


# ── Confidence score ─────────────────────────────────────────────────

def _get_opt_weight(db: Session, sport_key: str, competition: str) -> float:
    """Return blended optimization weight for sport+competition (−10…+10)."""
    comp_key  = f"{sport_key}_{competition}"
    sport_key_ = sport_key
    weight = 0.0
    for scope in [comp_key, sport_key_, "global"]:
        row = db.query(OptimizationWeight).filter_by(scope_key=scope).first()
        if row and row.sample_size >= 10:
            weight += row.weight * 0.5
    return max(-10, min(10, weight))


def compute_confidence_score(
    top_prob: float,
    ev: Optional[float],
    elo_diff_abs: float,          # |home_elo - away_elo|
    opt_boost: float = 0.0,
) -> tuple[float, float, float, float, float]:
    """
    Returns (total, prob_comp, ev_comp, form_comp, consistency_comp).

    Components:
      • Probability   (40%): scaled top-outcome probability
      • EV            (20%): expected value signal
      • Form proxy    (20%): approximated via ELO gap + top-prob synergy
      • Consistency   (20%): ELO gap stability (bigger gap → more predictable)
    """
    # Probability component (0-40)
    prob_comp = top_prob * 100 * 0.40

    # EV component (0-20) — neutral 10 if no EV, scales with positive EV
    if ev is None:
        ev_comp = 10.0
    else:
        ev_comp = min(20.0, max(0.0, 10.0 + ev * 60.0))

    # Form proxy (0-20) — high top_prob + ELO advantage → good form
    # ELO diffs: 0→flat, 100→slight edge, 300+→strong edge
    elo_form = min(1.0, elo_diff_abs / 400.0)
    form_comp = (top_prob * 0.7 + elo_form * 0.3) * 20.0

    # Consistency (0-20) — larger ELO gap means more predictable outcomes
    consistency_comp = min(20.0, (elo_diff_abs / 400.0) * 20.0)

    raw = prob_comp + ev_comp + form_comp + consistency_comp + opt_boost
    total = round(min(100.0, max(0.0, raw)), 1)
    return total, prob_comp, ev_comp, form_comp, consistency_comp


def classify_probability(prob: float) -> str:
    if prob >= HIGH_PROB_THRESHOLD:
        return "HIGH"
    elif prob >= MEDIUM_PROB_THRESHOLD:
        return "MEDIUM"
    return "RISKY"


def detect_volatility(
    home_prob: float,
    draw_prob: Optional[float],
    away_prob: float,
) -> tuple[bool, str]:
    """Returns (is_volatile, reason)."""
    probs = sorted(
        [p for p in [home_prob, draw_prob or 0.0, away_prob] if p > 0],
        reverse=True,
    )
    if len(probs) < 2:
        return False, ""

    margin = probs[0] - probs[1]
    if margin < VOLATILITY_MARGIN:
        return True, f"Outcomes too close ({margin:.0%} margin)"

    # Grey zone: top prob is "unsure" (40–65%)
    if 0.40 <= probs[0] < PLAY_PROB_THRESHOLD:
        return True, f"Grey-zone probability ({probs[0]:.0%})"

    return False, ""


def make_ai_decision(
    top_prob: float,
    confidence_score: float,
    has_volatility: bool,
) -> str:
    if (top_prob >= PLAY_PROB_THRESHOLD
            and confidence_score >= PLAY_CONFIDENCE_THRESHOLD
            and not has_volatility):
        return "PLAY"
    return "SKIP"


# ── Core entry point: process all upcoming matches ────────────────────

def process_decisions(db: Session) -> int:
    """
    Re-compute AI decisions for all upcoming scheduled matches that have a Prediction.
    Returns count of PLAY decisions.
    """
    from sqlalchemy.orm import joinedload

    matches = (
        db.query(Match)
        .join(Competition)
        .join(Sport)
        .options(
            joinedload(Match.home),
            joinedload(Match.away),
            joinedload(Match.competition).joinedload(Competition.sport),
            joinedload(Match.predictions),
            joinedload(Match.odds),
        )
        .filter(Match.status == "scheduled")
        .all()
    )

    play_count = 0
    for m in matches:
        pred: Optional[Prediction] = m.predictions[0] if m.predictions else None
        if not pred:
            continue

        sport_key   = m.competition.sport.key if m.competition and m.competition.sport else "unknown"
        competition = m.competition.name if m.competition else ""

        # Evaluate all markets: result + over/under + BTTS
        candidates = {
            "H":        pred.home_win_prob or 0.0,
            "D":        pred.draw_prob     or 0.0,
            "A":        pred.away_win_prob or 0.0,
        }

        # Add side markets only when model has made a prediction AND odds exist
        over25_prob = pred.over25_prob or 0.0
        btts_prob   = pred.btts_prob   or 0.0

        has_totals_odds = any(o.market == "totals" for o in m.odds)
        has_btts_odds   = any(o.market == "btts"   for o in m.odds)

        if over25_prob > 0 and has_totals_odds:
            # Use whichever side is stronger (over or under)
            under_prob = 1.0 - over25_prob
            if over25_prob >= under_prob:
                candidates["over"]  = over25_prob
            else:
                candidates["under"] = under_prob

        if btts_prob > 0 and has_btts_odds:
            btts_no_prob = 1.0 - btts_prob
            if btts_prob >= btts_no_prob:
                candidates["btts_yes"] = btts_prob
            else:
                candidates["btts_no"]  = btts_no_prob

        top_outcome = max(candidates, key=candidates.get)
        top_prob    = candidates[top_outcome]

        # Volatility only makes sense for match result market
        _result_probs = {k: v for k, v in candidates.items() if k in ("H", "D", "A")}

        # ELO diff
        home_elo = m.home.elo_rating if m.home else 1500.0
        away_elo = m.away.elo_rating if m.away else 1500.0
        elo_diff_abs = abs(home_elo - away_elo)

        # Optimization weight
        opt_boost = _get_opt_weight(db, sport_key, competition)

        # Intelligence boost (news/injury signals) — max ±15 points
        try:
            from intelligence.signals import get_intelligence_boost
            intel_boost = get_intelligence_boost(db, m.id)
        except Exception:
            intel_boost = 0.0

        # Compute score
        conf, p_comp, ev_comp, f_comp, c_comp = compute_confidence_score(
            top_prob, pred.expected_value, elo_diff_abs, opt_boost + intel_boost
        )

        # Volatility — only checked for result market (H/D/A)
        if top_outcome in ("H", "D", "A"):
            volatile, vol_reason = detect_volatility(
                pred.home_win_prob or 0.0,
                pred.draw_prob,
                pred.away_win_prob or 0.0,
            )
        else:
            # Side markets (over/under, BTTS) don't have three-way volatility
            volatile, vol_reason = False, ""

        # Decision
        decision = make_ai_decision(top_prob, conf, volatile)
        prob_tag  = classify_probability(top_prob)

        # Best odds for recommended outcome across all markets
        rec_odds = None
        outcome_to_market = {
            "H": ("h2h",   "home"),
            "D": ("h2h",   "draw"),
            "A": ("h2h",   "away"),
            "over":     ("totals", "over"),
            "under":    ("totals", "under"),
            "btts_yes": ("btts",   "yes"),
            "btts_no":  ("btts",   "no"),
        }
        if top_outcome in outcome_to_market:
            mkt, db_out = outcome_to_market[top_outcome]
            prices = [o.price for o in m.odds if o.market == mkt and o.outcome == db_out]
            if prices:
                rec_odds = max(prices)

        # Upsert MatchDecision
        md = db.query(MatchDecision).filter_by(match_id=m.id).first()
        if not md:
            md = MatchDecision(match_id=m.id)
            db.add(md)

        md.confidence_score        = conf
        md.prob_tag                = prob_tag
        md.ai_decision             = decision
        md.top_prob                = top_prob
        md.predicted_outcome       = top_outcome
        md.has_volatility          = volatile
        md.volatility_reason       = vol_reason
        md.prob_component          = p_comp
        md.ev_component            = ev_comp
        md.form_component          = f_comp
        md.consistency_component   = c_comp
        md.recommended_odds        = rec_odds
        md.recommended_stake_pct   = pred.kelly_stake
        md.updated_at              = datetime.utcnow()

        if decision == "PLAY":
            play_count += 1

    db.commit()
    logger.info(f"Decisions processed: {play_count} PLAY out of {len(matches)} scheduled matches")
    return play_count


# ── Smart Sets ────────────────────────────────────────────────────────

def generate_smart_sets(db: Session) -> list[SmartSet]:
    """
    Generate up to 10 unique Smart Sets for today+tomorrow.
    Each set has 10 matches, mixed sports, balanced risk.
    Falls back to SKIP matches if not enough PLAY ones.
    """
    from sqlalchemy.orm import joinedload

    cutoff = datetime.utcnow() + timedelta(days=7)

    # Fetch all upcoming decisions with predictions (7-day window)
    matches = (
        db.query(Match)
        .join(Competition)
        .join(Sport)
        .join(MatchDecision, Match.id == MatchDecision.match_id)
        .join(Prediction, Match.id == Prediction.match_id)
        .options(
            joinedload(Match.home),
            joinedload(Match.away),
            joinedload(Match.competition).joinedload(Competition.sport),
            joinedload(Match.predictions),
            joinedload(Match.odds),
        )
        .filter(
            Match.status == "scheduled",
            Match.match_date >= datetime.utcnow(),
            Match.match_date <= cutoff,
        )
        .all()
    )

    if len(matches) < SET_SIZE:
        logger.warning(f"Only {len(matches)} matches available for smart sets")
        return []

    # Build candidate list with scores
    candidates = []
    for m in matches:
        md   = db.query(MatchDecision).filter_by(match_id=m.id).first()
        pred = m.predictions[0] if m.predictions else None
        if not md or not pred:
            continue
        sport_key = m.competition.sport.key if m.competition and m.competition.sport else "unknown"
        top_prob  = md.top_prob
        rec_odds  = md.recommended_odds or 1.5
        candidates.append({
            "match_id":      m.id,
            "home_team":     m.home.name if m.home else "TBD",
            "away_team":     m.away.name if m.away else "TBD",
            "sport":         sport_key,
            "sport_icon":    m.competition.sport.icon if m.competition and m.competition.sport else "🏆",
            "competition":   m.competition.name if m.competition else "",
            "match_date":    m.match_date.isoformat(),
            "ai_decision":   md.ai_decision,
            "confidence":    md.confidence_score,
            "prob_tag":      md.prob_tag,
            "predicted_outcome": md.predicted_outcome,
            "top_prob":      top_prob,
            "rec_odds":      rec_odds,
            "home_win_prob": pred.home_win_prob,
            "draw_prob":     pred.draw_prob,
            "away_win_prob": pred.away_win_prob,
        })

    # Sort: PLAY first, then by confidence desc
    candidates.sort(key=lambda x: (x["ai_decision"] == "SKIP", -x["confidence"]))

    # Delete today's old sets before regenerating
    db.query(SmartSet).filter(
        SmartSet.generated_date >= datetime.utcnow().replace(hour=0, minute=0, second=0)
    ).delete()
    db.commit()

    sets_created = []
    used_ids     = set()
    sports_available = list({c["sport"] for c in candidates})

    for set_num in range(1, NUM_SETS + 1):
        available = [c for c in candidates if c["match_id"] not in used_ids]
        if len(available) < SET_SIZE:
            break

        # Balance risk: ~60% HIGH+MEDIUM, ~40% any
        high_med = [c for c in available if c["prob_tag"] in ("HIGH", "MEDIUM")]
        risky    = [c for c in available if c["prob_tag"] == "RISKY"]

        set_matches = []
        # Try to get a sport-balanced mix
        sport_quota = {s: max(1, SET_SIZE // len(sports_available)) for s in sports_available}
        sport_count = {s: 0 for s in sports_available}

        # Fill with high/medium first
        pool = high_med + risky
        for c in pool:
            if len(set_matches) >= SET_SIZE:
                break
            sp = c["sport"]
            if sport_count.get(sp, 0) < sport_quota.get(sp, 3):
                set_matches.append(c)
                sport_count[sp] = sport_count.get(sp, 0) + 1

        # Top up if needed
        if len(set_matches) < SET_SIZE:
            leftovers = [c for c in pool if c not in set_matches]
            set_matches.extend(leftovers[:SET_SIZE - len(set_matches)])

        if len(set_matches) < SET_SIZE:
            break

        for m in set_matches:
            used_ids.add(m["match_id"])

        avg_conf  = sum(m["confidence"] for m in set_matches) / len(set_matches)
        # Combined prob = product of individual probs (parlay-style)
        combined  = math.prod(m["top_prob"] for m in set_matches)
        avg_odds  = sum(m["rec_odds"] for m in set_matches) / len(set_matches)
        risk_lvl  = "HIGH" if avg_conf >= 75 else ("MEDIUM" if avg_conf >= 60 else "LOW")

        ss = SmartSet(
            set_number         = set_num,
            generated_date     = datetime.utcnow(),
            matches_json       = json.dumps(set_matches),
            match_count        = len(set_matches),
            overall_confidence = round(avg_conf, 1),
            combined_probability = round(combined, 6),
            avg_odds           = round(avg_odds, 2),
            risk_level         = risk_lvl,
            status             = "pending",
        )
        db.add(ss)
        sets_created.append(ss)

    db.commit()
    logger.info(f"Generated {len(sets_created)} smart sets")
    return sets_created


# ── Performance resolution ────────────────────────────────────────────

def resolve_finished_matches(db: Session) -> int:
    """
    1. Fetch real results from The Odds API / API-Football and update Match records.
    2. Find matches that are now finished, have a prediction+decision, but no PerformanceLog.
    3. Create PerformanceLog rows (win/loss, P&L) and trigger self-optimization.
    Returns number of newly resolved matches.
    """
    from sqlalchemy.orm import joinedload

    # ── Step 1: pull real results from external APIs ──────────────────
    try:
        from data.sources.results_fetcher import fetch_and_update_results
        n_updated = fetch_and_update_results(db)
        if n_updated:
            logger.info(f"Result fetcher: {n_updated} matches updated to finished")
    except Exception as e:
        logger.warning(f"Result fetcher error (non-fatal): {e}")

    resolved = 0

    # Finished matches with a prediction and decision but no perf log
    finished = (
        db.query(Match)
        .join(Prediction, Match.id == Prediction.match_id)
        .join(MatchDecision, Match.id == MatchDecision.match_id)
        .options(
            joinedload(Match.competition).joinedload(Competition.sport),
            joinedload(Match.predictions),
        )
        .filter(Match.result.isnot(None))
        .outerjoin(PerformanceLog, Match.id == PerformanceLog.match_id)
        .filter(PerformanceLog.id.is_(None))
        .limit(500)
        .all()
    )

    for m in finished:
        md   = db.query(MatchDecision).filter_by(match_id=m.id).first()
        pred = m.predictions[0] if m.predictions else None
        if not md or not pred:
            continue

        sport_key   = m.competition.sport.key if m.competition and m.competition.sport else "unknown"
        competition = m.competition.name if m.competition else ""
        actual      = m.result  # H/D/A

        # Check if our predicted outcome matches actual
        is_correct = (md.predicted_outcome == actual)
        odds_used  = md.recommended_odds or 1.5
        stake      = md.recommended_stake_pct or 0.01

        if md.ai_decision == "PLAY":
            pnl = stake * (odds_used - 1) if is_correct else -stake
        else:
            pnl = 0.0  # SKIP — no stake

        pl = PerformanceLog(
            match_id          = m.id,
            sport_key         = sport_key,
            competition       = competition,
            ai_decision       = md.ai_decision,
            confidence_score  = md.confidence_score,
            predicted_outcome = md.predicted_outcome or "",
            predicted_prob    = md.top_prob,
            odds_used         = odds_used,
            stake_pct         = stake,
            actual_result     = actual,
            is_correct        = is_correct,
            profit_loss_units = pnl,
        )
        db.add(pl)
        resolved += 1

    db.commit()
    if resolved:
        logger.info(f"Resolved {resolved} finished matches")
        _update_optimization_weights(db)
    return resolved


# ── Self-optimization ─────────────────────────────────────────────────

def _update_optimization_weights(db: Session):
    """
    Recalculate per-competition and per-sport confidence boosts
    from recent PerformanceLog records (last 60 days, PLAY only).
    Weight formula: (success_rate - 0.5) * 20  → range −10…+10
    """
    cutoff = datetime.utcnow() - timedelta(days=60)
    logs   = (
        db.query(PerformanceLog)
        .filter(PerformanceLog.ai_decision == "PLAY",
                PerformanceLog.log_date >= cutoff,
                PerformanceLog.is_correct.isnot(None))
        .all()
    )

    # Group by scope
    from collections import defaultdict
    sport_stats = defaultdict(lambda: {"wins": 0, "total": 0})
    comp_stats  = defaultdict(lambda: {"wins": 0, "total": 0})
    global_s    = {"wins": 0, "total": 0}

    for lg in logs:
        sk = lg.sport_key
        ck = f"{sk}_{lg.competition}"
        sport_stats[sk]["wins"]  += int(lg.is_correct)
        sport_stats[sk]["total"] += 1
        comp_stats[ck]["wins"]   += int(lg.is_correct)
        comp_stats[ck]["total"]  += 1
        global_s["wins"]  += int(lg.is_correct)
        global_s["total"] += 1

    def _upsert_weight(scope_key, scope_type, wins, total):
        if total < 5:
            return
        rate = wins / total
        wt   = (rate - 0.5) * 20
        row  = db.query(OptimizationWeight).filter_by(scope_key=scope_key).first()
        if not row:
            row = OptimizationWeight(scope_key=scope_key, scope_type=scope_type)
            db.add(row)
        row.weight       = round(max(-10, min(10, wt)), 2)
        row.success_rate = round(rate, 4)
        row.sample_size  = total
        row.updated_at   = datetime.utcnow()

    for sk, s in sport_stats.items():
        _upsert_weight(sk, "sport", s["wins"], s["total"])
    for ck, s in comp_stats.items():
        _upsert_weight(ck, "competition", s["wins"], s["total"])
    if global_s["total"] >= 5:
        _upsert_weight("global", "global", global_s["wins"], global_s["total"])

    db.commit()
    logger.info("Optimization weights updated")
