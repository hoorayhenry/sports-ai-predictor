"""
Tier 1 statistical base models — sport-specific physics layer.

These models produce informed prior probabilities that become input features
for the Tier 2 XGB+LGB ensemble.  They encode domain knowledge that the
ML model would have to re-discover from scratch:

  ScoreDiffWinProb   — logistic sigmoid on score differential (basketball, NFL, rugby, etc.)
  SurfaceEloTracker  — separate ELO per surface for tennis (clay/grass/hard/indoor)
  detect_surface()   — infer surface from competition name
  detect_cricket_format() — classify T20 / ODI / Test from competition name

Leakage guarantee
-----------------
  All Tier 1 computations are strictly causal:
  - ScoreDiffWinProb is stateless (just a formula on already-computed features)
  - SurfaceEloTracker records the PRE-match ELO, then updates AFTER — the
    build_training_matrix() caller must maintain this order.
"""
from __future__ import annotations

import math
from typing import Optional

# ---------------------------------------------------------------------------
# Surface detection
# ---------------------------------------------------------------------------

_CLAY_KEYWORDS = [
    "roland garros", "french open", "clay",
    "monte carlo", "monte-carlo", "barcelona",
    "madrid open", "internazionali", "rome", "hamburg",
    "rio open", "buenos aires", "santiago", "bogota",
    "istanbul", "casablanca", "lyon", "marrakech",
    "munich", "estoril", "genova", "kitzbühel",
    "umag", "gstaad", "bastad", "swedish",
]

_GRASS_KEYWORDS = [
    "wimbledon", "grass",
    "halle", "queens", "queen's",
    "eastbourne", "hertogenbosch", "'s-hertogenbosch",
    "nottingham", "newport grass", "birmingham",
]

_INDOOR_KEYWORDS = [
    "indoor", "o2 arena", "atp finals", "nitto atp",
    "paris masters", "bercy",
    "rotterdam", "sofia", "montpellier", "marseille",
    "st. petersburg", "metz", "vienna",
    "swiss indoors", "kremlin cup",
]

# Default for everything else: hard court
SURFACES = ("clay", "grass", "hard", "indoor")


def detect_surface(competition_name: str) -> str:
    """
    Infer tennis surface from competition name.
    Returns one of: 'clay', 'grass', 'hard', 'indoor'.
    Defaults to 'hard' (most common surface).
    """
    name = (competition_name or "").lower()
    if any(k in name for k in _CLAY_KEYWORDS):
        return "clay"
    if any(k in name for k in _GRASS_KEYWORDS):
        return "grass"
    if any(k in name for k in _INDOOR_KEYWORDS):
        return "indoor"
    return "hard"


# ---------------------------------------------------------------------------
# Cricket format detection
# ---------------------------------------------------------------------------

_T20_KEYWORDS = [
    "t20", "twenty20", "t-20",
    "ipl", "indian premier league",
    "big bash", "bbl",
    "sa20", "csa t20",
    "caribbean premier", "cpl",
    "pakistan super", "psl",
    "hundred", "the hundred",
    "vitality blast",
    "super smash",
    "ram slam",
    "dream11",
    "global t20",
    "lanka premier",
    "bangladesh premier", "bpl",
    "abu dhabi t10",   # T10 but same model
]

_TEST_KEYWORDS = [
    " test ", "test match", "test series",
    "ashes", "test cricket",
    "day/night test", "pink ball",
]


def detect_cricket_format(competition_name: str) -> str:
    """
    Classify cricket competition as 't20', 'test', or 'odi'.
    Returns one of: 't20', 'odi', 'test'.
    Defaults to 'odi' when ambiguous.
    """
    name = (competition_name or "").lower()
    if any(k in name for k in _T20_KEYWORDS):
        return "t20"
    if any(k in name for k in _TEST_KEYWORDS):
        return "test"
    return "odi"


# ---------------------------------------------------------------------------
# Score-differential win probability (stateless)
# ---------------------------------------------------------------------------

def score_diff_win_prob(
    home_score_diff: float,
    away_score_diff: float,
    avg_side: float,
) -> float:
    """
    Convert score-differential features into a calibrated home win probability.

    Uses a logistic sigmoid scaled to the sport's natural scoring range.
    Scale parameter = avg_side / 2 so that a 1-std-dev advantage maps to
    roughly 65% win probability — empirically calibrated across sports.

    Parameters
    ----------
    home_score_diff : average margin per game for the home team (last 10)
    away_score_diff : average margin per game for the away team (last 10)
    avg_side        : sport's average score per team per game (from SportProfile)
                      e.g. football=1.38, basketball=107, hockey=3.1, NFL=22.5

    Returns
    -------
    float in (0, 1)
    """
    net_diff = home_score_diff - away_score_diff
    # Scale: half an avg_side is the "typical" differential
    scale = max(avg_side * 0.5, 0.5)
    z = net_diff / scale
    # Clamp to avoid extreme probabilities
    z = max(-5.0, min(5.0, z))
    return 1.0 / (1.0 + math.exp(-z))


# ---------------------------------------------------------------------------
# Surface-specific ELO for tennis
# ---------------------------------------------------------------------------

_SURFACE_HOME_ADV = 30.0   # smaller than general ELO (tennis barely has home advantage)
_SURFACE_DEFAULT  = 1500.0
_SURFACE_K        = 20.0   # smaller K → slower drift (surface ratings are more stable)


class SurfaceEloTracker:
    """
    Maintains separate ELO ratings per player per surface.

    No DB schema changes required — computed on-the-fly by replaying all
    historical tennis matches in chronological order.

    Leakage-safe usage (build_training_matrix):
        tracker = SurfaceEloTracker()
        for match in all_matches_chronological:
            # 1. Record PRE-match state (this is what goes into features)
            snap = tracker.snapshot(home_id, away_id, surface)
            # 2. Update AFTER recording
            if match.result:
                tracker.update(home_id, away_id, home_score, away_score, surface)
    """

    def __init__(self):
        # (player_id, surface) → elo_rating
        self._ratings: dict[tuple[int, str], float] = {}

    def get(self, player_id: int, surface: str) -> float:
        return self._ratings.get((player_id, surface), _SURFACE_DEFAULT)

    def diff(self, home_id: int, away_id: int, surface: str) -> float:
        """Home surface ELO minus away surface ELO (positive = home favoured)."""
        return self.get(home_id, surface) - self.get(away_id, surface)

    def snapshot(self, home_id: int, away_id: int, surface: str) -> dict:
        """Return the current (pre-match) surface ELO state for feature generation."""
        h = self.get(home_id, surface)
        a = self.get(away_id, surface)
        h_exp = 1.0 / (1.0 + 10 ** ((a - h - _SURFACE_HOME_ADV) / 400.0))
        return {
            "diff":   h - a,
            "h_elo":  h,
            "a_elo":  a,
            "h_prob": h_exp,      # surface-specific win probability
        }

    def update(
        self,
        home_id: int,
        away_id: int,
        home_score: float,
        away_score: float,
        surface: str,
    ) -> None:
        """Update ELO after a completed match."""
        h_elo = self.get(home_id, surface)
        a_elo = self.get(away_id, surface)

        h_exp = 1.0 / (1.0 + 10 ** ((a_elo - h_elo - _SURFACE_HOME_ADV) / 400.0))
        a_exp = 1.0 - h_exp

        if home_score > away_score:
            h_act, a_act = 1.0, 0.0
        elif home_score < away_score:
            h_act, a_act = 0.0, 1.0
        else:
            h_act, a_act = 0.5, 0.5  # rare but handle draws

        self._ratings[(home_id, surface)] = h_elo + _SURFACE_K * (h_act - h_exp)
        self._ratings[(away_id, surface)] = a_elo + _SURFACE_K * (a_act - a_exp)


# ---------------------------------------------------------------------------
# Per-sport extra feature names (beyond COMMON_FEATURES)
# ---------------------------------------------------------------------------

# These feature names MUST be present in build_row() output for the
# corresponding sport.  SportModel uses this to expand its feature list.
SPORT_EXTRA_FEATURES: dict[str, list[str]] = {
    "tennis":  ["surface_elo_diff", "surface_h_elo", "surface_a_elo", "surface_h_prob"],
    "cricket": ["format_t20", "format_odi"],
}


# ---------------------------------------------------------------------------
# General ELO tracker — leakage-safe in-memory replay
# ---------------------------------------------------------------------------

class EloTracker:
    """
    Replays match history in chronological order to compute historically-correct
    ELO ratings at the time of each match.

    Eliminates DB ELO leakage: the persisted ``elo_rating`` column reflects
    post-all-matches (current) ELO — using it as a training feature leaks the
    outcome of future matches into rows that pre-date them.

    Leakage-safe usage (build_training_matrix):
        tracker = EloTracker(has_draw=True)
        for match in all_matches_chronological:
            snap = tracker.snapshot(home_id, away_id)  # PRE-match state
            # ... use snap for features ...
            if match.result:
                tracker.update(home_id, away_id, home_score, away_score, match_date)
    """

    _DEFAULT = 1500.0

    def __init__(self, has_draw: bool = True):
        self.has_draw = has_draw
        self._ratings: dict[int, float] = {}
        self._current_season: int | None = None

    def get(self, team_id: int) -> float:
        return self._ratings.get(team_id, self._DEFAULT)

    def snapshot(self, home_id: int, away_id: int) -> dict:
        """Return current (pre-match) ELO state as a feature dict."""
        from features.elo import win_probabilities
        h = self.get(home_id)
        a = self.get(away_id)
        probs = win_probabilities(h, a, self.has_draw)
        return {
            "home_elo":      h,
            "away_elo":      a,
            "elo_diff":      h - a,
            "elo_home_prob": probs.get("home", 0.4),
            "elo_draw_prob": probs.get("draw", 0.25),
            "elo_away_prob": probs.get("away", 0.35),
        }

    def update(
        self,
        home_id: int,
        away_id: int,
        home_score: float,
        away_score: float,
        match_date,
    ) -> None:
        """Update ELO ratings after a completed match. Applies seasonal decay at season boundaries."""
        from features.elo import update_elo, apply_seasonal_decay

        # Season boundary: July = start of new European season.
        # Apply seasonal decay to all tracked teams when season rolls over.
        season_year = match_date.year if match_date.month >= 7 else match_date.year - 1
        if self._current_season is not None and season_year != self._current_season:
            for tid in list(self._ratings):
                self._ratings[tid] = apply_seasonal_decay(self._ratings[tid])
        self._current_season = season_year

        h_new, a_new = update_elo(
            self.get(home_id), self.get(away_id), home_score, away_score
        )
        self._ratings[home_id] = h_new
        self._ratings[away_id] = a_new
