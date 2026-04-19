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
    is_binary_sport: bool = False,
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

    Binary sports (basketball, baseball, hockey, NFL, tennis) use adjusted
    thresholds because there is no draw dilution — a 60% prob in a binary market
    carries more information than 60% in a 3-way market.

    When rec_odds is None (market data not yet available), falls back to
    probability+confidence only and marks skip_reason as "no_market_data"
    on PLAY picks — flagging them as unconfirmed by market.
    """
    # Binary sports use lower thresholds (no-draw → cleaner signal)
    prob_threshold = 0.58 if is_binary_sport else PLAY_PROB_THRESHOLD
    conf_threshold = 65.0 if is_binary_sport else PLAY_CONFIDENCE_THRESHOLD

    # ── No market data — probability-only fallback ────────────────────
    if rec_odds is None or rec_odds <= 1.0:
        if (top_prob >= prob_threshold
                and confidence_score >= conf_threshold
                and not has_volatility):
            return "PLAY", "no_market_data"
        return "SKIP", _build_skip_reason(
            top_prob, confidence_score, has_volatility, ev=None, edge=None
        )

    # ── Full value gate ───────────────────────────────────────────────
    if top_prob < prob_threshold:
        return "SKIP", f"Low probability ({top_prob:.0%} < {prob_threshold:.0%})"

    if confidence_score < conf_threshold:
        return "SKIP", f"Low confidence ({confidence_score:.0f} < {conf_threshold:.0f})"

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
        # Binary sports: basketball, baseball, ice_hockey, american_football, tennis, rugby
        is_binary_sport = sport_key not in ("football", "handball")

        # ── Parse all Poisson market probabilities ────────────────────
        mkts: dict = {}
        try:
            if pred.markets_json:
                mkts = json.loads(pred.markets_json)
        except Exception:
            pass

        h_prob = pred.home_win_prob or 0.0
        d_prob = pred.draw_prob     or 0.0
        a_prob = pred.away_win_prob or 0.0

        # ── Outcome → (market, outcome_key, point) odds lookup ────────
        # point=None → match any row (no point filter needed)
        # Stored in MatchOdds: market, outcome, point
        ODDS_LOOKUP: dict[str, tuple[str, str, Optional[float]]] = {
            # 1X2
            "H":            ("h2h",             "home",       None),
            "D":            ("h2h",             "draw",       None),
            "A":            ("h2h",             "away",       None),
            # Totals at each line
            "over_1.5":     ("totals",          "over",       1.5),
            "over_2.5":     ("totals",          "over",       2.5),
            "over_3.5":     ("totals",          "over",       3.5),
            "over_4.5":     ("totals",          "over",       4.5),
            "under_1.5":    ("totals",          "under",      1.5),
            "under_2.5":    ("totals",          "under",      2.5),
            "under_3.5":    ("totals",          "under",      3.5),
            # BTTS
            "btts_yes":     ("btts",            "yes",        None),
            "btts_no":      ("btts",            "no",         None),
            # Draw No Bet
            "dnb_home":     ("draw_no_bet",     "home",       None),
            "dnb_away":     ("draw_no_bet",     "away",       None),
            # Double Chance (from API-Football odds)
            "dc_1x":        ("double_chance",   "home_draw",  None),
            "dc_x2":        ("double_chance",   "away_draw",  None),
            "dc_12":        ("double_chance",   "home_away",  None),
            # Win to Nil (from API-Football odds)
            "wtn_home":     ("win_to_nil",      "home",       None),
            "wtn_away":     ("win_to_nil",      "away",       None),
            # Spreads (non-football)
            "home_spread":  ("spreads",         "home",       None),
            "away_spread":  ("spreads",         "away",       None),
            # Asian Handicap (from API-Football odds — best available line)
            "ah_home":      ("asian_handicap",  "home",       None),
            "ah_away":      ("asian_handicap",  "away",       None),
        }

        def _best_price(outcome_key: str) -> Optional[float]:
            """Max price available across all bookmakers for this outcome."""
            if outcome_key not in ODDS_LOOKUP:
                return None
            mkt, out, pt = ODDS_LOOKUP[outcome_key]
            prices = [
                o.price for o in m.odds
                if o.market == mkt
                and o.outcome == out
                and (pt is None or o.point == pt)
                and o.price > 1.0
            ]
            return max(prices) if prices else None

        def _has_market(market: str) -> bool:
            return any(o.market == market for o in m.odds)

        # ── Build candidate pool ──────────────────────────────────────
        candidates: dict[str, float] = {}

        # 1. Match result (1X2) — always present
        candidates["H"] = h_prob
        candidates["D"] = d_prob
        candidates["A"] = a_prob

        # 2. Over/Under at multiple lines (add only when odds for that line exist)
        ou_defs = [
            ("over_1.5",  "over15",  pred.over25_prob, 1.5),   # over15 from mkts_json
            ("over_2.5",  "over25",  pred.over25_prob, 2.5),   # fallback to pred col
            ("over_3.5",  "over35",  None,             3.5),
            ("over_4.5",  "over45",  None,             4.5),
        ]
        for ok, mkey, fallback, pt_val in ou_defs:
            raw = mkts.get(mkey) or (fallback if mkey == "over25" else None)
            if not raw:
                continue
            # markets_json stores over/under as {"over": float, "under": float}
            over_p = raw.get("over") if isinstance(raw, dict) else raw
            if not over_p:
                continue
            if not any(o.market == "totals" and o.point == pt_val for o in m.odds):
                continue
            candidates[ok]                             = float(over_p)
            candidates[ok.replace("over", "under")]    = 1.0 - float(over_p)

        # 3. BTTS
        raw_btts = mkts.get("btts")
        btts_p = (raw_btts.get("yes") if isinstance(raw_btts, dict) else raw_btts) or pred.btts_prob or 0.0
        if btts_p > 0 and _has_market("btts"):
            candidates["btts_yes"] = float(btts_p)
            candidates["btts_no"]  = 1.0 - float(btts_p)

        # 4. Draw No Bet (football only — removes draw outcome)
        if _has_market("draw_no_bet"):
            ha_total = h_prob + a_prob
            if ha_total > 0:
                candidates["dnb_home"] = h_prob / ha_total
                candidates["dnb_away"] = a_prob / ha_total

        # 5. Double Chance (H+D, D+A, H+A) — computed from 1X2 probs
        if _has_market("double_chance"):
            dc1x = mkts.get("double_chance_1x") or (h_prob + d_prob)
            dcx2 = mkts.get("double_chance_x2") or (d_prob + a_prob)
            dc12 = mkts.get("double_chance_12") or (h_prob + a_prob)
            candidates["dc_1x"] = min(float(dc1x), 0.999)
            candidates["dc_x2"] = min(float(dcx2), 0.999)
            candidates["dc_12"] = min(float(dc12), 0.999)

        # 6. Win to Nil — from markets_json Poisson output
        if _has_market("win_to_nil"):
            wtn_h = mkts.get("home_win_to_nil")
            wtn_a = mkts.get("away_win_to_nil")
            if wtn_h:
                candidates["wtn_home"] = float(wtn_h)
            if wtn_a:
                candidates["wtn_away"] = float(wtn_a)

        # 7. Asian Handicap — use Poisson AH probs when available
        if _has_market("asian_handicap"):
            ah_h = mkts.get("ah_home") or mkts.get("ah_home_-0.5")
            ah_a = mkts.get("ah_away") or mkts.get("ah_away_-0.5")
            if ah_h:
                candidates["ah_home"] = float(ah_h)
            if ah_a:
                candidates["ah_away"] = float(ah_a)

        # 8. Spreads (non-football — basketball, NFL, etc.)
        if sport_key != "football" and _has_market("spreads"):
            candidates["home_spread"] = h_prob
            candidates["away_spread"] = a_prob

        # 9. Over/Under — sport-specific main line (basketball 215.5, baseball 9.5…)
        over_main_data = mkts.get("over_main")
        if over_main_data and isinstance(over_main_data, dict):
            try:
                main_line_val = float(over_main_data.get("line") or 0)
            except (TypeError, ValueError):
                main_line_val = 0.0
            if main_line_val > 0:
                # Register this dynamic line in the odds lookup for this match
                ODDS_LOOKUP["over_main_o"] = ("totals", "over",  main_line_val)
                ODDS_LOOKUP["over_main_u"] = ("totals", "under", main_line_val)
                candidates["over_main_o"] = float(over_main_data.get("over",  0.5))
                candidates["over_main_u"] = float(over_main_data.get("under", 0.5))

        # ── Select best candidate by Expected Value ───────────────────
        # For each candidate that meets the prob floor, compute EV = prob*odds-1.
        # Pick the highest EV. Candidates without odds rank by excess probability.
        best_outcome: Optional[str] = None
        best_ev_score: float        = -999.0

        _prob_floor = 0.58 if is_binary_sport else PLAY_PROB_THRESHOLD
        for outcome, prob in candidates.items():
            if prob < _prob_floor:
                continue
            odds = _best_price(outcome)
            if odds and odds > 1.0:
                ev_score = prob * odds - 1.0      # true expected value
            else:
                ev_score = prob - _prob_floor  # prob-only fallback

            if ev_score > best_ev_score:
                best_ev_score = ev_score
                best_outcome  = outcome

        # Fall back to max-prob if nothing exceeded the floor
        if best_outcome is None:
            best_outcome = max(candidates, key=candidates.get)

        top_outcome = best_outcome
        top_prob    = candidates[top_outcome]

        # ── Best odds for chosen outcome ──────────────────────────────
        rec_odds = _best_price(top_outcome)

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
            top_prob, conf, volatile, ev, rec_odds, edge,
            is_binary_sport=is_binary_sport,
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

def _window_label(window_start_utc: datetime, window_end_utc: datetime) -> str:
    """Build a human-readable label in WAT (UTC+1)."""
    from zoneinfo import ZoneInfo
    WAT = ZoneInfo("Africa/Lagos")
    s = window_start_utc.replace(tzinfo=None)
    e = window_end_utc.replace(tzinfo=None)
    # Shift naively: WAT = UTC+1
    s_wat = s + timedelta(hours=1)
    e_wat = e + timedelta(hours=1)
    DAYS  = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    s_day = DAYS[s_wat.weekday()]
    e_day = DAYS[e_wat.weekday()]
    # e.g. "Mon–Wed · Apr 21–23"
    if s_wat.month == e_wat.month:
        return f"{s_day}–{e_day} · {s_wat.strftime('%b')} {s_wat.day}–{e_wat.day}"
    return f"{s_day}–{e_day} · {s_wat.strftime('%b')} {s_wat.day}–{e_wat.strftime('%b')} {e_wat.day}"


def _build_candidates(db: Session, window_start_utc: datetime, window_end_utc: datetime,
                      sport_filter: Optional[str] = None) -> list[dict]:
    """Fetch and rank PLAY candidates within a match window."""
    from sqlalchemy.orm import joinedload

    q = (
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
            Match.match_date >= window_start_utc,
            Match.match_date <= window_end_utc,
            MatchDecision.ai_decision == "PLAY",
        )
    )
    if sport_filter:
        q = q.filter(Sport.key == sport_filter)
    matches = q.all()

    value_rank = {"strong_value": 0, "fair_value": 1, "no_odds": 2, "no_value": 3}
    candidates = []
    for m in matches:
        md   = db.query(MatchDecision).filter_by(match_id=m.id).first()
        pred = m.predictions[0] if m.predictions else None
        if not md or not pred:
            continue
        sk   = m.competition.sport.key if m.competition and m.competition.sport else "unknown"
        edge = md.edge or 0.0
        conf = md.confidence_score or 0.0
        candidates.append({
            "match_id":          m.id,
            "home_team":         m.home.name if m.home else "TBD",
            "away_team":         m.away.name if m.away else "TBD",
            "sport":             sk,
            "sport_icon":        m.competition.sport.icon if m.competition and m.competition.sport else "🏆",
            "competition":       m.competition.name if m.competition else "",
            "match_date":        m.match_date.isoformat(),
            "ai_decision":       md.ai_decision,
            "confidence":        conf,
            "prob_tag":          md.prob_tag,
            "predicted_outcome": md.predicted_outcome,
            "top_prob":          md.top_prob,
            "rec_odds":          md.recommended_odds or 1.5,
            "edge":              edge,
            "value_label":       md.value_label,
            "home_win_prob":     pred.home_win_prob,
            "draw_prob":         pred.draw_prob,
            "away_win_prob":     pred.away_win_prob,
            # composite rank score: strong_value + edge + confidence
            "_rank": (value_rank.get(md.value_label or "no_value", 3), -(edge * conf)),
        })

    candidates.sort(key=lambda x: x["_rank"])
    return candidates


def _pack_sets(candidates: list[dict], num_sets: int, set_size: int,
               sport_key: str, window_label: str,
               window_start_utc: datetime, window_end_utc: datetime,
               db: Session) -> list[SmartSet]:
    """Pack candidates into SmartSet rows, apply correlation cap."""
    # Remove existing sets for this window+sport so we regenerate cleanly
    db.query(SmartSet).filter(
        SmartSet.sport_key == sport_key,
        SmartSet.window_start == window_start_utc,
    ).delete(synchronize_session=False)
    db.flush()

    sets_created: list[SmartSet] = []
    used_ids: set[int] = set()
    now = datetime.utcnow()

    for set_num in range(1, num_sets + 1):
        available = [c for c in candidates if c["match_id"] not in used_ids]
        if len(available) < set_size:
            break

        set_matches: list[dict] = []
        league_count: dict[str, int] = {}

        for c in available:
            if len(set_matches) >= set_size:
                break
            if league_count.get(c["competition"], 0) >= MAX_SAME_LEAGUE_PER_SET:
                continue
            set_matches.append(c)
            league_count[c["competition"]] = league_count.get(c["competition"], 0) + 1

        # Top up if correlation cap left gaps
        if len(set_matches) < set_size:
            leftovers = [
                c for c in available
                if c not in set_matches
                and league_count.get(c["competition"], 0) < MAX_SAME_LEAGUE_PER_SET
            ]
            set_matches.extend(leftovers[:set_size - len(set_matches)])

        if len(set_matches) < set_size:
            break

        for c in set_matches:
            used_ids.add(c["match_id"])

        avg_conf = sum(c["confidence"] for c in set_matches) / len(set_matches)
        combined = math.prod(c["top_prob"] for c in set_matches if c["top_prob"])
        avg_odds = sum(c["rec_odds"] for c in set_matches) / len(set_matches)
        risk_lvl = "HIGH" if avg_conf >= 75 else ("MEDIUM" if avg_conf >= 60 else "LOW")

        # Strip internal rank key before storing JSON
        clean = [{k: v for k, v in c.items() if k != "_rank"} for c in set_matches]

        ss = SmartSet(
            set_number           = set_num,
            generated_date       = now,
            window_label         = window_label,
            window_start         = window_start_utc,
            window_end           = window_end_utc,
            sport_key            = sport_key,
            matches_json         = json.dumps(clean),
            match_count          = len(clean),
            overall_confidence   = round(avg_conf, 1),
            combined_probability = round(combined, 6),
            avg_odds             = round(avg_odds, 2),
            risk_level           = risk_lvl,
            status               = "pending",
        )
        db.add(ss)
        sets_created.append(ss)

    return sets_created


def generate_smart_sets(
    db: Session,
    window_start_utc: Optional[datetime] = None,
    window_end_utc: Optional[datetime] = None,
) -> list[SmartSet]:
    """
    Generate Smart Sets for all sports within the given UTC window.

    Football: 10 sets × 10 matches (10×10), ranked by edge × confidence.
    Other sports: flexible — up to 5 sets, set size = min(available ÷ 2, 8), min 3.

    If window_start/end are omitted the next 7 days are used (legacy / manual trigger).
    """
    now = datetime.utcnow()
    if window_start_utc is None:
        window_start_utc = now
    if window_end_utc is None:
        window_end_utc = now + timedelta(days=7)

    label = _window_label(window_start_utc, window_end_utc)
    all_created: list[SmartSet] = []

    # ── Football: 10×10 ────────────────────────────────────────────────────────
    football_candidates = _build_candidates(db, window_start_utc, window_end_utc, "football")
    if len(football_candidates) >= SET_SIZE:
        sets = _pack_sets(
            football_candidates, NUM_SETS, SET_SIZE,
            "football", label, window_start_utc, window_end_utc, db,
        )
        all_created.extend(sets)
        logger.info(f"Football sets: {len(sets)} sets from {len(football_candidates)} candidates")
    else:
        logger.warning(f"Football: only {len(football_candidates)} PLAY candidates — need {SET_SIZE} min")

    # ── Other sports: flexible ─────────────────────────────────────────────────
    OTHER_SPORTS = [
        "basketball", "tennis", "american_football", "ice_hockey",
        "baseball", "cricket", "rugby", "handball", "volleyball",
    ]
    for sk in OTHER_SPORTS:
        candidates = _build_candidates(db, window_start_utc, window_end_utc, sk)
        if not candidates:
            continue
        # Flexible sizing: split evenly, sets of 3–8 matches
        raw_size  = max(3, min(8, len(candidates) // 2)) if len(candidates) >= 6 else len(candidates)
        raw_sets  = min(5, max(1, len(candidates) // raw_size))
        if len(candidates) < 3:
            logger.info(f"{sk}: only {len(candidates)} candidates — skipping (need ≥3)")
            continue
        sets = _pack_sets(
            candidates, raw_sets, raw_size,
            sk, label, window_start_utc, window_end_utc, db,
        )
        all_created.extend(sets)
        if sets:
            logger.info(f"{sk}: {len(sets)} sets from {len(candidates)} candidates")

    db.commit()
    logger.info(f"Smart sets generated: {len(all_created)} total for window '{label}'")
    return all_created


# ── Outcome correctness evaluator ────────────────────────────────────────────

def _evaluate_outcome(
    predicted: str,
    result: str,
    home_score: Optional[int],
    away_score: Optional[int],
) -> tuple[Optional[bool], str]:
    """
    Determine whether a pick was correct given the actual match result/scores.

    Returns (is_correct, actual_label):
      is_correct = True    → win
      is_correct = False   → loss
      is_correct = None    → push (DNB on draw — stake returned, no P&L)
      actual_label         → human-readable description of what happened
    """
    # ── 1X2 result markets ────────────────────────────────────────────
    if predicted in ("H", "D", "A"):
        return (predicted == result), result

    # All remaining markets need score data
    if home_score is None or away_score is None:
        return None, result or "unknown"

    total       = home_score + away_score
    both_scored = home_score > 0 and away_score > 0

    # ── Totals — Over/Under ───────────────────────────────────────────
    if predicted.startswith("over_"):
        try:
            line    = float(predicted[5:])
            correct = total > line
            return correct, f"over_{line}" if correct else f"under_{line}"
        except ValueError:
            pass

    if predicted.startswith("under_"):
        try:
            line    = float(predicted[7:])
            correct = total < line
            return correct, f"under_{line}" if correct else f"over_{line}"
        except ValueError:
            pass

    # ── Sport-specific main totals line (basketball 215.5, baseball 9.5…) ────
    # predicted is "over_main_o" (over) or "over_main_u" (under);
    # the actual line was stored in MatchDecision.predicted_outcome
    if predicted in ("over_main_o", "over_main_u"):
        return None, predicted    # Can't resolve without knowing the line; defer

    # ── BTTS ──────────────────────────────────────────────────────────
    if predicted == "btts_yes":
        return both_scored, "btts_yes" if both_scored else "btts_no"
    if predicted == "btts_no":
        return not both_scored, "btts_no" if not both_scored else "btts_yes"

    # ── Draw No Bet ───────────────────────────────────────────────────
    # Draw = push (stake returned). Loss only on opposite team winning.
    if predicted == "dnb_home":
        if result == "D":
            return None, "D"    # push
        return result == "H", result
    if predicted == "dnb_away":
        if result == "D":
            return None, "D"    # push
        return result == "A", result

    # ── Double Chance ─────────────────────────────────────────────────
    if predicted == "dc_1x":   # Home or Draw
        return result in ("H", "D"), result
    if predicted == "dc_x2":   # Away or Draw
        return result in ("A", "D"), result
    if predicted == "dc_12":   # Home or Away (no draw)
        return result in ("H", "A"), result

    # ── Win to Nil ────────────────────────────────────────────────────
    if predicted == "wtn_home":
        return (result == "H" and away_score == 0), result
    if predicted == "wtn_away":
        return (result == "A" and home_score == 0), result

    # ── Asian Handicap / Spreads (approximate: use win/loss) ──────────
    # True AH resolution needs the exact handicap line used at bet time.
    # Until we store that, we approximate: AH home = home win, AH away = away win.
    if predicted in ("ah_home", "home_spread"):
        return result == "H", result
    if predicted in ("ah_away", "away_spread"):
        return result == "A", result

    # ── Unknown ───────────────────────────────────────────────────────
    return None, result or "unknown"


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

    # outcome → (market, outcome_key, point) for CLV lookup
    CLV_LOOKUP: dict[str, tuple[str, str, Optional[float]]] = {
        "H":           ("h2h",            "home",      None),
        "D":           ("h2h",            "draw",      None),
        "A":           ("h2h",            "away",      None),
        "over_1.5":    ("totals",         "over",      1.5),
        "over_2.5":    ("totals",         "over",      2.5),
        "over_3.5":    ("totals",         "over",      3.5),
        "over_4.5":    ("totals",         "over",      4.5),
        "under_1.5":   ("totals",         "under",     1.5),
        "under_2.5":   ("totals",         "under",     2.5),
        "under_3.5":   ("totals",         "under",     3.5),
        "btts_yes":    ("btts",           "yes",       None),
        "btts_no":     ("btts",           "no",        None),
        "dnb_home":    ("draw_no_bet",    "home",      None),
        "dnb_away":    ("draw_no_bet",    "away",      None),
        "dc_1x":       ("double_chance",  "home_draw", None),
        "dc_x2":       ("double_chance",  "away_draw", None),
        "dc_12":       ("double_chance",  "home_away", None),
        "wtn_home":    ("win_to_nil",     "home",      None),
        "wtn_away":    ("win_to_nil",     "away",      None),
        "ah_home":     ("asian_handicap", "home",      None),
        "ah_away":     ("asian_handicap", "away",      None),
        "home_spread": ("spreads",        "home",      None),
        "away_spread": ("spreads",        "away",      None),
    }

    for m in finished:
        md   = db.query(MatchDecision).filter_by(match_id=m.id).first()
        pred = m.predictions[0] if m.predictions else None
        if not md or not pred:
            continue

        sport_key   = m.competition.sport.key if m.competition and m.competition.sport else "unknown"
        competition = m.competition.name if m.competition else ""
        actual      = m.result           # "H" / "D" / "A" for all sports

        # ── Determine if pick was correct for any market type ─────────
        is_correct, actual_label = _evaluate_outcome(
            md.predicted_outcome or "",
            actual or "",
            m.home_score,
            m.away_score,
        )

        odds_used = md.recommended_odds or 1.5
        stake     = md.recommended_stake_pct or 0.01

        # DNB draw = push (stake returned, P&L = 0)
        pnl = 0.0
        if md.ai_decision == "PLAY":
            if is_correct is None:       # push (DNB draw)
                pnl = 0.0
            elif is_correct:
                pnl = stake * (odds_used - 1)
            else:
                pnl = -stake

        # ── CLV: compare decision odds vs latest odds before kickoff ──
        from data.db_models.models import MatchOdds as _MatchOdds
        clv: Optional[float] = None
        closing_odds: Optional[float] = None
        if md.odds_at_decision and md.predicted_outcome in CLV_LOOKUP:
            mkt, db_out, pt = CLV_LOOKUP[md.predicted_outcome]
            q = (
                db.query(_MatchOdds)
                .filter_by(match_id=m.id, market=mkt, outcome=db_out)
                .filter(_MatchOdds.recorded_at <= m.match_date)
            )
            if pt is not None:
                q = q.filter(_MatchOdds.point == pt)
            latest = q.order_by(_MatchOdds.recorded_at.desc()).first()
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
            actual_result     = actual_label,
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
