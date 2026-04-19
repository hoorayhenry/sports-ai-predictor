"""
Unified feature engineering for all sports.
Each sport has its own feature builder but shares common infrastructure.

Feature philosophy:
  - COMMON_FEATURES are computable for ALL sports from score history
  - Sport-specific extras are appended when training/predicting for that sport
  - Scale-agnostic: features like "avg_score_10" work whether the unit is
    football goals (1.4) or basketball points (107) — the model learns the scale
  - Pythagorean win% removes luck from W/L records across all sports
  - Back-to-back fatigue applies to basketball, NHL, baseball (dense schedules)
"""
import json
import math
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from sqlalchemy.orm import Session
from data.db_models.models import Match, Participant, Competition, Sport
from features.elo import win_probabilities
from features.sport_profiles import get_profile, is_binary as _sport_is_binary, pythagorean_win_pct

COMMON_FEATURES = [
    # ── Elo ──────────────────────────────────────────────────────────
    "home_elo", "away_elo", "elo_diff",
    "elo_home_prob", "elo_draw_prob", "elo_away_prob",
    # ── Form (generic — works for goals, points, runs) ───────────────
    "home_win_rate_5", "home_win_rate_10", "home_goals_avg_5", "home_goals_conceded_avg_5",
    "away_win_rate_5", "away_win_rate_10", "away_goals_avg_5", "away_goals_conceded_avg_5",
    # ── Head-to-head ─────────────────────────────────────────────────
    "h2h_home_win_rate", "h2h_draw_rate", "h2h_away_win_rate", "h2h_avg_goals", "h2h_n",
    # ── Attack / defence strength (Dixon-Coles style) ─────────────────
    "home_attack_str", "home_defence_str", "away_attack_str", "away_defence_str",
    # ── Expected score (Poisson proxy, scale-agnostic) ───────────────
    "exp_home_goals", "exp_away_goals", "exp_total_goals",
    # ── BTTS / over-2.5 base rates ───────────────────────────────────
    "home_btts_rate", "away_btts_rate", "home_over25_rate", "away_over25_rate",
    # ── Market-implied probabilities ─────────────────────────────────
    "imp_home_prob", "imp_draw_prob", "imp_away_prob", "market_margin",
    # ── Fatigue / scheduling ─────────────────────────────────────────
    "home_days_rest", "away_days_rest",
    # ── Intelligence signals (injuries / suspensions) ────────────────
    "home_injury_impact", "away_injury_impact",
    # ── League table position proxy ──────────────────────────────────
    "home_league_pts_rate", "away_league_pts_rate",
    "home_league_gd_per_game", "away_league_gd_per_game",
    "home_form_points", "away_form_points",
    "pts_rate_diff", "form_points_diff",
    # ── Historical season finish (from league_season_cache) ───────────
    "home_prev_season_rank", "away_prev_season_rank",
    # ── Shot-based features (xG proxy) ───────────────────────────────
    "home_shots_avg_5", "away_shots_avg_5",
    "home_sot_avg_5", "away_sot_avg_5",
    "home_shot_conv_5", "away_shot_conv_5",
    "home_xg_proxy_5", "away_xg_proxy_5",
    # ── Referee tendencies ───────────────────────────────────────────
    "ref_avg_goals", "ref_avg_cards",
    # ── Venue-split form ─────────────────────────────────────────────
    "home_venue_win_rate_5", "home_venue_goals_avg_5", "home_venue_conceded_avg_5",
    "away_venue_win_rate_5", "away_venue_goals_avg_5", "away_venue_conceded_avg_5",
    # ── Dixon-Coles Poisson model outputs ────────────────────────────
    "dc_home_win", "dc_draw", "dc_away_win",
    "dc_over_2_5", "dc_btts_yes",
    "dc_exp_home_goals", "dc_exp_away_goals",
    # ── Deep sport-agnostic scoring features ─────────────────────────
    # These work for ALL sports: basketball pts, baseball runs, hockey goals etc.
    # Values are in the sport's native unit (pts/goals/runs) — model learns the scale.
    "home_score_avg_10",          # avg score per game, last 10
    "away_score_avg_10",
    "home_score_allowed_avg_10",  # avg score conceded per game, last 10
    "away_score_allowed_avg_10",
    "home_score_diff_avg_10",     # avg point/goal/run differential (SRS-style)
    "away_score_diff_avg_10",
    "home_pythag",                # Pythagorean win% — luck-adjusted strength
    "away_pythag",
    "pythag_diff",                # home_pythag - away_pythag
    "pace_home",                  # avg total score/game in home team's games (pace)
    "pace_away",
    "pace_diff",                  # pace_home - pace_away
    "home_consistency",           # 1/std_dev of scores (high = more consistent)
    "away_consistency",
    "back_to_back_home",          # 1 if ≤1 day rest (B2B in basketball/hockey)
    "back_to_back_away",
    "home_cover_rate",            # how often home team wins by >spread (ATS)
    "away_cover_rate",
    "home_score_trend",           # slope of scoring in last 10 games (momentum)
    "away_score_trend",
    "home_recent_form_score",     # ELO-weighted win rate last 5 (generalised form)
    "away_recent_form_score",
    # ── Tier 1 model outputs ──────────────────────────────────────────────
    # Sport-specific mathematical priors — passed to Tier 2 ML as features.
    "t1_home_win_prob",           # score-diff sigmoid win prob (all sports)
    # ── Tennis surface ELO ────────────────────────────────────────────────
    "surface_elo_diff",           # home surface ELO minus away (0 for non-tennis)
    "surface_h_elo",              # home player's surface-specific ELO
    "surface_a_elo",              # away player's surface-specific ELO
    "surface_h_prob",             # surface ELO win probability for home
    # ── Cricket format encoding ───────────────────────────────────────────
    "format_t20",                 # 1 if T20 format, else 0
    "format_odi",                 # 1 if ODI format, else 0
    # format_test implied by both being 0
]

# Mapping: competition name → ESPN league slug (for historical standings lookup)
_COMP_NAME_TO_SLUG: dict[str, str] = {
    "premier league":                    "eng.1",
    "la liga":                           "esp.1",
    "bundesliga":                        "ger.1",
    "serie a":                           "ita.1",
    "ligue 1":                           "fra.1",
    "primeira liga":                     "por.1",
    "eredivisie":                        "ned.1",
    "süper lig":                         "tur.1",
    "super lig":                         "tur.1",
    "scottish premiership":              "sco.1",
    "pro league":                        "bel.1",
    "mls":                               "usa.1",
    "brasileirão":                       "bra.1",
    "serie a brasileira":                "bra.1",
    "liga profesional":                  "arg.1",
    "champions league":                  "uefa.champions",
    "uefa champions league":             "uefa.champions",
    "europa league":                     "uefa.europa",
    "uefa europa league":                "uefa.europa",
    "conference league":                 "uefa.europa.conf",
    "uefa europa conference league":     "uefa.europa.conf",
}

# Mapping: API-Football league ID string → ESPN league slug
_AF_ID_TO_SLUG: dict[str, str] = {
    "39": "eng.1",   "140": "esp.1",  "78": "ger.1",   "135": "ita.1",
    "61": "fra.1",   "94":  "por.1",  "88": "ned.1",   "203": "tur.1",
    "179": "sco.1",  "144": "bel.1",  "253": "usa.1",  "71":  "bra.1",
    "128": "arg.1",  "239": "col.1",
    "2": "uefa.champions", "3": "uefa.europa", "848": "uefa.europa.conf",
}

# Dixon-Coles model cache — one instance per sport, fitted once per training session
_dc_models: dict = {}

# Sports for which Poisson / Dixon-Coles is an appropriate scoring model.
# (Football and ice_hockey have Poisson-distributed low-count scores.)
_POISSON_SPORTS = {"football", "ice_hockey"}


def get_dc_model(db, sport_key: str = "football"):
    """Return a cached fitted DixonColes model for the given sport."""
    global _dc_models
    if sport_key not in _dc_models or not _dc_models[sport_key].is_fitted():
        try:
            from features.poisson import build_dc_model_from_db
            _dc_models[sport_key] = build_dc_model_from_db(db, sport_key)
        except Exception as e:
            logger.warning(f"[Engineering] Dixon-Coles build failed for {sport_key}: {e}")
            from features.poisson import DixonColes
            _dc_models[sport_key] = DixonColes()
    return _dc_models[sport_key]


def _build_team_index(df: pd.DataFrame) -> tuple[dict, dict]:
    """
    Pre-group the match DataFrame by team ID (and by H2H pair) for fast form lookups.
    Call once before the training loop; pass the returned indexes to the _*_fast() helpers.

    Entry format (tuple indices):
      _DATE=0  _HID=1  _AID=2  _HS=3   _AS=4   _RES=5
      _HSHOTS=6  _ASHOTS=7  _HSOT=8  _ASOT=9  _HXG=10  _AXG=11

    Returns:
        team_idx: team_id  → sorted list of entries (most-recent first, result not-null)
        h2h_idx:  frozenset({hid, aid}) → sorted list of entries (most-recent first)
    """
    from collections import defaultdict
    team_idx: dict = defaultdict(list)
    h2h_idx:  dict = defaultdict(list)

    def _f(v):
        return float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else None

    for _, r in df.iterrows():
        hid = int(r.home_id); aid = int(r.away_id)
        hs  = float(r.home_score or 0); as_ = float(r.away_score or 0)
        entry = (
            r.match_date, hid, aid, hs, as_, r.result,
            _f(r.get("home_shots")), _f(r.get("away_shots")),
            _f(r.get("home_sot")),   _f(r.get("away_sot")),
            _f(r.get("home_xg")),    _f(r.get("away_xg")),
        )
        if pd.notna(r.result):
            team_idx[hid].append(entry)
            team_idx[aid].append(entry)
        # H2H includes all finished matches regardless of which team was home
        if pd.notna(r.result):
            key = frozenset({hid, aid})
            h2h_idx[key].append(entry)

    for tid in team_idx:
        team_idx[tid].sort(key=lambda x: x[0], reverse=True)
    for key in h2h_idx:
        h2h_idx[key].sort(key=lambda x: x[0], reverse=True)

    return dict(team_idx), dict(h2h_idx)


# Entry field indices (for readability in fast functions)
_DATE = 0; _HID = 1; _AID = 2; _HS = 3; _AS = 4; _RES = 5
_HSHOTS = 6; _ASHOTS = 7; _HSOT = 8; _ASOT = 9; _HXG = 10; _AXG = 11


def _filter_before(entries: list, before: datetime, n: int) -> list:
    """Return up to n entries whose date < before (entries sorted most-recent-first)."""
    return [e for e in entries if e[_DATE] < before][:n]


def _form_fast(team_idx: dict, pid: int, before: datetime, n: int) -> dict:
    """
    Fast form lookup — O(k) vs O(N) for _form().
    Equivalent to _form() but uses pre-built team index.
    """
    filtered = _filter_before(team_idx.get(pid, []), before, n)
    if not filtered:
        return {"win": 0.33, "draw": 0.33, "gf": 1.2, "ga": 1.2, "btts": 0.5, "over25": 0.5}

    w = d = gf = ga = btts = over25 = 0
    for e in filtered:
        is_home = e[_HID] == pid
        sc = e[_HS] if is_home else e[_AS]
        co = e[_AS] if is_home else e[_HS]
        gf += sc; ga += co
        if sc > co: w += 1
        elif sc == co: d += 1
        if sc > 0 and co > 0: btts += 1
        if sc + co > 2: over25 += 1

    t = len(filtered)
    return {"win": w/t, "draw": d/t, "gf": gf/t, "ga": ga/t, "btts": btts/t, "over25": over25/t}


def _venue_form_fast(team_idx: dict, pid: int, before: datetime, n: int, as_home: bool) -> dict:
    """Fast O(k) venue-specific form — equivalent to _venue_form()."""
    all_entries = team_idx.get(pid, [])
    entries = [e for e in all_entries if e[_DATE] < before and
               (e[_HID] == pid if as_home else e[_AID] == pid)][:n]
    if not entries:
        return {"win": 0.33, "gf": 1.2, "ga": 1.2}

    w = gf = ga = 0
    for e in entries:
        sc = e[_HS] if as_home else e[_AS]
        co = e[_AS] if as_home else e[_HS]
        gf += sc; ga += co
        if sc > co: w += 1

    t = len(entries)
    return {"win": w/t, "gf": gf/t, "ga": ga/t}


def _h2h_fast(h2h_idx: dict, hid: int, aid: int, before: datetime, n: int = 10) -> dict:
    """Fast O(k) H2H lookup — equivalent to _h2h()."""
    key = frozenset({hid, aid})
    filtered = _filter_before(h2h_idx.get(key, []), before, n)
    if not filtered:
        return {"hw": 0.33, "d": 0.33, "aw": 0.33, "goals": 2.65, "n": 0}

    hw = d = aw = goals = 0
    for e in filtered:
        hs = e[_HS]; as_ = e[_AS]
        goals += hs + as_
        if hs > as_: hw += 1
        elif hs == as_: d += 1
        else: aw += 1

    t = len(filtered)
    return {"hw": hw/t, "d": d/t, "aw": aw/t, "goals": goals/t, "n": t}


def _strength_fast(team_idx: dict, pid: int, before: datetime, lg_avg: float) -> dict:
    """Fast O(k) attack/defence strength — equivalent to _strength()."""
    entries = [e for e in team_idx.get(pid, []) if e[_DATE] < before]
    if not entries:
        return {"atk": 1.0, "def": 1.0}

    gf = ga = 0
    for e in entries:
        is_home = e[_HID] == pid
        gf += e[_HS] if is_home else e[_AS]
        ga += e[_AS] if is_home else e[_HS]

    cnt = len(entries)
    return {"atk": (gf / cnt) / (lg_avg or 1.3), "def": (ga / cnt) / (lg_avg or 1.3)}


def _league_stats_fast(team_idx: dict, pid: int, before: datetime) -> dict:
    """Fast O(k) league stats — equivalent to _league_stats()."""
    all_before = [e for e in team_idx.get(pid, []) if e[_DATE] < before]
    if not all_before:
        return {"pts_rate": 1.0, "gd_per_game": 0.0, "form_pts": 5.0}

    pts = gd = form_pts = 0
    for i, e in enumerate(all_before):  # already sorted most-recent-first
        is_home = e[_HID] == pid
        sc = e[_HS] if is_home else e[_AS]
        co = e[_AS] if is_home else e[_HS]
        gd += sc - co
        p = 3 if sc > co else (1 if sc == co else 0)
        pts += p
        if i < 5:
            form_pts += p

    t = len(all_before)
    return {"pts_rate": pts / t, "gd_per_game": gd / t, "form_pts": float(form_pts)}


def _days_rest_fast(team_idx: dict, pid: int, before: datetime) -> float:
    """Fast O(k) days-rest — equivalent to _days_rest()."""
    # Include non-finished matches too (injury list differs, but rest still counts)
    # team_idx only has finished matches; use it as best approximation
    entries = team_idx.get(pid, [])
    before_entries = [e for e in entries if e[_DATE] < before]
    if not before_entries:
        return 7.0
    last_date = before_entries[0][_DATE]  # sorted most-recent-first
    return min((before - last_date).days, 30)


def _shots_form_fast(team_idx: dict, pid: int, before: datetime, n: int) -> dict:
    """Fast O(k) shot-based form — equivalent to _shots_form()."""
    filtered = _filter_before(team_idx.get(pid, []), before, n)
    if not filtered:
        return {"shots": 11.0, "sot": 4.5, "conv": 0.33, "xg": 1.3}

    shots_total = sot_total = goals_total = xg_total = 0.0
    games_with_shots = games_with_xg = 0
    for e in filtered:
        is_home = e[_HID] == pid
        sh  = e[_HSHOTS] if is_home else e[_ASHOTS]
        sot = e[_HSOT]   if is_home else e[_ASOT]
        xg  = e[_HXG]    if is_home else e[_AXG]
        gf  = e[_HS]     if is_home else e[_AS]
        goals_total += gf
        if sh is not None:
            shots_total += sh; games_with_shots += 1
        if sot is not None:
            sot_total += sot
        if xg is not None:
            xg_total += xg; games_with_xg += 1

    t = len(filtered)
    if games_with_shots < 2:
        avg_gf = goals_total / t
        xg = xg_total / games_with_xg if games_with_xg >= 2 else avg_gf
        return {"shots": avg_gf / 0.12, "sot": avg_gf / 0.35, "conv": 0.35, "xg": xg}

    avg_shots = shots_total / games_with_shots
    avg_sot   = sot_total   / games_with_shots
    avg_gf    = goals_total / t
    conv      = avg_gf / (avg_sot + 0.5)
    xg_proxy  = xg_total / games_with_xg if games_with_xg >= 3 else avg_sot * 0.33
    return {"shots": avg_shots, "sot": avg_sot, "conv": conv, "xg": xg_proxy}


def _score_form_generic_fast(
    team_idx: dict,
    pid: int,
    before: datetime,
    n: int,
    avg_side: float,
    typical_spread: float,
) -> dict:
    """Fast O(k) generic scoring form — equivalent to _score_form_generic()."""
    filtered = _filter_before(team_idx.get(pid, []), before, n)
    if not filtered:
        return {
            "scored": avg_side, "conceded": avg_side,
            "diff": 0.0, "pace": avg_side * 2.0,
            "consistency": 0.5, "cover_rate": 0.5,
            "trend": 0.0, "form_score": 0.5,
        }

    scores, conceded_list, pace_list = [], [], []
    covers = 0
    for e in filtered:
        is_home = e[_HID] == pid
        sc  = e[_HS] if is_home else e[_AS]
        co  = e[_AS] if is_home else e[_HS]
        scores.append(sc); conceded_list.append(co); pace_list.append(sc + co)
        if (sc - co) > (typical_spread * 0.5):
            covers += 1

    t = len(filtered)
    avg_scored   = float(np.mean(scores))
    avg_conceded = float(np.mean(conceded_list))

    if len(scores) >= 3:
        x = np.arange(len(scores))
        trend = float(np.polyfit(x, list(reversed(scores)), 1)[0])
    else:
        trend = 0.0

    std = float(np.std(scores)) if len(scores) > 1 else (avg_side * 0.3)
    consistency = 1.0 / (1.0 + std / max(avg_side, 0.1))

    decay = [0.8 ** i for i in range(t)]
    total_w = sum(decay)
    form_score = sum(
        (1.0 if scores[i] > conceded_list[i] else
         (0.5 if scores[i] == conceded_list[i] else 0.0)) * decay[i]
        for i in range(t)
    ) / (total_w + 1e-9)

    return {
        "scored":      avg_scored,
        "conceded":    avg_conceded,
        "diff":        avg_scored - avg_conceded,
        "pace":        float(np.mean(pace_list)),
        "consistency": min(1.0, consistency),
        "cover_rate":  covers / t,
        "trend":       trend,
        "form_score":  form_score,
    }


def _form(df: pd.DataFrame, pid: int, before: datetime, n: int) -> dict:
    team_df = df[
        ((df.home_id == pid) | (df.away_id == pid)) &
        (df.match_date < before) & df.result.notna()
    ].sort_values("match_date", ascending=False).head(n)

    if team_df.empty:
        return {"win": 0.33, "draw": 0.33, "gf": 1.2, "ga": 1.2, "btts": 0.5, "over25": 0.5}

    w = d = l = gf = ga = btts = over25 = 0
    for _, r in team_df.iterrows():
        is_home = r.home_id == pid
        scored = r.home_score if is_home else r.away_score
        conceded = r.away_score if is_home else r.home_score
        gf += scored; ga += conceded
        if scored > conceded: w += 1
        elif scored == conceded: d += 1
        else: l += 1
        if scored > 0 and conceded > 0: btts += 1
        if scored + conceded > 2: over25 += 1

    t = len(team_df)
    return {"win": w/t, "draw": d/t, "gf": gf/t, "ga": ga/t, "btts": btts/t, "over25": over25/t}


def _venue_form(df: pd.DataFrame, pid: int, before: datetime, n: int, as_home: bool) -> dict:
    """
    Form restricted to a specific venue role.
    as_home=True  → only matches where pid was the home team.
    as_home=False → only matches where pid was the away team.
    """
    if as_home:
        team_df = df[(df.home_id == pid) & (df.match_date < before) & df.result.notna()]
    else:
        team_df = df[(df.away_id == pid) & (df.match_date < before) & df.result.notna()]

    team_df = team_df.sort_values("match_date", ascending=False).head(n)

    if team_df.empty:
        return {"win": 0.33, "gf": 1.2, "ga": 1.2}

    w = gf = ga = 0
    for _, r in team_df.iterrows():
        scored   = r.home_score if as_home else r.away_score
        conceded = r.away_score if as_home else r.home_score
        gf += scored
        ga += conceded
        if scored > conceded:
            w += 1

    t = len(team_df)
    return {"win": w / t, "gf": gf / t, "ga": ga / t}


def _h2h(df: pd.DataFrame, hid: int, aid: int, before: datetime, n: int = 10) -> dict:
    h2h_df = df[
        (((df.home_id == hid) & (df.away_id == aid)) | ((df.home_id == aid) & (df.away_id == hid))) &
        (df.match_date < before) & df.result.notna()
    ].sort_values("match_date", ascending=False).head(n)

    if h2h_df.empty:
        return {"hw": 0.33, "d": 0.33, "aw": 0.33, "goals": 2.5, "n": 0}

    hw = d = aw = goals = 0
    for _, r in h2h_df.iterrows():
        hs, as_ = r.home_score, r.away_score
        goals += hs + as_
        if r.home_id == hid:
            if hs > as_: hw += 1
            elif hs == as_: d += 1
            else: aw += 1
        else:
            if as_ > hs: hw += 1
            elif hs == as_: d += 1
            else: aw += 1
    t = len(h2h_df)
    return {"hw": hw/t, "d": d/t, "aw": aw/t, "goals": goals/t, "n": t}


def _strength(df: pd.DataFrame, pid: int, before: datetime) -> dict:
    lg_avg = df[df.result.notna()]["home_score"].mean() or 1.3
    hm = df[(df.home_id == pid) & (df.match_date < before) & df.result.notna()]
    am = df[(df.away_id == pid) & (df.match_date < before) & df.result.notna()]
    gf = hm["home_score"].sum() + am["away_score"].sum()
    ga = hm["away_score"].sum() + am["home_score"].sum()
    cnt = len(hm) + len(am) or 1
    return {"atk": (gf / cnt) / lg_avg, "def": (ga / cnt) / lg_avg}


def _odds_features(db: Session, match_id: int) -> dict:
    from data.db_models.models import MatchOdds
    rows = db.query(MatchOdds).filter_by(match_id=match_id, market="h2h").all()
    if not rows:
        return {"imp_h": 0, "imp_d": 0, "imp_a": 0, "margin": 0}
    best = {}
    for r in rows:
        if best.get(r.outcome, 0) < r.price:
            best[r.outcome] = r.price
    h_imp = 1/best.get("home", 3.0)
    d_imp = 1/best.get("draw", 3.5)
    a_imp = 1/best.get("away", 3.0)
    total = h_imp + d_imp + a_imp
    return {"imp_h": h_imp/total, "imp_d": d_imp/total, "imp_a": a_imp/total, "margin": total-1}


def _injury_impact(db: Session, team_id: int, before: datetime, window_days: int = 14) -> float:
    """
    Sum of recent injury/suspension signal impacts for a team.
    Returns a value in [-3.0, 0.0]: negative means team is weakened.
    Only uses signals from the last `window_days` days before the match.
    Returns 0.0 if no signals found (no impact known).
    """
    if not team_id:
        return 0.0
    try:
        from data.db_models.models import IntelligenceSignal
        cutoff = before - timedelta(days=window_days)
        sigs = (
            db.query(IntelligenceSignal)
            .filter(
                IntelligenceSignal.team_id == team_id,
                IntelligenceSignal.signal_type.in_(["injury", "suspension"]),
                IntelligenceSignal.created_at >= cutoff,
                IntelligenceSignal.created_at < before,
            )
            .all()
        )
        if not sigs:
            return 0.0
        # Sum negative impacts, capped at -3.0 (3 key players out)
        total = sum(min(0.0, s.impact_score) * s.confidence for s in sigs)
        return max(-3.0, total)
    except Exception:
        return 0.0


def _league_stats(df: pd.DataFrame, pid: int, before: datetime) -> dict:
    """Points rate, GD per game, and form points (last 5 games) from match history."""
    team_df = df[
        ((df.home_id == pid) | (df.away_id == pid)) &
        (df.match_date < before) & df.result.notna()
    ].sort_values("match_date", ascending=False)

    if team_df.empty:
        return {"pts_rate": 1.0, "gd_per_game": 0.0, "form_pts": 5.0}

    pts = gd = form_pts = 0
    for i, (_, r) in enumerate(team_df.iterrows()):
        is_home = r.home_id == pid
        scored = r.home_score if is_home else r.away_score
        conceded = r.away_score if is_home else r.home_score
        gd += scored - conceded
        p = 3 if scored > conceded else (1 if scored == conceded else 0)
        pts += p
        if i < 5:
            form_pts += p

    t = len(team_df)
    return {"pts_rate": pts / t, "gd_per_game": gd / t, "form_pts": float(form_pts)}


def _days_rest(df: pd.DataFrame, pid: int, before: datetime) -> float:
    last = df[
        ((df.home_id == pid) | (df.away_id == pid)) & (df.match_date < before)
    ].sort_values("match_date", ascending=False).head(1)
    if last.empty: return 7.0
    return min((before - last.iloc[0].match_date).days, 30)


def _score_form_generic(
    df: pd.DataFrame,
    pid: int,
    before: datetime,
    n: int,
    avg_side: float,
    typical_spread: float,
) -> dict:
    """
    Scale-agnostic scoring form over last N games.
    Works for any sport: basketball (107 pts), baseball (4.7 runs),
    hockey (3.1 goals), football (1.4 goals), NFL (22 pts), etc.
    Values returned are in the sport's native unit — the model learns the scale.
    """
    team_df = df[
        ((df.home_id == pid) | (df.away_id == pid)) &
        (df.match_date < before) & df.result.notna()
    ].sort_values("match_date", ascending=False).head(n)

    if team_df.empty:
        return {
            "scored": avg_side, "conceded": avg_side,
            "diff": 0.0, "pace": avg_side * 2.0,
            "consistency": 0.5, "cover_rate": 0.5,
            "trend": 0.0, "form_score": 0.5,
        }

    scores, conceded_list, pace_list = [], [], []
    wins = covers = 0

    for _, r in team_df.iterrows():
        is_home = r.home_id == pid
        sc  = float(r.home_score if is_home else r.away_score)
        con = float(r.away_score if is_home else r.home_score)
        scores.append(sc)
        conceded_list.append(con)
        pace_list.append(sc + con)
        if sc > con:
            wins += 1
        # Cover: won by more than half the typical spread
        if (sc - con) > (typical_spread * 0.5):
            covers += 1

    t = len(team_df)
    avg_scored   = float(np.mean(scores))
    avg_conceded = float(np.mean(conceded_list))

    # Scoring trend: positive = improving in recent games
    # scores[0] is most recent; reverse list so regression slope is +ve for improving
    if len(scores) >= 3:
        x = np.arange(len(scores))
        trend = float(np.polyfit(x, list(reversed(scores)), 1)[0])
    else:
        trend = 0.0

    # Consistency: 1/(1 + normalised_std) — higher = more predictable
    std = float(np.std(scores)) if len(scores) > 1 else (avg_side * 0.3)
    consistency = 1.0 / (1.0 + std / max(avg_side, 0.1))

    # Recency-weighted form score (decay 0.8^i, most recent game has highest weight)
    decay = [0.8 ** i for i in range(t)]
    total_w = sum(decay)
    form_score = sum(
        (1.0 if scores[i] > conceded_list[i] else
         (0.5 if scores[i] == conceded_list[i] else 0.0)) * decay[i]
        for i in range(t)
    ) / (total_w + 1e-9)

    return {
        "scored":      avg_scored,
        "conceded":    avg_conceded,
        "diff":        avg_scored - avg_conceded,
        "pace":        float(np.mean(pace_list)),
        "consistency": min(1.0, consistency),
        "cover_rate":  covers / t,
        "trend":       trend,
        "form_score":  form_score,
    }


def _parse_extra(extra_str) -> dict:
    """Parse extra_data JSON blob from a Match row."""
    if not extra_str:
        return {}
    try:
        return json.loads(extra_str)
    except Exception:
        return {}


def _shots_form(df: pd.DataFrame, pid: int, before: datetime, n: int) -> dict:
    """
    Compute shot-based form over last n games.
    Returns avg shots, avg shots-on-target, shot conversion, xG proxy.
    Falls back to league averages when data is sparse.
    """
    team_df = df[
        ((df.home_id == pid) | (df.away_id == pid)) &
        (df.match_date < before) & df.result.notna()
    ].sort_values("match_date", ascending=False).head(n)

    if team_df.empty:
        return {"shots": 11.0, "sot": 4.5, "conv": 0.33, "xg": 1.3}

    shots_total = sot_total = goals_total = games_with_shots = 0
    for _, r in team_df.iterrows():
        is_home = r.home_id == pid
        if is_home:
            sh  = r.get("home_shots", None)
            sot = r.get("home_sot", None)
            gf  = r.home_score
        else:
            sh  = r.get("away_shots", None)
            sot = r.get("away_sot", None)
            gf  = r.away_score

        if sh is not None and not pd.isna(sh):
            shots_total += sh
            games_with_shots += 1
        if sot is not None and not pd.isna(sot):
            sot_total += sot
        goals_total += gf

    t = len(team_df)
    # Also sum real xG from API-Football backfill when available
    real_xg_total = 0.0
    games_with_xg = 0
    for _, r in team_df.iterrows():
        is_home = r.home_id == pid
        xg_key  = "home_xg" if is_home else "away_xg"
        xg_val  = r.get(xg_key, None)
        if xg_val is not None and not pd.isna(xg_val):
            real_xg_total += float(xg_val)
            games_with_xg += 1

    if games_with_shots < 2:
        # Not enough shot data — use goals-based proxy
        avg_gf = goals_total / t
        xg = real_xg_total / games_with_xg if games_with_xg >= 2 else avg_gf
        return {
            "shots": avg_gf / 0.12,
            "sot":   avg_gf / 0.35,
            "conv":  0.35,
            "xg":    xg,
        }

    avg_shots = shots_total / games_with_shots
    avg_sot   = sot_total   / games_with_shots
    avg_gf    = goals_total / t
    conv      = avg_gf / (avg_sot + 0.5)      # goals per shot on target

    # Prefer real xG when we have enough; fall back to sot-proxy
    if games_with_xg >= 3:
        xg_proxy = real_xg_total / games_with_xg
    else:
        xg_proxy = avg_sot * 0.33              # industry avg: ~33% sot → goal

    return {"shots": avg_shots, "sot": avg_sot, "conv": conv, "xg": xg_proxy}


def _referee_stats(df: pd.DataFrame, referee: str | None, before: datetime) -> dict:
    """
    Historical tendencies for a specific referee (goals/game, cards/game).
    Falls back to league averages when fewer than 5 games found.
    """
    default = {"avg_goals": 2.65, "avg_cards": 4.2}

    if not referee or "referee" not in df.columns:
        return default

    ref_df = df[
        (df["referee"] == referee) &
        (df.match_date < before) &
        df.result.notna()
    ]
    if len(ref_df) < 5:
        return default

    avg_goals = (ref_df.home_score + ref_df.away_score).mean()

    cards_cols_present = [c for c in ("home_yellow", "away_yellow", "home_red", "away_red") if c in df.columns]
    if cards_cols_present:
        avg_cards = ref_df[cards_cols_present].sum(axis=1).mean()
    else:
        avg_cards = default["avg_cards"]

    return {
        "avg_goals": float(avg_goals) if not pd.isna(avg_goals) else default["avg_goals"],
        "avg_cards": float(avg_cards) if not pd.isna(avg_cards) else default["avg_cards"],
    }


def _get_league_slug_for_comp(db: Session, competition_id: int) -> str | None:
    """Map a Competition row to an ESPN league slug for standings lookup."""
    from data.db_models.models import Competition
    comp = db.query(Competition).filter_by(id=competition_id).first()
    if not comp:
        return None
    # Try external_id (API-Football numeric ID stored as string)
    slug = _AF_ID_TO_SLUG.get(str(comp.external_id or ""))
    if slug:
        return slug
    # Try competition name
    name_lower = (comp.name or "").lower()
    for key, s in _COMP_NAME_TO_SLUG.items():
        if key in name_lower or name_lower in key:
            return s
    return None


def _prev_season_rank(db: Session, team_name: str, competition_id: int, match_date: datetime) -> float:
    """
    Return this team's end-of-previous-season league rank from LeagueSeasonCache.
    Scale: 1.0 = champion last season, 0.5 = midtable / unknown, 0.0 = bottom.

    European seasons span Aug–Jun: a match on 2024-10-05 belongs to season 2024,
    so we look at season 2023 standings.  South American/MLS seasons are calendar-year
    but the same heuristic (month >= 7 → current year's season) is close enough.
    """
    try:
        import json as _json
        from data.db_models.models import LeagueSeasonCache

        league_slug = _get_league_slug_for_comp(db, competition_id)
        if not league_slug:
            return 0.5

        # Determine which ESPN season this match falls in, then subtract 1
        season_year = match_date.year if match_date.month >= 7 else match_date.year - 1
        prev_season = season_year - 1

        row = (
            db.query(LeagueSeasonCache)
            .filter_by(league_slug=league_slug, season=prev_season, data_type="standings")
            .first()
        )
        if not row:
            return 0.5

        data   = _json.loads(row.json_data)
        groups = data.get("groups", [])
        if not groups:
            return 0.5

        # Flatten all groups and find the team by name (partial match)
        all_entries = [e for g in groups for e in g]
        total       = max(len(all_entries), 1)
        team_lower  = (team_name or "").lower()

        for entry in all_entries:
            ename = (entry.get("team_name") or "").lower()
            if ename and (ename == team_lower or team_lower in ename or ename in team_lower):
                rank = int(entry.get("rank") or total)
                # rank 1 → 1.0, rank total → ~0.0
                return round(1.0 - (rank - 1) / total, 4)

    except Exception:
        pass
    return 0.5


def build_row(
    db: Session,
    match: Match,
    df: pd.DataFrame,
    sport_key: str = "football",
    team_idx: dict | None = None,
    h2h_idx: dict | None = None,
    lg_avg: float | None = None,
    surface_elo_snapshot: dict | None = None,
    competition_name: str | None = None,
    elo_snapshot: dict | None = None,
) -> dict:
    """
    Build a single feature row for a match.

    Extra kwargs (Tier 1):
      elo_snapshot         : pre-match ELO state dict from EloTracker
                             (pass during training to avoid DB ELO leakage;
                             omit for inference where we use current DB ELO)
      surface_elo_snapshot : pre-match surface ELO state dict from SurfaceEloTracker
                             (only meaningful for tennis; pass None for other sports)
      competition_name     : competition name string for surface/format detection

    team_idx / h2h_idx: pre-built indexes from _build_team_index().
      When provided, all form lookups run in O(k) instead of O(N), giving a
      ~25–50× speedup during bulk training-matrix construction.
      When omitted (inference, scheduler) the original slow-but-correct
      pandas-scan functions are used — no behaviour change.
    """
    hid, aid = match.home_id, match.away_id
    date = match.match_date
    # Use historically-correct ELO from on-the-fly tracker (training),
    # falling back to current DB ELO for inference.
    if elo_snapshot:
        h_elo = float(elo_snapshot.get("home_elo", match.home.elo_rating if match.home else 1500.0))
        a_elo = float(elo_snapshot.get("away_elo", match.away.elo_rating if match.away else 1500.0))
    else:
        h_elo = match.home.elo_rating if match.home else 1500.0
        a_elo = match.away.elo_rating if match.away else 1500.0

    profile  = get_profile(sport_key)
    has_draw = not _sport_is_binary(sport_key)
    elo_p = win_probabilities(h_elo, a_elo, has_draw)

    # ── Form lookups — fast (O(k)) when index available, slow (O(N)) otherwise ─
    if team_idx is not None:
        hf5  = _form_fast(team_idx, hid, date, 5)
        hf10 = _form_fast(team_idx, hid, date, 10)
        af5  = _form_fast(team_idx, aid, date, 5)
        af10 = _form_fast(team_idx, aid, date, 10)
        hvf  = _venue_form_fast(team_idx, hid, date, 5, as_home=True)
        avf  = _venue_form_fast(team_idx, aid, date, 5, as_home=False)
        h2h  = _h2h_fast(h2h_idx or {}, hid, aid, date) if h2h_idx is not None else _h2h(df, hid, aid, date)
        _lg_avg = lg_avg or 1.3
        hs   = _strength_fast(team_idx, hid, date, _lg_avg)
        as_s = _strength_fast(team_idx, aid, date, _lg_avg)
        hls  = _league_stats_fast(team_idx, hid, date)
        als  = _league_stats_fast(team_idx, aid, date)
        hsf  = _shots_form_fast(team_idx, hid, date, 5)
        asf  = _shots_form_fast(team_idx, aid, date, 5)
        hsf10 = _score_form_generic_fast(team_idx, hid, date, 10, profile.avg_side, profile.typical_spread)
        asf10 = _score_form_generic_fast(team_idx, aid, date, 10, profile.avg_side, profile.typical_spread)
        h_rest = _days_rest_fast(team_idx, hid, date)
        a_rest = _days_rest_fast(team_idx, aid, date)
    else:
        hf5  = _form(df, hid, date, 5)
        hf10 = _form(df, hid, date, 10)
        af5  = _form(df, aid, date, 5)
        af10 = _form(df, aid, date, 10)
        hvf  = _venue_form(df, hid, date, 5, as_home=True)
        avf  = _venue_form(df, aid, date, 5, as_home=False)
        h2h  = _h2h(df, hid, aid, date)
        hs   = _strength(df, hid, date)
        as_s = _strength(df, aid, date)
        hls  = _league_stats(df, hid, date)
        als  = _league_stats(df, aid, date)
        hsf  = _shots_form(df, hid, date, 5)
        asf  = _shots_form(df, aid, date, 5)
        hsf10 = _score_form_generic(df, hid, date, 10, profile.avg_side, profile.typical_spread)
        asf10 = _score_form_generic(df, aid, date, 10, profile.avg_side, profile.typical_spread)
        h_rest = _days_rest(df, hid, date)
        a_rest = _days_rest(df, aid, date)
        _lg_avg = df[df.result.notna()]["home_score"].mean() or 1.3

    of   = _odds_features(db, match.id)

    # Referee features (no fast path — referee is rare & quick to look up)
    ref_name = _parse_extra(match.extra_data).get("ref") if match.extra_data else None
    ref_s = _referee_stats(df, ref_name, date)

    # Historical season rank (from league_season_cache)
    home_name   = match.home.name if match.home else ""
    away_name   = match.away.name if match.away else ""
    h_prev_rank = _prev_season_rank(db, home_name, match.competition_id, date)
    a_prev_rank = _prev_season_rank(db, away_name, match.competition_id, date)

    exp_h = max(0.2, hs["atk"] * as_s["def"] * _lg_avg)
    exp_a = max(0.2, as_s["atk"] * hs["def"] * _lg_avg * 0.88)

    # ── Dixon-Coles Poisson model (football + ice_hockey) ────────────────────
    # Only appropriate for low-count Poisson-distributed scoring.
    # For basketball/baseball/rugby/cricket etc. the DC model gives nonsense.
    _dc_fallback = {
        "home_win": elo_p.get("home", 0.4), "draw": elo_p.get("draw", 0.25),
        "away_win": elo_p.get("away", 0.35), "over_2.5": 0.5, "btts_yes": 0.5,
        "exp_home_goals": exp_h, "exp_away_goals": exp_a,
    }
    if sport_key in _POISSON_SPORTS:
        dc = get_dc_model(db, sport_key)
        try:
            dc_out = dc.predict(home_name, away_name)
        except Exception:
            dc_out = _dc_fallback
    else:
        dc_out = _dc_fallback

    # ── Tier 1: score-differential win probability ────────────────────────
    from features.tier1_models import score_diff_win_prob
    t1_home_win_prob = score_diff_win_prob(
        hsf10["diff"], asf10["diff"], profile.avg_side
    )

    # ── Tier 1: surface ELO features (tennis only) ────────────────────────
    if surface_elo_snapshot:
        _surf_diff  = float(surface_elo_snapshot.get("diff",   0.0))
        _surf_h_elo = float(surface_elo_snapshot.get("h_elo",  1500.0))
        _surf_a_elo = float(surface_elo_snapshot.get("a_elo",  1500.0))
        _surf_h_prob = float(surface_elo_snapshot.get("h_prob", 0.5))
    else:
        _surf_diff = _surf_h_elo = _surf_a_elo = 0.0
        _surf_h_prob = 0.5

    # ── Tier 1: cricket format encoding ───────────────────────────────────
    if sport_key == "cricket":
        from features.tier1_models import detect_cricket_format
        _comp_name = competition_name or (match.competition.name if match.competition else "")
        _fmt = detect_cricket_format(_comp_name)
        _fmt_t20 = int(_fmt == "t20")
        _fmt_odi = int(_fmt == "odi")
    else:
        _fmt_t20 = _fmt_odi = 0

    # ── Sport-agnostic deep scoring features ─────────────────────────────────
    h_pythag = pythagorean_win_pct(hsf10["scored"], hsf10["conceded"], profile.pythag_exp)
    a_pythag = pythagorean_win_pct(asf10["scored"], asf10["conceded"], profile.pythag_exp)

    return {
        "home_elo": h_elo, "away_elo": a_elo, "elo_diff": h_elo - a_elo,
        "elo_home_prob": elo_p.get("home", 0.4),
        "elo_draw_prob": elo_p.get("draw", 0.25),
        "elo_away_prob": elo_p.get("away", 0.35),
        "home_win_rate_5": hf5["win"], "home_win_rate_10": hf10["win"],
        "home_goals_avg_5": hf5["gf"], "home_goals_conceded_avg_5": hf5["ga"],
        "away_win_rate_5": af5["win"], "away_win_rate_10": af10["win"],
        "away_goals_avg_5": af5["gf"], "away_goals_conceded_avg_5": af5["ga"],
        "h2h_home_win_rate": h2h["hw"], "h2h_draw_rate": h2h["d"],
        "h2h_away_win_rate": h2h["aw"], "h2h_avg_goals": h2h["goals"], "h2h_n": h2h["n"],
        "home_attack_str": hs["atk"], "home_defence_str": hs["def"],
        "away_attack_str": as_s["atk"], "away_defence_str": as_s["def"],
        "exp_home_goals": exp_h, "exp_away_goals": exp_a, "exp_total_goals": exp_h + exp_a,
        "home_btts_rate": hf10["btts"], "away_btts_rate": af10["btts"],
        "home_over25_rate": hf10["over25"], "away_over25_rate": af10["over25"],
        "imp_home_prob": of["imp_h"], "imp_draw_prob": of["imp_d"], "imp_away_prob": of["imp_a"],
        "market_margin": of["margin"],
        "home_days_rest": h_rest,
        "away_days_rest": a_rest,
        "home_injury_impact": _injury_impact(db, hid, date),
        "away_injury_impact": _injury_impact(db, aid, date),
        "home_league_pts_rate": hls["pts_rate"],
        "away_league_pts_rate": als["pts_rate"],
        "home_league_gd_per_game": hls["gd_per_game"],
        "away_league_gd_per_game": als["gd_per_game"],
        "home_form_points": hls["form_pts"],
        "away_form_points": als["form_pts"],
        "pts_rate_diff": hls["pts_rate"] - als["pts_rate"],
        "form_points_diff": hls["form_pts"] - als["form_pts"],
        # ── Historical season rank (from league_season_cache) ─────────
        "home_prev_season_rank": h_prev_rank,
        "away_prev_season_rank": a_prev_rank,
        # ── Shot features ─────────────────────────────────────────────
        "home_shots_avg_5": hsf["shots"],
        "away_shots_avg_5": asf["shots"],
        "home_sot_avg_5":   hsf["sot"],
        "away_sot_avg_5":   asf["sot"],
        "home_shot_conv_5": hsf["conv"],
        "away_shot_conv_5": asf["conv"],
        "home_xg_proxy_5":  hsf["xg"],
        "away_xg_proxy_5":  asf["xg"],
        # ── Referee features ──────────────────────────────────────────
        "ref_avg_goals": ref_s["avg_goals"],
        "ref_avg_cards": ref_s["avg_cards"],
        # ── Venue-split form ──────────────────────────────────────────
        "home_venue_win_rate_5":    hvf["win"],
        "home_venue_goals_avg_5":   hvf["gf"],
        "home_venue_conceded_avg_5": hvf["ga"],
        "away_venue_win_rate_5":    avf["win"],
        "away_venue_goals_avg_5":   avf["gf"],
        "away_venue_conceded_avg_5": avf["ga"],
        # ── Dixon-Coles Poisson ───────────────────────────────────────
        "dc_home_win":       dc_out.get("home_win", elo_p.get("home", 0.4)),
        "dc_draw":           dc_out.get("draw", elo_p.get("draw", 0.25)),
        "dc_away_win":       dc_out.get("away_win", elo_p.get("away", 0.35)),
        "dc_over_2_5":       dc_out.get("over_2.5", 0.5),
        "dc_btts_yes":       dc_out.get("btts_yes", 0.5),
        "dc_exp_home_goals": dc_out.get("exp_home_goals", exp_h),
        "dc_exp_away_goals": dc_out.get("exp_away_goals", exp_a),
        # ── Deep sport-agnostic scoring features ─────────────────────
        "home_score_avg_10":         hsf10["scored"],
        "away_score_avg_10":         asf10["scored"],
        "home_score_allowed_avg_10": hsf10["conceded"],
        "away_score_allowed_avg_10": asf10["conceded"],
        "home_score_diff_avg_10":    hsf10["diff"],
        "away_score_diff_avg_10":    asf10["diff"],
        "home_pythag":               h_pythag,
        "away_pythag":               a_pythag,
        "pythag_diff":               h_pythag - a_pythag,
        "pace_home":                 hsf10["pace"],
        "pace_away":                 asf10["pace"],
        "pace_diff":                 hsf10["pace"] - asf10["pace"],
        "home_consistency":          hsf10["consistency"],
        "away_consistency":          asf10["consistency"],
        "back_to_back_home":         int(h_rest <= 1),
        "back_to_back_away":         int(a_rest <= 1),
        "home_cover_rate":           hsf10["cover_rate"],
        "away_cover_rate":           asf10["cover_rate"],
        "home_score_trend":          hsf10["trend"],
        "away_score_trend":          asf10["trend"],
        "home_recent_form_score":    hsf10["form_score"],
        "away_recent_form_score":    asf10["form_score"],
        # ── Tier 1 outputs ────────────────────────────────────────────────
        "t1_home_win_prob":     t1_home_win_prob,
        "surface_elo_diff":     _surf_diff,
        "surface_h_elo":        _surf_h_elo,
        "surface_a_elo":        _surf_a_elo,
        "surface_h_prob":       _surf_h_prob,
        "format_t20":           _fmt_t20,
        "format_odi":           _fmt_odi,
    }


def _swap_tennis_home_away(row: dict) -> dict:
    """
    For tennis: deterministically swap home↔away for half the training rows
    (odd match IDs).  Sofascore always places the WINNER as the home player,
    so without swapping 100% of labels are "H" — a single class the classifier
    cannot learn from.

    The swap mirrors every feature that distinguishes home from away:
      - home_* ↔ away_* named features
      - negates *_diff features
      - flips probability pairs (dc_home_win/dc_away_win, etc.)
      - flips result: H → A, A → H
    This produces a balanced, bias-free dataset while preserving all
    information content.
    """
    r = row.copy()

    # ── Swap matching home_* ↔ away_* pairs ──────────────────────────────
    home_keys = [k for k in r if k.startswith("home_")]
    for hk in home_keys:
        ak = "away_" + hk[5:]
        if ak in r:
            r[hk], r[ak] = row[ak], row[hk]

    # ── Swap other paired keys ────────────────────────────────────────────
    _pairs = [
        ("elo_home_prob",    "elo_away_prob"),
        ("imp_home_prob",    "imp_away_prob"),
        ("h2h_home_win_rate","h2h_away_win_rate"),
        ("dc_home_win",      "dc_away_win"),
        ("dc_exp_home_goals","dc_exp_away_goals"),
        ("exp_home_goals",   "exp_away_goals"),
        ("surface_h_elo",    "surface_a_elo"),
    ]
    for hk, ak in _pairs:
        if hk in r and ak in r:
            r[hk], r[ak] = row[ak], row[hk]

    # ── Negate scalar diffs ───────────────────────────────────────────────
    _diffs = [
        "elo_diff", "pythag_diff", "pace_diff",
        "pts_rate_diff", "form_points_diff",
        "surface_elo_diff",
    ]
    for dk in _diffs:
        if dk in r:
            r[dk] = -float(row[dk])

    # ── Flip calibrated win probs ─────────────────────────────────────────
    for fk, default in [("t1_home_win_prob", 0.5), ("surface_h_prob", 0.5)]:
        if fk in r:
            r[fk] = 1.0 - float(row.get(fk, default))

    # ── Flip result ───────────────────────────────────────────────────────
    res = row.get("result")
    if res == "H":
        r["result"] = "A"
    elif res == "A":
        r["result"] = "H"

    return r


def build_training_matrix(
    db: Session,
    sport_key: str,
    training_years: int = 2,       # hard cutoff: only train on last N years
) -> pd.DataFrame:
    """
    Build training matrix for the ML model.

    Key design decisions:
    - ALL historical matches are loaded into `df` for feature computation
      (H2H lookups, form context, ELO).  Historical depth improves features.
    - But only matches from the last `training_years` years become training rows.
      This prevents stale team identities from polluting the model.
      (Real Madrid 2010 != Real Madrid 2025.)
    - Within the training window, recency weights (3x/2x/1.5x) further
      prioritise the most recent form.
    - Train/test split is TIME-BASED (not random) to prevent data leakage.

    Tier 1 leakage guarantee:
    - Surface ELO tracker replays ALL matches chronologically; for each match
      it records the PRE-match surface ELO state, then updates AFTER.  This
      ensures the feature for match D only reflects matches before D.
    """
    global _dc_models
    _dc_models = {}   # Force fresh DC model fit each training run

    from data.db_models.models import Sport, Competition
    from sqlalchemy.orm import joinedload

    sport = db.query(Sport).filter_by(key=sport_key).first()
    if not sport:
        return pd.DataFrame()

    profile  = get_profile(sport_key)
    has_draw = not _sport_is_binary(sport_key)

    # Sport-specific totals line (None = no over/under market for this sport)
    _tot_lines = profile.totals_lines
    main_line: float | None = None
    if _tot_lines:
        # Use the middle line — roughly 50% hit rate → balanced classes
        main_line = _tot_lines[len(_tot_lines) // 2]

    # Load ALL finished matches for feature computation context
    all_matches = (
        db.query(Match)
        .join(Competition)
        .filter(Competition.sport_id == sport.id, Match.result.isnot(None))
        .options(joinedload(Match.home), joinedload(Match.away))
        .order_by(Match.match_date)
        .all()
    )

    if not all_matches:
        return pd.DataFrame()

    def _match_row(m: Match) -> dict:
        row = {
            "id": m.id, "home_id": m.home_id, "away_id": m.away_id,
            "match_date": pd.to_datetime(m.match_date),
            "home_score": m.home_score or 0, "away_score": m.away_score or 0,
            "result": m.result,
        }
        ex = _parse_extra(m.extra_data)
        row["home_shots"]  = ex.get("hs",  None)
        row["away_shots"]  = ex.get("as_", None)
        row["home_sot"]    = ex.get("hst", None)
        row["away_sot"]    = ex.get("ast", None)
        row["home_yellow"] = ex.get("hy",  None)
        row["away_yellow"] = ex.get("ay",  None)
        row["home_red"]    = ex.get("hr",  None)
        row["away_red"]    = ex.get("ar",  None)
        row["referee"]     = ex.get("ref", None)
        row["home_xg"]     = ex.get("home_xg", None)
        row["away_xg"]     = ex.get("away_xg", None)
        return row

    # Full context dataframe (all history) — used for feature computation only
    df = pd.DataFrame([_match_row(m) for m in all_matches])

    # Pre-build team index once — O(N log N) up-front, then O(k) per row
    # Reduces per-row form-lookup cost from ~200ms to ~5ms (25-50× speedup)
    team_idx, h2h_idx = _build_team_index(df)
    lg_avg = float(df[df.result.notna()]["home_score"].mean() or 1.3)

    now = datetime.utcnow()
    training_cutoff = now - timedelta(days=training_years * 365)

    # Only build training rows for matches within the training window
    training_matches = [
        m for m in all_matches[20:]   # skip first 20 (not enough form history)
        if m.match_date >= training_cutoff
    ]

    logger.info(
        f"[Training] {sport_key}: {len(all_matches)} total matches in DB, "
        f"{len(training_matches)} in training window (last {training_years} years)"
    )

    # ── Tier 1: ELO snapshots for ALL sports (leakage-safe) ──────────────────
    # Replay ALL matches chronologically; for each match record the PRE-match
    # ELO then update AFTER — guarantees no future data leaks.
    # This replaces the stale DB elo_rating column which reflects current
    # (post-all-matches) ELO, not the historical ELO at match time.
    from features.tier1_models import EloTracker
    elo_snapshots: dict[int, dict] = {}
    _elo_tracker = EloTracker(has_draw=has_draw)
    for m in all_matches:
        if not (m.home and m.away):
            continue
        elo_snapshots[m.id] = _elo_tracker.snapshot(m.home_id, m.away_id)
        if m.home_score is not None and m.away_score is not None:
            _elo_tracker.update(
                m.home_id, m.away_id,
                float(m.home_score), float(m.away_score),
                m.match_date,
            )

    # ── Tier 1: surface ELO snapshots for tennis (leakage-safe) ──────────────
    # Replay ALL matches chronologically; for each match record the PRE-match
    # surface ELO then update AFTER — guarantees no future data leaks into
    # the feature for any given training row.
    surface_elo_snapshots: dict[int, dict] = {}
    if sport_key == "tennis":
        from features.tier1_models import SurfaceEloTracker, detect_surface
        _surf_tracker = SurfaceEloTracker()
        for m in all_matches:
            if not (m.home and m.away):
                continue
            _comp = getattr(m, "competition", None)
            _cname = (_comp.name if _comp else "") or ""
            _surface = detect_surface(_cname)
            # Record PRE-match state — what the model sees at prediction time
            surface_elo_snapshots[m.id] = _surf_tracker.snapshot(
                m.home_id, m.away_id, _surface
            )
            # Update AFTER recording (strict causal order)
            if m.home_score is not None and m.away_score is not None:
                _surf_tracker.update(
                    m.home_id, m.away_id,
                    float(m.home_score), float(m.away_score),
                    _surface,
                )

    rows = []
    for m in training_matches:
        try:
            hs = m.home_score or 0
            as_ = m.away_score or 0

            _comp      = getattr(m, "competition", None)
            _comp_name = (_comp.name if _comp else "") or ""
            _surf_snap = surface_elo_snapshots.get(m.id, {})

            row = build_row(
                db, m, df, sport_key,
                team_idx=team_idx, h2h_idx=h2h_idx, lg_avg=lg_avg,
                surface_elo_snapshot=_surf_snap,
                competition_name=_comp_name,
                elo_snapshot=elo_snapshots.get(m.id),
            )
            row["result"] = m.result

            # ── Training labels — sport-specific ───────────────────────
            if sport_key == "football":
                # Football: full market set
                row["over15"]  = int(hs + as_ > 1.5)
                row["over25"]  = int(hs + as_ > 2.5)
                row["over35"]  = int(hs + as_ > 3.5)
                row["btts"]    = int(hs > 0 and as_ > 0)
                row["home_cs"] = int(as_ == 0)
                row["away_cs"] = int(hs == 0)
            else:
                # Other sports: over/under on sport's main totals line
                if main_line is not None:
                    row["over_main"] = int(hs + as_ > main_line)
                # BTTS makes sense for handball (medium scoring with 2 teams)
                if sport_key in ("handball",):
                    row["btts"] = int(hs > 0 and as_ > 0)

            # ── Tennis: home/away swap for balanced classes ────────────────
            # Sofascore places the winner as home_team in every tennis match,
            # so result is always "H" without this correction.
            # Deterministic by match ID (odd IDs get swapped) — reproducible.
            if sport_key == "tennis" and m.id % 2 == 0:
                row = _swap_tennis_home_away(row)

            # ── Recency weights (within training window) ────────────────
            age_days = (now - m.match_date).days
            if age_days <= 90:
                row["sample_weight"] = 4.0   # last 3 months — highest trust
            elif age_days <= 180:
                row["sample_weight"] = 3.0   # last 6 months
            elif age_days <= 365:
                row["sample_weight"] = 2.0   # last year
            else:
                row["sample_weight"] = 1.5   # older within 2-year window

            rows.append(row)
        except Exception:
            pass

    df_train = pd.DataFrame(rows).dropna()

    # ── Time-based train/val split marker ─────────────────────────────────────
    # The SportModel will use this to split chronologically (not randomly)
    # Validation set = most recent 20% of matches
    if len(df_train) > 0 and "match_date" not in df_train.columns:
        pass  # match_date not preserved through build_row — use index ordering
    # We preserve ordering (matches are sorted by date) so SportModel can split by index

    return df_train


def build_inference_row(db: Session, match: Match, sport_key: str) -> pd.DataFrame:
    from data.db_models.models import Sport, Competition
    from sqlalchemy.orm import joinedload

    sport = db.query(Sport).filter_by(key=sport_key).first()
    if not sport:
        return pd.DataFrame()
    matches = (
        db.query(Match)
        .join(Competition)
        .filter(Competition.sport_id == sport.id, Match.result.isnot(None))
        .options(joinedload(Match.home), joinedload(Match.away))
        .order_by(Match.match_date)
        .all()
    )
    def _match_row_inf(m: Match) -> dict:
        row = {
            "id": m.id, "home_id": m.home_id, "away_id": m.away_id,
            "match_date": pd.to_datetime(m.match_date),
            "home_score": m.home_score or 0, "away_score": m.away_score or 0,
            "result": m.result,
        }
        ex = _parse_extra(m.extra_data)
        row["home_shots"]  = ex.get("hs",  None)
        row["away_shots"]  = ex.get("as_", None)
        row["home_sot"]    = ex.get("hst", None)
        row["away_sot"]    = ex.get("ast", None)
        row["home_yellow"] = ex.get("hy",  None)
        row["away_yellow"] = ex.get("ay",  None)
        row["home_red"]    = ex.get("hr",  None)
        row["away_red"]    = ex.get("ar",  None)
        row["referee"]     = ex.get("ref", None)
        row["home_xg"]     = ex.get("home_xg", None)
        row["away_xg"]     = ex.get("away_xg", None)
        return row

    df = pd.DataFrame([_match_row_inf(m) for m in matches]) if matches else pd.DataFrame(
        columns=["id","home_id","away_id","match_date","home_score","away_score","result",
                 "home_shots","away_shots","home_sot","away_sot",
                 "home_yellow","away_yellow","home_red","away_red","referee"]
    )

    # ── Tier 1: ELO for all sports (replay all history before this match) ─────
    from features.tier1_models import EloTracker
    _has_draw = not _sport_is_binary(sport_key)
    _elo_tracker_inf = EloTracker(has_draw=_has_draw)
    elo_snap: dict = {}
    for m in matches:
        if not (m.home and m.away):
            continue
        if m.id == match.id:
            elo_snap = _elo_tracker_inf.snapshot(m.home_id, m.away_id)
            break
        if m.home_score is not None and m.away_score is not None:
            _elo_tracker_inf.update(
                m.home_id, m.away_id,
                float(m.home_score), float(m.away_score),
                m.match_date,
            )

    # ── Tier 1: surface ELO for tennis (replay all history before this match) ─
    surface_snap: dict = {}
    if sport_key == "tennis":
        from features.tier1_models import SurfaceEloTracker, detect_surface
        _tracker = SurfaceEloTracker()
        for m in matches:
            if not (m.home and m.away):
                continue
            _cname   = (m.competition.name if m.competition else "") or ""
            _surface = detect_surface(_cname)
            # Update with past matches only — stop before the target match
            if m.id == match.id:
                # Record snapshot before updating (same causal order as training)
                surface_snap = _tracker.snapshot(m.home_id, m.away_id, _surface)
                break
            if m.home_score is not None and m.away_score is not None:
                _tracker.update(m.home_id, m.away_id,
                                float(m.home_score), float(m.away_score), _surface)

    _comp_name = (match.competition.name if match.competition else "") or ""
    row = build_row(
        db, match, df, sport_key,
        surface_elo_snapshot=surface_snap,
        competition_name=_comp_name,
        elo_snapshot=elo_snap,
    )
    return pd.DataFrame([row])[COMMON_FEATURES]
