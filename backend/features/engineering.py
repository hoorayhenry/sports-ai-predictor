"""
Unified feature engineering for all sports.
Each sport has its own feature builder but shares common infrastructure.
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

COMMON_FEATURES = [
    # ── Elo ──────────────────────────────────────────────────────────
    "home_elo", "away_elo", "elo_diff",
    "elo_home_prob", "elo_draw_prob", "elo_away_prob",
    # ── Form (goals) ─────────────────────────────────────────────────
    "home_win_rate_5", "home_win_rate_10", "home_goals_avg_5", "home_goals_conceded_avg_5",
    "away_win_rate_5", "away_win_rate_10", "away_goals_avg_5", "away_goals_conceded_avg_5",
    # ── Head-to-head ─────────────────────────────────────────────────
    "h2h_home_win_rate", "h2h_draw_rate", "h2h_away_win_rate", "h2h_avg_goals", "h2h_n",
    # ── Attack / defence strength (Dixon-Coles style) ─────────────────
    "home_attack_str", "home_defence_str", "away_attack_str", "away_defence_str",
    # ── Expected goals (Poisson proxy) ───────────────────────────────
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
    # 1.0 = champion last season, 0.5 = midtable, 0.0 = bottom
    "home_prev_season_rank", "away_prev_season_rank",
    # ── Shot-based features (xG proxy) ───────────────────────────────
    "home_shots_avg_5", "away_shots_avg_5",
    "home_sot_avg_5", "away_sot_avg_5",
    "home_shot_conv_5", "away_shot_conv_5",    # goals / (sot+1) — luck indicator
    "home_xg_proxy_5", "away_xg_proxy_5",      # sot * league_sot_goal_rate
    # ── Referee tendencies ───────────────────────────────────────────
    "ref_avg_goals", "ref_avg_cards",
    # ── Dixon-Coles Poisson model outputs ────────────────────────────
    "dc_home_win", "dc_draw", "dc_away_win",
    "dc_over_2_5", "dc_btts_yes",
    "dc_exp_home_goals", "dc_exp_away_goals",
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

# Dixon-Coles model instance — fitted once per training session, reused for inference
_dc_model = None


def get_dc_model(db, sport_key: str = "football"):
    """Return a cached fitted DixonColes model, building it if needed."""
    global _dc_model
    if _dc_model is None or not _dc_model.is_fitted():
        try:
            from features.poisson import build_dc_model_from_db
            _dc_model = build_dc_model_from_db(db, sport_key)
        except Exception as e:
            logger.warning(f"[Engineering] Dixon-Coles build failed: {e}")
            from features.poisson import DixonColes
            _dc_model = DixonColes()
    return _dc_model


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


def build_row(db: Session, match: Match, df: pd.DataFrame, has_draw: bool = True) -> dict:
    hid, aid = match.home_id, match.away_id
    date = match.match_date
    h_elo = match.home.elo_rating if match.home else 1500.0
    a_elo = match.away.elo_rating if match.away else 1500.0

    elo_p = win_probabilities(h_elo, a_elo, has_draw)
    hf5  = _form(df, hid, date, 5)
    hf10 = _form(df, hid, date, 10)
    af5  = _form(df, aid, date, 5)
    af10 = _form(df, aid, date, 10)
    h2h  = _h2h(df, hid, aid, date)
    hs   = _strength(df, hid, date)
    as_  = _strength(df, aid, date)
    of   = _odds_features(db, match.id)
    hls  = _league_stats(df, hid, date)
    als  = _league_stats(df, aid, date)

    # Shot features (xG proxy)
    hsf = _shots_form(df, hid, date, 5)
    asf = _shots_form(df, aid, date, 5)

    # Referee features
    ref_name = _parse_extra(match.extra_data).get("ref") if match.extra_data else None
    ref_s = _referee_stats(df, ref_name, date)

    # Historical season rank (from league_season_cache) + DC model names
    home_name   = match.home.name if match.home else ""
    away_name   = match.away.name if match.away else ""
    h_prev_rank = _prev_season_rank(db, home_name, match.competition_id, date)
    a_prev_rank = _prev_season_rank(db, away_name, match.competition_id, date)

    # Dixon-Coles Poisson model features
    dc = get_dc_model(db, "football")
    try:
        dc_out = dc.predict(home_name, away_name)
    except Exception:
        dc_out = {
            "home_win": elo_p.get("home", 0.4), "draw": elo_p.get("draw", 0.25),
            "away_win": elo_p.get("away", 0.35), "over_2.5": 0.5, "btts_yes": 0.5,
            "exp_home_goals": exp_h, "exp_away_goals": exp_a,
        }

    lg_avg = df[df.result.notna()]["home_score"].mean() or 1.3
    exp_h = max(0.2, hs["atk"] * as_["def"] * lg_avg)
    exp_a = max(0.2, as_["atk"] * hs["def"] * lg_avg * 0.88)

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
        "away_attack_str": as_["atk"], "away_defence_str": as_["def"],
        "exp_home_goals": exp_h, "exp_away_goals": exp_a, "exp_total_goals": exp_h + exp_a,
        "home_btts_rate": hf10["btts"], "away_btts_rate": af10["btts"],
        "home_over25_rate": hf10["over25"], "away_over25_rate": af10["over25"],
        "imp_home_prob": of["imp_h"], "imp_draw_prob": of["imp_d"], "imp_away_prob": of["imp_a"],
        "market_margin": of["margin"],
        "home_days_rest": _days_rest(df, hid, date),
        "away_days_rest": _days_rest(df, aid, date),
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
        # ── Dixon-Coles Poisson ───────────────────────────────────────
        "dc_home_win":       dc_out.get("home_win", elo_p.get("home", 0.4)),
        "dc_draw":           dc_out.get("draw", elo_p.get("draw", 0.25)),
        "dc_away_win":       dc_out.get("away_win", elo_p.get("away", 0.35)),
        "dc_over_2_5":       dc_out.get("over_2.5", 0.5),
        "dc_btts_yes":       dc_out.get("btts_yes", 0.5),
        "dc_exp_home_goals": dc_out.get("exp_home_goals", exp_h),
        "dc_exp_away_goals": dc_out.get("exp_away_goals", exp_a),
    }


def build_training_matrix(db: Session, sport_key: str) -> pd.DataFrame:
    global _dc_model
    _dc_model = None   # Force fresh DC model fit each training run

    from data.db_models.models import Sport, Competition
    from sqlalchemy.orm import joinedload

    sport = db.query(Sport).filter_by(key=sport_key).first()
    if not sport:
        return pd.DataFrame()

    has_draw = (sport_key == "football")

    matches = (
        db.query(Match)
        .join(Competition)
        .filter(Competition.sport_id == sport.id, Match.result.isnot(None))
        .options(joinedload(Match.home), joinedload(Match.away))
        .order_by(Match.match_date)
        .all()
    )

    if not matches:
        return pd.DataFrame()

    def _match_row(m: Match) -> dict:
        row = {
            "id": m.id, "home_id": m.home_id, "away_id": m.away_id,
            "match_date": pd.to_datetime(m.match_date),
            "home_score": m.home_score or 0, "away_score": m.away_score or 0,
            "result": m.result,
        }
        # Parse shots / cards / referee from extra_data JSON
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
        # Real xG from API-Football backfill (present after job_resolve_matches)
        row["home_xg"]     = ex.get("home_xg", None)
        row["away_xg"]     = ex.get("away_xg", None)
        return row

    df = pd.DataFrame([_match_row(m) for m in matches])

    now = datetime.utcnow()
    rows = []
    for m in matches[20:]:   # skip first 20 (not enough form data)
        try:
            row = build_row(db, m, df, has_draw)
            row["result"] = m.result
            row["over25"] = int((m.home_score or 0) + (m.away_score or 0) > 2.5)
            row["btts"] = int((m.home_score or 0) > 0 and (m.away_score or 0) > 0)

            # Recency weight: recent matches matter more than old ones
            age_days = (now - m.match_date).days
            if age_days <= 180:
                row["sample_weight"] = 3.0   # last 6 months — highest weight
            elif age_days <= 365:
                row["sample_weight"] = 2.0   # last year
            elif age_days <= 730:
                row["sample_weight"] = 1.5   # last 2 years
            else:
                row["sample_weight"] = 1.0   # historical baseline

            rows.append(row)
        except Exception:
            pass
    return pd.DataFrame(rows).dropna()


def build_inference_row(db: Session, match: Match, sport_key: str) -> pd.DataFrame:
    from data.db_models.models import Sport, Competition
    from sqlalchemy.orm import joinedload

    sport = db.query(Sport).filter_by(key=sport_key).first()
    if not sport:
        return pd.DataFrame()

    has_draw = (sport_key == "football")
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

    row = build_row(db, match, df, has_draw)
    return pd.DataFrame([row])[COMMON_FEATURES]
