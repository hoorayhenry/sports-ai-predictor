"""
Sport profiles — the single source of truth for how each sport works.

Every sport has completely different physics:
  - Score scale  (basketball: 80-130 pts, football: 0-4 goals)
  - Outcome type (basketball/baseball/NHL: no real draws; football: draws common)
  - Market set   (different betting markets make sense per sport)
  - Totals lines (must be scaled to the sport's scoring range)
  - Home advantage (varies significantly by sport and venue type)

These profiles drive:
  • Feature engineering (what "form" means per sport)
  • Model training     (binary vs 3-class, totals thresholds)
  • Decision engine    (which markets to evaluate, what odds to look for)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SportProfile:
    # ── Outcome structure ─────────────────────────────────────────────
    binary: bool           # True = only H/A (no draws), False = H/D/A
    outcomes: list[str]    # ["H","A"] or ["H","D","A"]

    # ── Scoring scale ─────────────────────────────────────────────────
    avg_total: float       # typical combined score (e.g. 9.4 for baseball)
    avg_side:  float       # typical score per team
    score_unit: str        # "goals", "points", "runs", "sets"

    # ── Totals betting lines (over/under thresholds) ─────────────────
    totals_lines: list[float]

    # ── Home advantage (typical edge in score units) ──────────────────
    home_advantage: float  # e.g. 3.0 pts NBA, 0.4 goals football

    # ── Spread / handicap market ──────────────────────────────────────
    has_spread: bool       # can we bet the spread?
    typical_spread: float  # average point spread abs value

    # ── Draw handling ─────────────────────────────────────────────────
    draw_rate: float       # historical draw rate (0.0 for binary sports)

    # ── Pythagorean exponent (for pythag win pct feature) ────────────
    # Baseball ~2, Basketball ~16.5, Football ~2, Hockey ~2.15
    pythag_exp: float = 2.0

    # ── Feature names that are meaningful for this sport ─────────────
    extra_features: list[str] = field(default_factory=list)


SPORT_PROFILES: dict[str, SportProfile] = {

    # ── Football (soccer) ─────────────────────────────────────────────
    # 3-outcome, low-scoring, Poisson-distributed goals.
    # Draws are common (~25%). Home advantage ~0.4 goals.
    "football": SportProfile(
        binary        = False,
        outcomes      = ["H", "D", "A"],
        avg_total     = 2.75,
        avg_side      = 1.38,
        score_unit    = "goals",
        totals_lines  = [1.5, 2.5, 3.5, 4.5],
        home_advantage= 0.40,
        has_spread    = False,
        typical_spread= 0.0,
        draw_rate     = 0.26,
        pythag_exp    = 2.0,
        extra_features= [
            "dc_home_win", "dc_draw", "dc_away_win",
            "dc_over_2_5", "dc_btts_yes",
        ],
    ),

    # ── Basketball ────────────────────────────────────────────────────
    # Binary (no draws — OT/SO determines winner). High-scoring.
    # NBA avg ~215 combined pts. Pace hugely affects totals.
    # Home advantage ~3-4 points. Net rating is the key stat.
    "basketball": SportProfile(
        binary        = True,
        outcomes      = ["H", "A"],
        avg_total     = 215.0,
        avg_side      = 107.0,
        score_unit    = "points",
        totals_lines  = [195.5, 205.5, 215.5, 225.5, 235.5],
        home_advantage= 3.5,
        has_spread    = True,
        typical_spread= 5.5,
        draw_rate     = 0.0,
        pythag_exp    = 16.5,   # Pythagorean exponent calibrated for NBA
        extra_features= [
            "pace_home", "pace_away", "pace_diff",
            "net_rating_home", "net_rating_away",
            "off_rating_home", "def_rating_home",
            "off_rating_away", "def_rating_away",
            "home_pts_avg_10", "away_pts_avg_10",
            "home_pts_allowed_avg_10", "away_pts_allowed_avg_10",
            "home_total_avg_10", "away_total_avg_10",
            "home_pythag", "away_pythag",
            "back_to_back_home", "back_to_back_away",
            "home_consistency", "away_consistency",
        ],
    ),

    # ── Baseball ─────────────────────────────────────────────────────
    # Binary (extra innings determines winner). Moderate scoring.
    # MLB avg ~9.4 runs combined. Pythagorean expectation is the best
    # predictor because baseball has high variance (any team can win).
    # Run differential over a season is far more predictive than W/L.
    "baseball": SportProfile(
        binary        = True,
        outcomes      = ["H", "A"],
        avg_total     = 9.4,
        avg_side      = 4.7,
        score_unit    = "runs",
        totals_lines  = [6.5, 7.5, 8.5, 9.5, 10.5, 11.5],
        home_advantage= 0.25,   # modest in baseball vs other sports
        has_spread    = True,
        typical_spread= 1.5,    # run line is always 1.5
        draw_rate     = 0.0,
        pythag_exp    = 1.83,   # James' original baseball exponent
        extra_features= [
            "home_runs_avg_10", "away_runs_avg_10",
            "home_runs_allowed_avg_10", "away_runs_allowed_avg_10",
            "home_pythag", "away_pythag",
            "home_run_diff_avg_10", "away_run_diff_avg_10",
            "home_run_line_cover_rate", "away_run_line_cover_rate",
            "total_runs_avg_10",
            "home_consistency", "away_consistency",
        ],
    ),

    # ── Ice Hockey ────────────────────────────────────────────────────
    # Binary (OT/SO determines winner). Low-scoring like football.
    # Poisson model is appropriate. Goalie performance is #1 factor.
    # Home advantage moderate (~0.3 goals).
    "ice_hockey": SportProfile(
        binary        = True,
        outcomes      = ["H", "A"],
        avg_total     = 6.2,
        avg_side      = 3.1,
        score_unit    = "goals",
        totals_lines  = [4.5, 5.5, 6.5, 7.5],
        home_advantage= 0.30,
        has_spread    = True,
        typical_spread= 1.5,    # puck line is always 1.5
        draw_rate     = 0.0,
        pythag_exp    = 2.15,
        extra_features= [
            "home_goals_avg_10", "away_goals_avg_10",
            "home_goals_allowed_avg_10", "away_goals_allowed_avg_10",
            "home_pythag", "away_pythag",
            "home_goal_diff_avg_10", "away_goal_diff_avg_10",
            "home_clean_sheet_rate", "away_clean_sheet_rate",
            "home_consistency", "away_consistency",
            "back_to_back_home", "back_to_back_away",
        ],
    ),

    # ── American Football (NFL) ───────────────────────────────────────
    # Binary (OT determines winner, ties extremely rare).
    # Moderate-high scoring. POINT SPREAD is the primary market.
    # Home advantage ~3 points. Weather and rest are significant.
    "american_football": SportProfile(
        binary        = True,
        outcomes      = ["H", "A"],
        avg_total     = 45.0,
        avg_side      = 22.5,
        score_unit    = "points",
        totals_lines  = [38.5, 42.5, 46.5, 50.5, 54.5],
        home_advantage= 3.0,
        has_spread    = True,
        typical_spread= 5.5,
        draw_rate     = 0.0,
        pythag_exp    = 2.37,
        extra_features= [
            "home_pts_avg_10", "away_pts_avg_10",
            "home_pts_allowed_avg_10", "away_pts_allowed_avg_10",
            "home_pythag", "away_pythag",
            "home_point_diff_avg_10", "away_point_diff_avg_10",
            "home_spread_cover_rate", "away_spread_cover_rate",
            "home_consistency", "away_consistency",
            "back_to_back_home", "back_to_back_away",
        ],
    ),

    # ── Tennis ───────────────────────────────────────────────────────
    # Binary (no draws). Surface-dependent. H2H + recent form key.
    # Ranking/ELO are the primary signal. Head-to-head on surface matters.
    "tennis": SportProfile(
        binary        = True,
        outcomes      = ["H", "A"],
        avg_total     = 2.3,    # avg sets played
        avg_side      = 1.15,
        score_unit    = "sets",
        totals_lines  = [],     # sets totals are complex, skip
        home_advantage= 0.0,    # tennis played at neutral venues mostly
        has_spread    = False,
        typical_spread= 0.0,
        draw_rate     = 0.0,
        pythag_exp    = 2.0,
        extra_features= [
            "home_win_rate_h2h", "home_surface_win_rate",
            "away_surface_win_rate", "rank_diff",
            "home_fatigue", "away_fatigue",
        ],
    ),

    # ── Rugby ────────────────────────────────────────────────────────
    # Binary (draws rare, ~5%). High-scoring by score type (tries, penalties).
    # Strong home advantage. Attack vs defence key.
    "rugby": SportProfile(
        binary        = True,
        outcomes      = ["H", "A"],
        avg_total     = 42.0,
        avg_side      = 21.0,
        score_unit    = "points",
        totals_lines  = [34.5, 39.5, 44.5, 49.5],
        home_advantage= 4.0,
        has_spread    = True,
        typical_spread= 7.0,
        draw_rate     = 0.04,
        pythag_exp    = 2.0,
        extra_features= [
            "home_pts_avg_10", "away_pts_avg_10",
            "home_pts_allowed_avg_10", "away_pts_allowed_avg_10",
            "home_pythag", "away_pythag",
            "home_consistency", "away_consistency",
        ],
    ),

    # ── Handball ─────────────────────────────────────────────────────
    # 3-outcome (draws ~12%). Very high-scoring (50-70 goals combined).
    # Strong home advantage. Attack/defence strengths key.
    "handball": SportProfile(
        binary        = False,
        outcomes      = ["H", "D", "A"],
        avg_total     = 57.0,
        avg_side      = 28.5,
        score_unit    = "goals",
        totals_lines  = [49.5, 54.5, 59.5, 64.5],
        home_advantage= 3.5,
        has_spread    = False,
        typical_spread= 0.0,
        draw_rate     = 0.12,
        pythag_exp    = 2.0,
        extra_features= [
            "home_goals_avg_10", "away_goals_avg_10",
            "home_goals_allowed_avg_10", "away_goals_allowed_avg_10",
            "home_consistency", "away_consistency",
        ],
    ),

    # ── Cricket ──────────────────────────────────────────────────────
    # Binary (draws are possible in Test but rare in T20/ODI).
    # Hugely context-dependent (format, pitch, toss).
    "cricket": SportProfile(
        binary        = True,
        outcomes      = ["H", "A"],
        avg_total     = 320.0,
        avg_side      = 160.0,
        score_unit    = "runs",
        totals_lines  = [],
        home_advantage= 0.15,
        has_spread    = False,
        typical_spread= 0.0,
        draw_rate     = 0.05,
        pythag_exp    = 2.0,
        extra_features= [],
    ),

    # ── Volleyball ───────────────────────────────────────────────────
    # Binary (no draws). Set-based scoring. High-frequency scoring.
    "volleyball": SportProfile(
        binary        = True,
        outcomes      = ["H", "A"],
        avg_total     = 3.0,
        avg_side      = 1.5,
        score_unit    = "sets",
        totals_lines  = [],
        home_advantage= 0.2,
        has_spread    = False,
        typical_spread= 0.0,
        draw_rate     = 0.0,
        pythag_exp    = 2.0,
        extra_features= [],
    ),
}


def get_profile(sport_key: str) -> SportProfile:
    """Get profile for a sport, falling back to football defaults."""
    return SPORT_PROFILES.get(sport_key, SPORT_PROFILES["football"])


def is_binary(sport_key: str) -> bool:
    """Returns True if this sport has no draws (binary win/loss only)."""
    return get_profile(sport_key).binary


def totals_lines(sport_key: str) -> list[float]:
    """Return the betting totals lines for a sport."""
    return get_profile(sport_key).totals_lines


def pythagorean_win_pct(runs_scored: float, runs_allowed: float, exp: float) -> float:
    """
    Pythagorean win percentage — a fundamentals-based win predictor.
    Far more stable than actual W/L over small samples.
    rs^exp / (rs^exp + ra^exp)
    """
    if runs_scored <= 0 and runs_allowed <= 0:
        return 0.5
    rs = max(runs_scored, 0.01)
    ra = max(runs_allowed, 0.01)
    rs_e = rs ** exp
    return rs_e / (rs_e + ra ** exp)
