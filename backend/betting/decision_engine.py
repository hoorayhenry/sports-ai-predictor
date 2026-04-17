"""
AI Decision Engine — value-driven betting intelligence.

A pick is only valid when ALL of these are true:
  1. Model probability ≥ threshold (signal quality)
  2. Confidence score ≥ threshold (composite signal)
  3. Not volatile (outcome clarity)
  4. Expected value ≥ threshold (positive return)
  5. Edge ≥ threshold (model beats the market)
  6. Low-odds penalty passes (short prices need bigger edge)

This separates a prediction engine from a decision intelligence system.
High probability alone is NOT a reason to bet.
Mispriced opportunity IS a reason to bet.

Confidence score rewards edge — a 70% model prob with 15% edge scores
higher than a 78% model prob with 2% edge.

Kelly stake is tiered: full Kelly only for high-confidence + strong-edge picks.
Weak signals get quarter Kelly to protect the bankroll.

Smart Sets only include edge-confirmed PLAY decisions, capped at
MAX_SAME_LEAGUE_PER_SET picks from the same league to limit correlation risk.

CLV (Closing Line Value) is tracked per pick: did we beat the market's
final assessment? Consistent positive CLV proves the edge is real.
"""
from __future__ import annotations
import json
import math
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger
from sqlalchemy.orm import Session

from data.db_models.models import (
    Match, Prediction, MatchDecision, SmartSet,
    PerformanceLog, OptimizationWeight, Competition, Sport,
)

# ─── Thresholds ───────────────────────────────────────────────────────────────
PLAY_PROB_THRESHOLD       = 0.65   # minimum model probability to consider
PLAY_CONFIDENCE_THRESHOLD = 70.0   # minimum composite confidence score
VOLATILITY_MARGIN         = 0.15   # gap between top two outcomes — below = volatile
HIGH_PROB_THRESHOLD       = 0.75
MEDIUM_PROB_THRESHOLD     = 0.60

# Value gate — the core upgrade
MIN_EV_THRESHOLD          = 0.03   # 3% minimum expected value
MIN_EDGE_THRESHOLD        = 0.05   # 5% minimum model-vs-market edge
LOW_ODDS_CUTOFF           = 1.30   # below this price, extra edge is required
LOW_ODDS_EDGE_REQUIRED    = 0.08   # 8% edge needed when odds < 1.30

# Smart Sets
NUM_SETS                  = 10
SET_SIZE                  = 10
MIN_SET_CONF              = 60.0
MAX_SAME_LEAGUE_PER_SET   = 3      # correlation cap — no more than 3 picks from same league
# ─────────────────────────────────────────────────────────────────────────────


# ── Helper: self-optimization weight ─────────────────────────────────────────

def _get_opt_weight(db: Session, sport_key: str, competition: str) -> float:
    """Blended self-optimization weight for sport+competition (−10…+10)."""
    comp_key = f"{sport_key}_{competition}"
    weight = 0.0
    for scope in [comp_key, sport_key, "global"]:
        row = db.query(OptimizationWeight).filter_by(scope_key=scope).first()
        if row and row.sample_size >= 10:
            weight += row.weight * 0.5
    return max(-10.0, min(10.0, weight))


# ── Edge computation ──────────────────────────────────────────────────────────

def compute_market_edge(
    top_prob: float,
    rec_odds: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """
    Returns (market_implied_prob, edge).
    market_implied_prob = 1 / odds (what the bookmaker thinks)
    edge = model_prob - market_implied_prob  (positive = we see more value)
    """
    if not rec_odds or rec_odds <= 1.0:
        return None, None
    market_prob = 1.0 / rec_odds
    edge = top_prob - market_prob
    return round(market_prob, 4), round(edge, 4)


def classify_value(edge: Optional[float], ev: Optional[float]) -> str:
    """
    Classify the value quality of a pick.
    strong_value: EV ≥ 10% and edge ≥ 10%
    fair_value:   EV ≥ 3% and edge ≥ 5%
    no_value:     does not meet thresholds
    no_odds:      no market data available
    """
    if edge is None or ev is None:
        return "no_odds"
    if ev >= 0.10 and edge >= 0.10:
        return "strong_value"
    if ev >= MIN_EV_THRESHOLD and edge >= MIN_EDGE_THRESHOLD:
        return "fair_value"
    return "no_value"


# ── Confidence score ──────────────────────────────────────────────────────────

def compute_confidence_score(
    top_prob: float,
    ev: Optional[float],
    elo_diff_abs: float,
    edge: Optional[float] = None,
    opt_boost: float = 0.0,
) -> tuple[float, float, float, float, float]:
    """
    Returns (total, prob_comp, ev_comp, form_comp, consistency_comp).

    Components:
      • Probability   (0–40): scaled top-outcome probability
      • EV            (0–20): expected value signal, neutral 10 when no data
      • Form          (0–20): ELO gap + prob synergy proxy
      • Consistency   (0–20): ELO gap stability (bigger gap = more predictable)
      • Edge boost    (0–10): bonus when model significantly beats the market
      • opt_boost     (±10): historical self-optimization weight

    Edge boost ensures high-edge picks rank above high-prob/low-edge picks.
    """
    prob_comp = top_prob * 100 * 0.40

    if ev is None:
        ev_comp = 10.0
    else:
        ev_comp = min(20.0, max(0.0, 10.0 + ev * 60.0))

    elo_form = min(1.0, elo_diff_abs / 400.0)
    form_comp = (top_prob * 0.7 + elo_form * 0.3) * 20.0

    consistency_comp = min(20.0, (elo_diff_abs / 400.0) * 20.0)

    # Edge boost: up to +10 when model strongly beats market implied probability
    edge_boost = min(10.0, edge * 100) if edge is not None and edge > 0 else 0.0

    raw = prob_comp + ev_comp + form_comp + consistency_comp + edge_boost + opt_boost
    total = round(min(100.0, max(0.0, raw)), 1)
    return total, prob_comp, ev_comp, form_comp, consistency_comp


def classify_probability(prob: float) -> str:
    if prob >= HIGH_PROB_THRESHOLD:
        return "HIGH"
    if prob >= MEDIUM_PROB_THRESHOLD:
        return "MEDIUM"
    return "RISKY"


# ── Volatility detection ──────────────────────────────────────────────────────

def detect_volatility(
    home_prob: float,
    draw_prob: Optional[float],
    away_prob: float,
) -> tuple[bool, str]:
    """Returns (is_volatile, reason). Only meaningful for 1X2 markets."""
    probs = sorted(
        [p for p in [home_prob, draw_prob or 0.0, away_prob] if p > 0],
        reverse=True,
    )
    if len(probs) < 2:
        return False, ""
    margin = probs[0] - probs[1]
    if margin < VOLATILITY_MARGIN:
        return True, f"Outcomes too close ({margin:.0%} margin)"
    if 0.40 <= probs[0] < PLAY_PROB_THRESHOLD:
        return True, f"Grey-zone probability ({probs[0]:.0%})"
    return False, ""


# ── Decision gate ─────────────────────────────────────────────────────────────

def make_ai_decision(
    top_prob: float,
    confidence_score: float,
    has_volatility: bool,
    ev: Optional[float],
    rec_odds: Optional[float],
    edge: Optional[float],
) -> tuple[str, str]:
    """
    Returns (decision, skip_reason).

    Gate order (fail-fast — stops at first failure):
      1. Probability floor
      2. Confidence floor
      3. Volatility
      4. EV floor
      5. Edge floor
      6. Low-odds penalty

    When rec_odds is None (market data not yet available), falls back to
    probability+confidence only and marks skip_reason as "no_market_data"
    on PLAY picks — flagging them as unconfirmed by market.
    """
    # ── No market data — probability-only fallback ────────────────────
    if rec_odds is None or rec_odds <= 1.0:
        if (top_prob >= PLAY_PROB_THRESHOLD
                and confidence_score >= PLAY_CONFIDENCE_THRESHOLD
                and not has_volatility):
            return "PLAY", "no_market_data"
        return "SKIP", _build_skip_reason(
            top_prob, confidence_score, has_volatility, ev=None, edge=None
        )

    # ── Full value gate ───────────────────────────────────────────────
    if top_prob < PLAY_PROB_THRESHOLD:
        return "SKIP", f"Low probability ({top_prob:.0%} < {PLAY_PROB_THRESHOLD:.0%})"

    if confidence_score < PLAY_CONFIDENCE_THRESHOLD:
        return "SKIP", f"Low confidence ({confidence_score:.0f} < {PLAY_CONFIDENCE_THRESHOLD:.0f})"

    if has_volatility:
        return "SKIP", "Volatile — outcomes too close to call"

    if ev is None or ev < MIN_EV_THRESHOLD:
        ev_pct = f"{ev*100:.1f}%" if ev is not None else "N/A"
        return "SKIP", f"No market edge (EV {ev_pct}, need ≥{MIN_EV_THRESHOLD*100:.0f}%)"

    if edge is None or edge < MIN_EDGE_THRESHOLD:
        edge_pct = f"{edge*100:.1f}%" if edge is not None else "N/A"
        return "SKIP", f"Insufficient edge ({edge_pct}, need ≥{MIN_EDGE_THRESHOLD*100:.0f}%)"

    if rec_odds < LOW_ODDS_CUTOFF and edge < LOW_ODDS_EDGE_REQUIRED:
        return "SKIP", (
            f"Short price ({rec_odds:.2f}) needs ≥{LOW_ODDS_EDGE_REQUIRED*100:.0f}% edge "
            f"(have {edge*100:.1f}%)"
        )

    return "PLAY", ""


def _build_skip_reason(
    top_prob: float,
    confidence_score: float,
    has_volatility: bool,
    ev: Optional[float],
    edge: Optional[float],
) -> str:
    """Human-readable explanation of why a match was skipped."""
    reasons = []
    if top_prob < PLAY_PROB_THRESHOLD:
        reasons.append(f"probability {top_prob:.0%}")
    if confidence_score < PLAY_CONFIDENCE_THRESHOLD:
        reasons.append(f"confidence {confidence_score:.0f}")
    if has_volatility:
        reasons.append("volatile")
    if ev is not None and ev < MIN_EV_THRESHOLD:
        reasons.append(f"EV {ev*100:.1f}%")
    if edge is not None and edge < MIN_EDGE_THRESHOLD:
        reasons.append(f"edge {edge*100:.1f}%")
    if not reasons:
        reasons.append("insufficient value")
    return "Low " + ", ".join(reasons)


# ── Tiered Kelly ──────────────────────────────────────────────────────────────

def _tiered_kelly(
    kelly_stake: Optional[float],
    confidence_score: float,
    edge: Optional[float],
) -> float:
    """
    Scale Kelly stake by confidence + edge tier.

    Tier 1 (full Kelly):     confidence ≥ 80 AND edge ≥ 12%  → strong signal
    Tier 2 (75% Kelly):      confidence ≥ 75 AND edge ≥ 8%
    Tier 3 (50% Kelly):      confidence ≥ 70 AND edge ≥ 5%
    Tier 4 (25% Kelly):      everything else                  → weak signal

    This protects the bankroll on marginal picks while maximising
    stake sizing on the highest-conviction opportunities.
    """
    if not kelly_stake or kelly_stake <= 0:
        return 0.0
    if confidence_score >= 80 and edge is not None and edge >= 0.12:
        return kelly_stake           # full Kelly
    if confidence_score >= 75 and edge is not None and edge >= 0.08:
        return kelly_stake * 0.75
    if confidence_score >= 70 and edge is not None and edge >= 0.05:
        return kelly_stake * 0.50
    return kelly_stake * 0.25        # quarter Kelly — defensive


# ── Core entry point: process all upcoming matches ────────────────────────────

def process_decisions(db: Session) -> int:
    """
    Re-compute AI decisions for all upcoming scheduled matches with a Prediction.
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
    skip_count = 0

    for m in matches:
        pred: Optional[Prediction] = m.predictions[0] if m.predictions else None
        if not pred:
            continue

        sport_key   = m.competition.sport.key if m.competition and m.competition.sport else "unknown"
        competition = m.competition.name if m.competition else ""

        # ── Candidate outcomes ────────────────────────────────────────
        candidates: dict[str, float] = {
            "H": pred.home_win_prob or 0.0,
            "D": pred.draw_prob     or 0.0,
            "A": pred.away_win_prob or 0.0,
        }

        over25_prob = pred.over25_prob or 0.0
        btts_prob   = pred.btts_prob   or 0.0

        has_totals_odds = any(o.market == "totals" for o in m.odds)
        has_btts_odds   = any(o.market == "btts"   for o in m.odds)

        if over25_prob > 0 and has_totals_odds:
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

        # ── Best odds for top outcome ─────────────────────────────────
        outcome_to_market = {
            "H":        ("h2h",    "home"),
            "D":        ("h2h",    "draw"),
            "A":        ("h2h",    "away"),
            "over":     ("totals", "over"),
            "under":    ("totals", "under"),
            "btts_yes": ("btts",   "yes"),
            "btts_no":  ("btts",   "no"),
        }
        rec_odds = None
        if top_outcome in outcome_to_market:
            mkt, db_out = outcome_to_market[top_outcome]
            prices = [o.price for o in m.odds if o.market == mkt and o.outcome == db_out]
            if prices:
                rec_odds = max(prices)

        # ── EV for the specific top outcome (not global best EV) ──────
        ev: Optional[float] = None
        if rec_odds and rec_odds > 1.0:
            ev = round((top_prob * rec_odds) - 1.0, 4)
        elif pred.expected_value is not None:
            ev = pred.expected_value  # fallback to stored best EV

        # ── Market edge ───────────────────────────────────────────────
        market_prob, edge = compute_market_edge(top_prob, rec_odds)

        # ── ELO diff ──────────────────────────────────────────────────
        home_elo     = m.home.elo_rating if m.home else 1500.0
        away_elo     = m.away.elo_rating if m.away else 1500.0
        elo_diff_abs = abs(home_elo - away_elo)

        # ── Optimization + intelligence boosts ───────────────────────
        opt_boost = _get_opt_weight(db, sport_key, competition)
        try:
            from intelligence.signals import get_intelligence_boost
            intel_boost = get_intelligence_boost(db, m.id)
        except Exception:
            intel_boost = 0.0

        # ── Confidence score (edge-boosted) ───────────────────────────
        conf, p_comp, ev_comp, f_comp, c_comp = compute_confidence_score(
            top_prob, ev, elo_diff_abs, edge, opt_boost + intel_boost
        )

        # ── Volatility (only for 1X2 result market) ───────────────────
        if top_outcome in ("H", "D", "A"):
            volatile, vol_reason = detect_volatility(
                pred.home_win_prob or 0.0,
                pred.draw_prob,
                pred.away_win_prob or 0.0,
            )
        else:
            volatile, vol_reason = False, ""

        # ── Value gate decision ───────────────────────────────────────
        decision, skip_reason = make_ai_decision(
            top_prob, conf, volatile, ev, rec_odds, edge
        )

        prob_tag    = classify_probability(top_prob)
        value_label = classify_value(edge, ev)

        # ── Tiered Kelly ──────────────────────────────────────────────
        tiered_stake = _tiered_kelly(pred.kelly_stake, conf, edge)

        # ── Persist MatchDecision ─────────────────────────────────────
        md = db.query(MatchDecision).filter_by(match_id=m.id).first()
        if not md:
            md = MatchDecision(match_id=m.id)
            db.add(md)

        md.confidence_score      = conf
        md.prob_tag              = prob_tag
        md.ai_decision           = decision
        md.top_prob              = top_prob
        md.predicted_outcome     = top_outcome
        md.has_volatility        = volatile
        md.volatility_reason     = vol_reason
        md.prob_component        = p_comp
        md.ev_component          = ev_comp
        md.form_component        = f_comp
        md.consistency_component = c_comp
        md.recommended_odds      = rec_odds
        md.recommended_stake_pct = tiered_stake
        md.skip_reason           = skip_reason if decision == "SKIP" else None
        md.market_prob           = market_prob
        md.edge                  = edge
        md.value_label           = value_label
        md.odds_at_decision      = rec_odds   # CLV baseline snapshot
        md.updated_at            = datetime.utcnow()

        if decision == "PLAY":
            play_count += 1
        else:
            skip_count += 1

    db.commit()
    total = play_count + skip_count
    logger.info(
        f"Decisions: {play_count} PLAY, {skip_count} SKIP out of {total} analysed "
        f"({play_count/total*100:.1f}% selection rate)" if total else
        "Decisions: 0 matches processed"
    )
    return play_count


# ── Smart Sets ────────────────────────────────────────────────────────────────

def generate_smart_sets(db: Session) -> list[SmartSet]:
    """
    Generate up to 10 Smart Sets for the next 7 days.

    Rules:
      - Only PLAY decisions with confirmed positive edge (or no_market_data fallback)
      - Max MAX_SAME_LEAGUE_PER_SET picks from the same competition per set
      - Sport-balanced (best effort quota)
      - Sets sorted by confidence desc within each tier
    """
    from sqlalchemy.orm import joinedload

    cutoff = datetime.utcnow() + timedelta(days=7)

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
            MatchDecision.ai_decision == "PLAY",
        )
        .all()
    )

    if len(matches) < SET_SIZE:
        logger.warning(f"Only {len(matches)} PLAY matches available for smart sets")
        return []

    candidates = []
    for m in matches:
        md   = db.query(MatchDecision).filter_by(match_id=m.id).first()
        pred = m.predictions[0] if m.predictions else None
        if not md or not pred:
            continue
        sport_key   = m.competition.sport.key if m.competition and m.competition.sport else "unknown"
        competition = m.competition.name if m.competition else ""
        candidates.append({
            "match_id":          m.id,
            "home_team":         m.home.name if m.home else "TBD",
            "away_team":         m.away.name if m.away else "TBD",
            "sport":             sport_key,
            "sport_icon":        m.competition.sport.icon if m.competition and m.competition.sport else "🏆",
            "competition":       competition,
            "match_date":        m.match_date.isoformat(),
            "ai_decision":       md.ai_decision,
            "confidence":        md.confidence_score,
            "prob_tag":          md.prob_tag,
            "predicted_outcome": md.predicted_outcome,
            "top_prob":          md.top_prob,
            "rec_odds":          md.recommended_odds or 1.5,
            "edge":              md.edge,
            "value_label":       md.value_label,
            "home_win_prob":     pred.home_win_prob,
            "draw_prob":         pred.draw_prob,
            "away_win_prob":     pred.away_win_prob,
        })

    # Sort: strong_value first → fair_value → confidence desc
    value_rank = {"strong_value": 0, "fair_value": 1, "no_odds": 2, "no_value": 3}
    candidates.sort(key=lambda x: (
        value_rank.get(x.get("value_label", "no_value"), 3),
        -x["confidence"],
    ))

    # Delete today's stale sets
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

        set_matches: list[dict] = []
        league_count: dict[str, int] = {}
        sport_quota  = {s: max(1, SET_SIZE // len(sports_available)) for s in sports_available}
        sport_count  = {s: 0 for s in sports_available}

        for c in available:
            if len(set_matches) >= SET_SIZE:
                break
            sp  = c["sport"]
            leg = c["competition"]

            # Correlation cap: max 3 from same league
            if league_count.get(leg, 0) >= MAX_SAME_LEAGUE_PER_SET:
                continue
            # Sport balance (best effort)
            if sport_count.get(sp, 0) >= sport_quota.get(sp, 3):
                continue

            set_matches.append(c)
            league_count[leg]  = league_count.get(leg, 0) + 1
            sport_count[sp]    = sport_count.get(sp, 0) + 1

        # Top up if sport quota prevented filling the set
        if len(set_matches) < SET_SIZE:
            leftovers = [
                c for c in available
                if c not in set_matches
                and league_count.get(c["competition"], 0) < MAX_SAME_LEAGUE_PER_SET
            ]
            set_matches.extend(leftovers[:SET_SIZE - len(set_matches)])

        if len(set_matches) < SET_SIZE:
            break

        for c in set_matches:
            used_ids.add(c["match_id"])

        avg_conf = sum(c["confidence"] for c in set_matches) / len(set_matches)
        combined = math.prod(c["top_prob"] for c in set_matches)
        avg_odds = sum(c["rec_odds"] for c in set_matches) / len(set_matches)
        risk_lvl = "HIGH" if avg_conf >= 75 else ("MEDIUM" if avg_conf >= 60 else "LOW")

        ss = SmartSet(
            set_number           = set_num,
            generated_date       = datetime.utcnow(),
            matches_json         = json.dumps(set_matches),
            match_count          = len(set_matches),
            overall_confidence   = round(avg_conf, 1),
            combined_probability = round(combined, 6),
            avg_odds             = round(avg_odds, 2),
            risk_level           = risk_lvl,
            status               = "pending",
        )
        db.add(ss)
        sets_created.append(ss)

    db.commit()
    logger.info(f"Generated {len(sets_created)} smart sets from {len(candidates)} PLAY candidates")
    return sets_created


# ── Performance resolution + CLV ─────────────────────────────────────────────

def resolve_finished_matches(db: Session) -> int:
    """
    1. Fetch real results from external APIs and update Match records.
    2. Create PerformanceLog rows for newly finished matches.
    3. Compute CLV — compare odds_at_decision vs latest pre-kickoff odds.
    4. Trigger self-optimization weight updates.
    Returns number of newly resolved matches.
    """
    from sqlalchemy.orm import joinedload

    try:
        from data.sources.results_fetcher import fetch_and_update_results
        n_updated = fetch_and_update_results(db)
        if n_updated:
            logger.info(f"Result fetcher: {n_updated} matches updated")
    except Exception as e:
        logger.warning(f"Result fetcher error (non-fatal): {e}")

    resolved = 0

    finished = (
        db.query(Match)
        .join(Prediction, Match.id == Prediction.match_id)
        .join(MatchDecision, Match.id == MatchDecision.match_id)
        .options(
            joinedload(Match.competition).joinedload(Competition.sport),
            joinedload(Match.predictions),
            joinedload(Match.odds),
        )
        .filter(Match.result.isnot(None))
        .outerjoin(PerformanceLog, Match.id == PerformanceLog.match_id)
        .filter(PerformanceLog.id.is_(None))
        .limit(500)
        .all()
    )

    outcome_to_market = {
        "H":        ("h2h",    "home"),
        "D":        ("h2h",    "draw"),
        "A":        ("h2h",    "away"),
        "over":     ("totals", "over"),
        "under":    ("totals", "under"),
        "btts_yes": ("btts",   "yes"),
        "btts_no":  ("btts",   "no"),
    }

    for m in finished:
        md   = db.query(MatchDecision).filter_by(match_id=m.id).first()
        pred = m.predictions[0] if m.predictions else None
        if not md or not pred:
            continue

        sport_key   = m.competition.sport.key if m.competition and m.competition.sport else "unknown"
        competition = m.competition.name if m.competition else ""
        actual      = m.result

        is_correct = (md.predicted_outcome == actual)
        odds_used  = md.recommended_odds or 1.5
        stake      = md.recommended_stake_pct or 0.01

        pnl = 0.0
        if md.ai_decision == "PLAY":
            pnl = stake * (odds_used - 1) if is_correct else -stake

        # ── CLV: compare decision odds vs latest odds before kickoff ──
        from data.db_models.models import MatchOdds as _MatchOdds
        clv: Optional[float] = None
        closing_odds: Optional[float] = None
        if md.odds_at_decision and md.predicted_outcome in outcome_to_market:
            mkt, db_out = outcome_to_market[md.predicted_outcome]
            latest = (
                db.query(_MatchOdds)
                .filter_by(match_id=m.id, market=mkt, outcome=db_out)
                .filter(_MatchOdds.recorded_at <= m.match_date)
                .order_by(_MatchOdds.recorded_at.desc())
                .first()
            )
            if latest and latest.price > 1.0:
                closing_odds    = latest.price
                clv             = round((md.odds_at_decision / closing_odds) - 1.0, 4)
                md.closing_odds = closing_odds
                md.clv          = clv

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
            edge              = md.edge,
            market_prob       = md.market_prob,
            clv               = clv,
        )
        db.add(pl)
        resolved += 1

    db.commit()
    if resolved:
        logger.info(f"Resolved {resolved} finished matches")
        _update_optimization_weights(db)
    return resolved


# ── Self-optimization ─────────────────────────────────────────────────────────

def _update_optimization_weights(db: Session):
    """
    Recalculate per-competition and per-sport confidence boosts
    from recent PerformanceLog records (last 60 days, PLAY only).
    Weight formula: (success_rate - 0.5) * 20  → range −10…+10
    """
    from collections import defaultdict

    cutoff = datetime.utcnow() - timedelta(days=60)
    logs   = (
        db.query(PerformanceLog)
        .filter(
            PerformanceLog.ai_decision == "PLAY",
            PerformanceLog.log_date >= cutoff,
            PerformanceLog.is_correct.isnot(None),
        )
        .all()
    )

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

    def _upsert(scope_key, scope_type, wins, total):
        if total < 5:
            return
        rate = wins / total
        wt   = (rate - 0.5) * 20
        row  = db.query(OptimizationWeight).filter_by(scope_key=scope_key).first()
        if not row:
            row = OptimizationWeight(scope_key=scope_key, scope_type=scope_type)
            db.add(row)
        row.weight       = round(max(-10.0, min(10.0, wt)), 2)
        row.success_rate = round(rate, 4)
        row.sample_size  = total
        row.updated_at   = datetime.utcnow()

    for sk, s in sport_stats.items():
        _upsert(sk, "sport", s["wins"], s["total"])
    for ck, s in comp_stats.items():
        _upsert(ck, "competition", s["wins"], s["total"])
    if global_s["total"] >= 5:
        _upsert("global", "global", global_s["wins"], global_s["total"])

    db.commit()
    logger.info("Optimization weights updated")
