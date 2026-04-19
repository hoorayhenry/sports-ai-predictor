"""
Shared in-memory training progress state.
Updated by _auto_train() as each sport/market trains.
Read by the /analytics/training-progress endpoint.
"""
import threading
from datetime import datetime

_lock = threading.Lock()

SPORTS = [
    "football", "basketball", "tennis", "baseball",
    "american_football", "ice_hockey", "cricket",
    "rugby", "handball", "volleyball",
]

MARKETS = ["result", "over15", "over25", "over35", "btts", "home_cs", "away_cs"]

_state: dict = {
    "is_training": False,
    "started_at": None,
    "finished_at": None,
    "overall_pct": 0.0,
    "current_sport": None,
    "current_market": None,
    "sports": {},
}


def get_state() -> dict:
    with _lock:
        import copy
        return copy.deepcopy(_state)


def start_training() -> None:
    with _lock:
        _state["is_training"] = True
        _state["started_at"] = datetime.utcnow().isoformat()
        _state["finished_at"] = None
        _state["overall_pct"] = 0.0
        _state["current_sport"] = None
        _state["current_market"] = None
        _state["sports"] = {
            s: {
                "status": "pending",
                "markets_done": 0,
                "markets_total": len(MARKETS),
                "pct": 0.0,
                "rows": 0,
                "accuracy": None,
            }
            for s in SPORTS
        }


def sport_started(sport_key: str, rows: int) -> None:
    with _lock:
        if sport_key in _state["sports"]:
            _state["sports"][sport_key]["status"] = "training"
            _state["sports"][sport_key]["rows"] = rows
            _state["sports"][sport_key]["markets_done"] = 0
            _state["sports"][sport_key]["pct"] = 0.0
        _state["current_sport"] = sport_key
        _state["current_market"] = None
        _update_overall()


def market_done(sport_key: str, market: str) -> None:
    with _lock:
        if sport_key in _state["sports"]:
            s = _state["sports"][sport_key]
            s["markets_done"] = min(s["markets_done"] + 1, s["markets_total"])
            s["pct"] = (s["markets_done"] / s["markets_total"]) * 100.0
        _state["current_market"] = market
        _update_overall()


def sport_done(sport_key: str, accuracy: float | None, skipped: bool = False) -> None:
    with _lock:
        if sport_key in _state["sports"]:
            s = _state["sports"][sport_key]
            s["status"] = "skipped" if skipped else "done"
            s["pct"] = 100.0
            s["accuracy"] = accuracy
        _update_overall()


def finish_training() -> None:
    with _lock:
        _state["is_training"] = False
        _state["overall_pct"] = 100.0
        _state["finished_at"] = datetime.utcnow().isoformat()
        _state["current_sport"] = None
        _state["current_market"] = None


def _update_overall() -> None:
    sports = _state["sports"]
    if not sports:
        return
    _state["overall_pct"] = sum(s["pct"] for s in sports.values()) / len(sports)
