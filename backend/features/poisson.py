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
        x0 = np.zeros(2 * n + 2)
        x0[2 * n]     = math.log(self.home_advantage)
        x0[2 * n + 1] = DEFAULT_RHO

        bounds = (
            [(-3.0, 3.0)] * n +         # log attack
            [(-3.0, 3.0)] * n +         # log defence
            [(0.0, 1.0)] +              # log home_adv
            [(-0.4, 0.0)]               # rho
        )

        # ── Pre-compute numpy arrays for vectorised likelihood ─────────────
        # Map team names → integer indices; drop rows with unknown teams
        hi_arr = np.array([team_idx[r] for r in df["home_name"]], dtype=np.int32)
        ai_arr = np.array([team_idx[r] for r in df["away_name"]], dtype=np.int32)
        hg_arr = df["home_score"].astype(int).values
        ag_arr = df["away_score"].astype(int).values
        w_arr  = df["weight"].values

        # Pre-compute log-factorial for scores (max_goals cap at 12 for PMF)
        max_g   = max(int(hg_arr.max()), int(ag_arr.max()), 12)
        logfact = np.array([math.lgamma(k + 1) for k in range(max_g + 1)])

        def _log_poisson(k_arr: np.ndarray, mu: np.ndarray) -> np.ndarray:
            """Vectorised log P(k; mu) = k*log(mu) - mu - log(k!)"""
            log_mu = np.log(np.maximum(mu, 1e-9))
            return k_arr * log_mu - mu - logfact[k_arr]

        def neg_log_likelihood(params):
            log_atk = params[:n]
            log_def = params[n:2*n]
            log_ha  = params[2*n]
            rho     = params[2*n+1]
            ha      = math.exp(log_ha)

            # Vectorised Poisson means for all matches
            mu_h = self.league_avg_goals * np.exp(log_atk[hi_arr] - log_def[ai_arr]) * ha
            mu_a = self.league_avg_goals * np.exp(log_atk[ai_arr] - log_def[hi_arr])

            # Vectorised Poisson log-PMF
            lp_h = _log_poisson(hg_arr, mu_h)
            lp_a = _log_poisson(ag_arr, mu_a)

            # Vectorised Dixon-Coles low-score correction (tau factor in log space)
            # Only 0-0, 0-1, 1-0, 1-1 deviate from independence
            log_tau = np.zeros(len(hi_arr))
            m00 = (hg_arr == 0) & (ag_arr == 0)
            m01 = (hg_arr == 0) & (ag_arr == 1)
            m10 = (hg_arr == 1) & (ag_arr == 0)
            m11 = (hg_arr == 1) & (ag_arr == 1)
            # tau must stay positive; clip to small positive before log
            log_tau[m00] = np.log(np.maximum(1.0 - mu_h[m00] * mu_a[m00] * rho, 1e-9))
            log_tau[m01] = np.log(np.maximum(1.0 + mu_h[m01] * rho,              1e-9))
            log_tau[m10] = np.log(np.maximum(1.0 + mu_a[m10] * rho,              1e-9))
            log_tau[m11] = np.log(np.maximum(1.0 - rho,                          1e-9))

            log_p = log_tau + lp_h + lp_a
            return -float(np.dot(w_arr, log_p))

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

        sm = score_matrix  # alias for readability

        # ── 1X2 ──────────────────────────────────────────────────────────
        home_win = float(np.tril(sm, -1).sum())
        draw     = float(np.trace(sm))
        away_win = float(np.triu(sm, 1).sum())

        # ── BTTS ─────────────────────────────────────────────────────────
        btts_yes = float(sm[1:, 1:].sum())
        btts_no  = 1.0 - btts_yes

        # ── Over/Under goal lines ─────────────────────────────────────────
        def _over(line: float) -> float:
            return float(sum(
                sm[h, a]
                for h in range(MAX_GOALS + 1)
                for a in range(MAX_GOALS + 1)
                if h + a > line
            ))

        over_0_5 = _over(0)
        over_1_5 = _over(1)
        over_2_5 = _over(2)
        over_3_5 = _over(3)
        over_4_5 = _over(4)

        # ── Double Chance ─────────────────────────────────────────────────
        dc_1x = home_win + draw   # home or draw
        dc_x2 = draw + away_win   # draw or away
        dc_12 = home_win + away_win  # home or away (no draw)

        # ── Draw No Bet ───────────────────────────────────────────────────
        no_draw_total = home_win + away_win
        dnb_home = home_win / no_draw_total if no_draw_total > 0 else 0.5
        dnb_away = away_win / no_draw_total if no_draw_total > 0 else 0.5

        # ── Asian Handicap -0.5 (home must win outright) ──────────────────
        ah_home_neg05 = home_win
        ah_away_neg05 = draw + away_win   # away covers if draw or away wins

        # ── Asian Handicap +0.5 (away must win outright) ──────────────────
        ah_home_pos05 = home_win + draw
        ah_away_pos05 = away_win

        # ── Asian Handicap -1 (home wins by 2+; push on win by 1) ────────
        ah_home_neg1  = float(sum(sm[h, a] for h in range(MAX_GOALS+1) for a in range(MAX_GOALS+1) if h - a >= 2))
        ah_push_neg1  = float(sum(sm[h, a] for h in range(MAX_GOALS+1) for a in range(MAX_GOALS+1) if h - a == 1))
        ah_away_neg1  = float(sum(sm[h, a] for h in range(MAX_GOALS+1) for a in range(MAX_GOALS+1) if h - a <= 0))

        # ── Asian Handicap +1 (away wins by 2+; push on away win by 1) ───
        ah_away_pos1  = float(sum(sm[h, a] for h in range(MAX_GOALS+1) for a in range(MAX_GOALS+1) if a - h >= 2))
        ah_push_pos1  = float(sum(sm[h, a] for h in range(MAX_GOALS+1) for a in range(MAX_GOALS+1) if a - h == 1))
        ah_home_pos1  = float(sum(sm[h, a] for h in range(MAX_GOALS+1) for a in range(MAX_GOALS+1) if h - a >= 0))

        # ── Clean sheets ──────────────────────────────────────────────────
        home_cs = float(sm[:, 0].sum())   # home keeps clean sheet (away scores 0)
        away_cs = float(sm[0, :].sum())   # away keeps clean sheet (home scores 0)

        # ── Win to Nil ────────────────────────────────────────────────────
        home_wtn = float(sum(sm[h, 0] for h in range(1, MAX_GOALS + 1)))   # home wins AND away 0
        away_wtn = float(sum(sm[0, a] for a in range(1, MAX_GOALS + 1)))   # away wins AND home 0

        # ── BTTS + Result combos ──────────────────────────────────────────
        btts_home = float(sum(sm[h, a] for h in range(1, MAX_GOALS+1) for a in range(1, MAX_GOALS+1) if h > a))
        btts_draw = float(sum(sm[h, h] for h in range(1, MAX_GOALS+1)))
        btts_away = float(sum(sm[h, a] for h in range(1, MAX_GOALS+1) for a in range(1, MAX_GOALS+1) if a > h))

        # ── Top correct scores (top 8 by probability) ─────────────────────
        score_probs = [
            {"home": h, "away": a, "prob": round(float(sm[h, a]), 5)}
            for h in range(MAX_GOALS + 1)
            for a in range(MAX_GOALS + 1)
        ]
        top_scores = sorted(score_probs, key=lambda x: x["prob"], reverse=True)[:8]

        return {
            # ── 1X2 ──
            "home_win":  home_win,
            "draw":      draw,
            "away_win":  away_win,
            # ── Double Chance ──
            "double_chance_1x": dc_1x,
            "double_chance_x2": dc_x2,
            "double_chance_12": dc_12,
            # ── Draw No Bet ──
            "dnb_home": dnb_home,
            "dnb_away": dnb_away,
            # ── Asian Handicap ──
            "ah_home_-0.5": ah_home_neg05,
            "ah_away_-0.5": ah_away_neg05,
            "ah_home_+0.5": ah_home_pos05,
            "ah_away_+0.5": ah_away_pos05,
            "ah_home_-1.0": ah_home_neg1,
            "ah_push_-1.0": ah_push_neg1,
            "ah_away_-1.0": ah_away_neg1,
            "ah_home_+1.0": ah_home_pos1,
            "ah_push_+1.0": ah_push_pos1,
            "ah_away_+1.0": ah_away_pos1,
            # ── Over/Under ──
            "over_0.5":  over_0_5,
            "under_0.5": 1.0 - over_0_5,
            "over_1.5":  over_1_5,
            "under_1.5": 1.0 - over_1_5,
            "over_2.5":  over_2_5,
            "under_2.5": 1.0 - over_2_5,
            "over_3.5":  over_3_5,
            "under_3.5": 1.0 - over_3_5,
            "over_4.5":  over_4_5,
            "under_4.5": 1.0 - over_4_5,
            # ── BTTS ──
            "btts_yes": btts_yes,
            "btts_no":  btts_no,
            # ── BTTS + Result ──
            "btts_home_win": btts_home,
            "btts_draw":     btts_draw,
            "btts_away_win": btts_away,
            # ── Clean Sheets / Win to Nil ──
            "home_clean_sheet": home_cs,
            "away_clean_sheet": away_cs,
            "home_win_to_nil":  home_wtn,
            "away_win_to_nil":  away_wtn,
            # ── Correct Score ──
            "top_correct_scores": top_scores,
            # ── Expected goals ──
            "exp_home_goals": mu_h,
            "exp_away_goals": mu_a,
            "score_matrix": sm.tolist(),
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

def build_dc_model_from_db(db, sport_key: str = "football", years: int = 2) -> DixonColes:
    """
    Fit a Dixon-Coles model from the last `years` years of finished matches.
    Rolling window prevents stale team ratings from diluting recent form.
    Returns the fitted model (not persisted — caller may cache it).
    """
    from data.db_models.models import Match, Competition, Sport, Participant
    from sqlalchemy.orm import joinedload
    from datetime import datetime, timedelta

    sport = db.query(Sport).filter_by(key=sport_key).first()
    if not sport:
        return DixonColes()

    cutoff = datetime.utcnow() - timedelta(days=365 * years)

    matches = (
        db.query(Match)
        .join(Competition)
        .filter(
            Competition.sport_id == sport.id,
            Match.result.isnot(None),
            Match.match_date >= cutoff,
        )
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
