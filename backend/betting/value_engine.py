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

    predictions example:
    {
        "result":  {"H": 0.52, "D": 0.24, "A": 0.24},
        "over25":  {"over": 0.61, "under": 0.39},
        "btts":    {"yes": 0.55, "no": 0.45},
    }
    """
    # Market/outcome mapping: (db_market, db_outcome, pred_key, pred_outcome)
    checks = []

    result = predictions.get("result", {})
    for outcome_key, db_out in [("H", "home"), ("D", "draw"), ("A", "away")]:
        if outcome_key in result:
            checks.append(("h2h", db_out, result[outcome_key]))

    if "over25" in predictions:
        checks.append(("totals", "over", predictions["over25"]["over"]))
        checks.append(("totals", "under", predictions["over25"]["under"]))

    if "btts" in predictions:
        checks.append(("btts", "yes", predictions["btts"]["yes"]))
        checks.append(("btts", "no", predictions["btts"]["no"]))

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
    # Remove old predictions for this match
    db.query(Prediction).filter_by(match_id=match.id).delete()

    result_probs = pred_probs.get("result", {})
    over25_probs = pred_probs.get("over25", {})
    btts_probs   = pred_probs.get("btts", {})

    # Determine predicted result
    if result_probs:
        pred_result = max(result_probs, key=result_probs.get)
        # Normalise key: H/home -> H, etc.
        remap = {"home": "H", "draw": "D", "away": "A", "H": "H", "D": "D", "A": "A"}
        pred_result = remap.get(pred_result, pred_result)
    else:
        pred_result = None

    # Pick the best value bet across ALL markets (not just h2h)
    best_vb = max(value_bets, key=lambda v: v.ev) if value_bets else None

    p = Prediction(
        match_id=match.id,
        predicted_result=pred_result,
        home_win_prob=result_probs.get("H") or result_probs.get("home"),
        draw_prob=result_probs.get("D") or result_probs.get("draw"),
        away_win_prob=result_probs.get("A") or result_probs.get("away"),
        over25_prob=over25_probs.get("over"),
        btts_prob=btts_probs.get("yes"),
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
