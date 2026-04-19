"""
Value bet engine — identifies positive expected value bets and sizes stakes
using fractional Kelly criterion.
"""
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger
from sqlalchemy.orm import Session
from data.db_models.models import Match, MatchOdds, Prediction
from config.settings import get_settings

settings = get_settings()


@dataclass
class ValueBet:
    match_id: int
    market: str
    outcome: str
    our_prob: float
    best_odds: float
    bookmaker: str
    ev: float
    kelly_stake: float         # fraction of bankroll (capped)
    confidence: str            # "high" | "medium" | "low"


def _best_odds(db: Session, match_id: int, market: str, outcome: str) -> tuple[float, str]:
    """Return (best_price, bookmaker) for the given outcome."""
    rows = db.query(MatchOdds).filter_by(match_id=match_id, market=market, outcome=outcome).all()
    if not rows:
        return 0.0, ""
    best = max(rows, key=lambda r: r.price)
    return best.price, best.bookmaker


def evaluate_match(db: Session, match_id: int, predictions: dict) -> list[ValueBet]:
    """
    Given model predictions dict (market -> outcome -> prob),
    return list of ValueBet objects where EV > threshold.

    Evaluates all available markets:
      ML-trained: result (1X2), over15/25/35, btts, home_cs, away_cs
      Poisson-derived (from dc_* keys): double chance, Asian handicap,
        draw no bet, BTTS+result, win to nil, clean sheets, correct score
    """
    checks: list[tuple[str, str, float]] = []

    # ── 1X2 (result) ─────────────────────────────────────────────────────
    result = predictions.get("result", {})
    for outcome_key, db_out in [("H", "home"), ("D", "draw"), ("A", "away")]:
        p = result.get(outcome_key) or result.get(db_out)
        if p is not None:
            checks.append(("h2h", db_out, p))

    # ── Over/Under (football lines) ───────────────────────────────────────
    for mkt_key, db_mkt in [("over15", "totals15"), ("over25", "totals"), ("over35", "totals35")]:
        mkt = predictions.get(mkt_key, {})
        if mkt:
            checks.append((db_mkt, "over",  mkt.get("over",  0)))
            checks.append((db_mkt, "under", mkt.get("under", 0)))

    # ── Over/Under (sport-specific main line: basketball 215.5, baseball 9.5…) ─
    over_main = predictions.get("over_main", {})
    if over_main:
        checks.append(("totals", "over",  over_main.get("over",  0)))
        checks.append(("totals", "under", over_main.get("under", 0)))

    # ── BTTS ──────────────────────────────────────────────────────────────
    btts = predictions.get("btts", {})
    if btts:
        checks.append(("btts", "yes", btts.get("yes", 0)))
        checks.append(("btts", "no",  btts.get("no",  0)))

    # ── Clean sheets (ML-trained) ─────────────────────────────────────────
    for mkt_key, db_mkt, out in [("home_cs", "clean_sheet", "home"), ("away_cs", "clean_sheet", "away")]:
        cs = predictions.get(mkt_key, {})
        if cs:
            checks.append((db_mkt, out, cs.get("yes", 0)))

    # ── Poisson-derived markets (from dc_probs key) ───────────────────────
    dc = predictions.get("dc_probs", {})
    if dc:
        # Double Chance
        checks.append(("double_chance", "1x", dc.get("double_chance_1x", 0)))
        checks.append(("double_chance", "x2", dc.get("double_chance_x2", 0)))
        checks.append(("double_chance", "12", dc.get("double_chance_12", 0)))

        # Draw No Bet
        checks.append(("dnb", "home", dc.get("dnb_home", 0)))
        checks.append(("dnb", "away", dc.get("dnb_away", 0)))

        # Asian Handicap
        checks.append(("ah",  "home_-0.5", dc.get("ah_home_-0.5", 0)))
        checks.append(("ah",  "away_-0.5", dc.get("ah_away_-0.5", 0)))
        checks.append(("ah",  "home_+0.5", dc.get("ah_home_+0.5", 0)))
        checks.append(("ah",  "away_+0.5", dc.get("ah_away_+0.5", 0)))
        checks.append(("ah",  "home_-1.0", dc.get("ah_home_-1.0", 0)))
        checks.append(("ah",  "away_-1.0", dc.get("ah_away_-1.0", 0)))
        checks.append(("ah",  "home_+1.0", dc.get("ah_home_+1.0", 0)))
        checks.append(("ah",  "away_+1.0", dc.get("ah_away_+1.0", 0)))

        # Win to Nil
        checks.append(("win_to_nil", "home", dc.get("home_win_to_nil", 0)))
        checks.append(("win_to_nil", "away", dc.get("away_win_to_nil", 0)))

        # BTTS + Result
        checks.append(("btts_result", "btts_home",  dc.get("btts_home_win", 0)))
        checks.append(("btts_result", "btts_draw",  dc.get("btts_draw",     0)))
        checks.append(("btts_result", "btts_away",  dc.get("btts_away_win", 0)))

        # Over 4.5
        checks.append(("totals45", "over",  dc.get("over_4.5",  0)))
        checks.append(("totals45", "under", dc.get("under_4.5", 0)))

    value_bets = []
    for mkt, outcome, our_prob in checks:
        if our_prob < settings.confidence_threshold:
            continue
        best_price, bm = _best_odds(db, match_id, mkt, outcome)
        if best_price < 1.1:
            continue

        ev = (our_prob * best_price) - 1.0
        if ev < settings.ev_threshold:
            continue

        # Fractional Kelly
        full_kelly = (our_prob - (1 - our_prob) / (best_price - 1)) if best_price > 1 else 0
        kelly = max(0.0, min(full_kelly * settings.kelly_fraction, settings.max_kelly_stake))

        if ev >= 0.15:
            conf = "high"
        elif ev >= 0.08:
            conf = "medium"
        else:
            conf = "low"

        value_bets.append(ValueBet(
            match_id=match_id,
            market=mkt,
            outcome=outcome,
            our_prob=our_prob,
            best_odds=best_price,
            bookmaker=bm,
            ev=ev,
            kelly_stake=kelly,
            confidence=conf,
        ))

    return value_bets


def save_predictions(db: Session, match: Match, pred_probs: dict, value_bets: list[ValueBet]):
    """Persist predictions and value bets to the Prediction table."""
    import json

    db.query(Prediction).filter_by(match_id=match.id).delete()

    result_probs = pred_probs.get("result", {})
    over25_probs = pred_probs.get("over25", {})
    btts_probs   = pred_probs.get("btts", {})
    dc_probs     = pred_probs.get("dc_probs", {})

    # Determine predicted result
    if result_probs:
        pred_result = max(result_probs, key=result_probs.get)
        remap = {"home": "H", "draw": "D", "away": "A", "H": "H", "D": "D", "A": "A"}
        pred_result = remap.get(pred_result, pred_result)
    else:
        pred_result = None

    # Best value bet across ALL markets
    best_vb = max(value_bets, key=lambda v: v.ev) if value_bets else None

    # ── Build full markets JSON ──────────────────────────────────────────
    # Store all probabilities for every market so the API can serve any of them
    markets: dict = {}

    # ML-trained markets (sport-adaptive — store whatever the model returned)
    for mkt in ["result", "over15", "over25", "over35", "btts", "home_cs", "away_cs", "over_main"]:
        if mkt in pred_probs:
            markets[mkt] = pred_probs[mkt]

    # Poisson-derived markets (from dc_probs)
    if dc_probs:
        for key in [
            "double_chance_1x", "double_chance_x2", "double_chance_12",
            "dnb_home", "dnb_away",
            "ah_home_-0.5", "ah_away_-0.5", "ah_home_+0.5", "ah_away_+0.5",
            "ah_home_-1.0", "ah_push_-1.0", "ah_away_-1.0",
            "ah_home_+1.0", "ah_push_+1.0", "ah_away_+1.0",
            "over_0.5", "under_0.5", "over_1.5", "under_1.5",
            "over_3.5", "under_3.5", "over_4.5", "under_4.5",
            "home_clean_sheet", "away_clean_sheet",
            "home_win_to_nil", "away_win_to_nil",
            "btts_home_win", "btts_draw", "btts_away_win",
            "top_correct_scores",
            "exp_home_goals", "exp_away_goals",
        ]:
            if key in dc_probs:
                markets[key] = dc_probs[key]

    # Value bet summary — top 3 by EV for the API to display
    markets["value_bets"] = [
        {
            "market": vb.market, "outcome": vb.outcome,
            "prob": round(vb.our_prob, 4), "odds": vb.best_odds,
            "ev": round(vb.ev, 4), "kelly": round(vb.kelly_stake, 4),
            "confidence": vb.confidence,
        }
        for vb in sorted(value_bets, key=lambda v: v.ev, reverse=True)[:3]
    ]

    p = Prediction(
        match_id=match.id,
        predicted_result=pred_result,
        home_win_prob=result_probs.get("H") or result_probs.get("home"),
        draw_prob=result_probs.get("D") or result_probs.get("draw"),
        away_win_prob=result_probs.get("A") or result_probs.get("away"),
        over25_prob=over25_probs.get("over"),
        btts_prob=btts_probs.get("yes"),
        markets_json=json.dumps(markets),
        is_value_bet=bool(value_bets),
        value_market=best_vb.market if best_vb else None,
        value_outcome=best_vb.outcome if best_vb else None,
        value_odds=best_vb.best_odds if best_vb else None,
        expected_value=best_vb.ev if best_vb else None,
        kelly_stake=best_vb.kelly_stake if best_vb else None,
        confidence=best_vb.confidence if best_vb else None,
    )
    db.add(p)
    db.commit()
    return p
