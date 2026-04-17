"""
Dixon-Coles Poisson model for football score prediction.

This model:
  1. Fits attack / defence strength parameters per team using maximum likelihood
  2. Applies the Dixon-Coles correction for low-scoring outcomes (0-0, 1-0, 0-1, 1-1)
     which Poisson over-estimates
  3. Integrates a time-decay weight so recent matches influence ratings more
  4. Outputs per-score probabilities → 1X2 / over-under / BTTS with better accuracy
     than the simple attack-strength proxy in engineering.py

Usage:
    dc = DixonColes()
    dc.fit(matches_df)          # one-time fit on historical data
    probs = dc.predict(home_team, away_team)
    # probs["home_win"], probs["draw"], probs["away_win"]
    # probs["over_2.5"], probs["btts"]
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from loguru import logger

# Max score considered in the score matrix
MAX_GOALS = 10

# Dixon-Coles rho correction (default; also estimated during fitting)
DEFAULT_RHO = -0.130


def _dc_correction(home_goals: int, away_goals: int, mu_h: float, mu_a: float, rho: float) -> float:
    """
    Low-score correction factor τ(x, y, μ_h, μ_a, ρ).
    Applied to (0,0), (1,0), (0,1), (1,1).
    """
    if home_goals == 0 and away_goals == 0:
        return 1.0 - mu_h * mu_a * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + mu_a * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + mu_h * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(min(k, 20))


class DixonColes:
    """
    Dixon-Coles Poisson model fitted on historical match data.

    Parameters
    ----------
    home_advantage : float
        Multiplicative home advantage applied to home attack rating.
        Estimated during fitting if data is sufficient.
    decay_rate : float
        Time-weighting: weight = exp(-decay * days_ago / 365).
        0.0 = no decay (all games equal), 0.3 = strong recency bias.
    """

    def __init__(self, home_advantage: float = 1.25, decay_rate: float = 0.18):
        self.home_advantage = home_advantage
        self.decay_rate = decay_rate
        self.rho = DEFAULT_RHO
        self.attack: dict[str, float] = {}
        self.defence: dict[str, float] = {}
        self.league_avg_goals: float = 1.35
        self._fitted = False

    # ── Fitting ───────────────────────────────────────────────────────────────

    def fit(self, df: pd.DataFrame) -> "DixonColes":
        """
        Fit attack/defence ratings from historical matches.

        df must have columns:
          home_name, away_name, home_score, away_score, match_date (datetime)

        Returns self for chaining.
        """
        df = df.dropna(subset=["home_score", "away_score"]).copy()
        if len(df) < 50:
            logger.warning("[DixonColes] Too few matches to fit — using defaults")
            return self

        df["match_date"] = pd.to_datetime(df["match_date"])
        latest = df["match_date"].max()
        df["days_ago"] = (latest - df["match_date"]).dt.days
        df["weight"]   = np.exp(-self.decay_rate * df["days_ago"] / 365.0)

        # Collect all teams
        teams = sorted(set(df["home_name"]) | set(df["away_name"]))
        team_idx = {t: i for i, t in enumerate(teams)}
        n = len(teams)

        self.league_avg_goals = (df["home_score"].mean() + df["away_score"].mean()) / 2.0

        # Initial parameter vector:
        # [attack_0..n-1, defence_0..n-1, home_adv, rho]
        # Constraint: sum(attack) = 0 (log-space, one team is anchor)
        x0 = np.zeros(2 * n + 2)
        x0[2 * n]     = math.log(self.home_advantage)
        x0[2 * n + 1] = DEFAULT_RHO

        bounds = (
            [(-3.0, 3.0)] * n +         # log attack
            [(-3.0, 3.0)] * n +         # log defence
            [(0.0, 1.0)] +              # log home_adv
            [(-0.4, 0.0)]               # rho
        )

        def neg_log_likelihood(params):
            log_atk = params[:n]
            log_def = params[n:2*n]
            log_ha  = params[2*n]
            rho     = params[2*n+1]
            ha = math.exp(log_ha)
            ll = 0.0
            for _, row in df.iterrows():
                hi = team_idx.get(row["home_name"])
                ai = team_idx.get(row["away_name"])
                if hi is None or ai is None:
                    continue
                mu_h = self.league_avg_goals * math.exp(log_atk[hi] - log_def[ai]) * ha
                mu_a = self.league_avg_goals * math.exp(log_atk[ai] - log_def[hi])
                hg, ag = int(row["home_score"]), int(row["away_score"])
                tau = _dc_correction(hg, ag, mu_h, mu_a, rho)
                p = (tau * _poisson_pmf(hg, mu_h) * _poisson_pmf(ag, mu_a))
                if p > 1e-10:
                    ll += row["weight"] * math.log(p)
            return -ll

        try:
            result = minimize(
                neg_log_likelihood, x0,
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 200, "ftol": 1e-7},
            )
            params = result.x
            log_atk = params[:n]
            log_def = params[n:2*n]
            self.home_advantage = math.exp(params[2*n])
            self.rho            = params[2*n+1]

            for i, t in enumerate(teams):
                self.attack[t]  = math.exp(log_atk[i])
                self.defence[t] = math.exp(log_def[i])

            self._fitted = True
            logger.info(
                f"[DixonColes] Fitted {n} teams on {len(df)} matches  "
                f"home_adv={self.home_advantage:.3f}  rho={self.rho:.3f}"
            )
        except Exception as e:
            logger.error(f"[DixonColes] Fitting failed: {e}")

        return self

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict(self, home_team: str, away_team: str) -> dict:
        """
        Return probability distribution over outcomes.

        Falls back gracefully: if team not in fitted ratings, uses league average.
        """
        # Get ratings (fall back to 1.0 = average)
        ha = self.attack.get(home_team, 1.0)
        hd = self.defence.get(home_team, 1.0)
        aa = self.attack.get(away_team, 1.0)
        ad = self.defence.get(away_team, 1.0)

        mu_h = self.league_avg_goals * ha / ad * self.home_advantage
        mu_a = self.league_avg_goals * aa / hd

        mu_h = max(0.1, mu_h)
        mu_a = max(0.1, mu_a)

        # Build score probability matrix
        score_matrix = np.zeros((MAX_GOALS + 1, MAX_GOALS + 1))
        for hg in range(MAX_GOALS + 1):
            for ag in range(MAX_GOALS + 1):
                tau = _dc_correction(hg, ag, mu_h, mu_a, self.rho)
                score_matrix[hg, ag] = (
                    tau * _poisson_pmf(hg, mu_h) * _poisson_pmf(ag, mu_a)
                )

        # Normalise
        total = score_matrix.sum()
        if total > 0:
            score_matrix /= total

        # Outcome probabilities
        home_win = float(np.tril(score_matrix, -1).sum())
        draw     = float(np.trace(score_matrix))
        away_win = float(np.triu(score_matrix, 1).sum())

        # BTTS: both teams score at least once
        btts_yes = float(score_matrix[1:, 1:].sum())

        # Over goals lines
        over_2_5 = float(sum(
            score_matrix[h, a]
            for h in range(MAX_GOALS + 1)
            for a in range(MAX_GOALS + 1)
            if h + a > 2
        ))
        over_1_5 = float(sum(
            score_matrix[h, a]
            for h in range(MAX_GOALS + 1)
            for a in range(MAX_GOALS + 1)
            if h + a > 1
        ))
        over_3_5 = float(sum(
            score_matrix[h, a]
            for h in range(MAX_GOALS + 1)
            for a in range(MAX_GOALS + 1)
            if h + a > 3
        ))

        return {
            "home_win":  home_win,
            "draw":      draw,
            "away_win":  away_win,
            "btts_yes":  btts_yes,
            "btts_no":   1.0 - btts_yes,
            "over_1.5":  over_1_5,
            "over_2.5":  over_2_5,
            "over_3.5":  over_3_5,
            "under_2.5": 1.0 - over_2_5,
            "exp_home_goals": mu_h,
            "exp_away_goals": mu_a,
            "score_matrix": score_matrix.tolist(),   # full 11×11 grid
        }

    def is_fitted(self) -> bool:
        return self._fitted

    def team_ratings(self) -> pd.DataFrame:
        """Return a DataFrame of attack / defence ratings sorted by attack desc."""
        teams = sorted(set(self.attack) | set(self.defence))
        rows = [
            {
                "team":    t,
                "attack":  round(self.attack.get(t, 1.0), 3),
                "defence": round(self.defence.get(t, 1.0), 3),
                "net":     round(self.attack.get(t, 1.0) / max(0.01, self.defence.get(t, 1.0)), 3),
            }
            for t in teams
        ]
        return pd.DataFrame(rows).sort_values("net", ascending=False)


# ── Convenience: fit from DB ──────────────────────────────────────────────────

def build_dc_model_from_db(db, sport_key: str = "football") -> DixonColes:
    """
    Fit a Dixon-Coles model from all finished football matches in the DB.
    Returns the fitted model (not persisted — caller may cache it).
    """
    from data.db_models.models import Match, Competition, Sport, Participant
    from sqlalchemy.orm import joinedload

    sport = db.query(Sport).filter_by(key=sport_key).first()
    if not sport:
        return DixonColes()

    matches = (
        db.query(Match)
        .join(Competition)
        .filter(Competition.sport_id == sport.id, Match.result.isnot(None))
        .options(joinedload(Match.home), joinedload(Match.away))
        .order_by(Match.match_date)
        .all()
    )

    if not matches:
        return DixonColes()

    df = pd.DataFrame([{
        "home_name":  m.home.name if m.home else "",
        "away_name":  m.away.name if m.away else "",
        "home_score": m.home_score or 0,
        "away_score": m.away_score or 0,
        "match_date": m.match_date,
    } for m in matches if m.home and m.away])

    dc = DixonColes()
    dc.fit(df)
    return dc
