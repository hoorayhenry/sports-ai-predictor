"""
Unified feature engineering for all sports.
Each sport has its own feature builder but shares common infrastructure.
"""
import math
import numpy as np
import pandas as pd
from datetime import datetime
from sqlalchemy.orm import Session
from data.db_models.models import Match, Participant, Competition, Sport
from features.elo import win_probabilities

COMMON_FEATURES = [
    "home_elo", "away_elo", "elo_diff",
    "elo_home_prob", "elo_draw_prob", "elo_away_prob",
    "home_win_rate_5", "home_win_rate_10", "home_goals_avg_5", "home_goals_conceded_avg_5",
    "away_win_rate_5", "away_win_rate_10", "away_goals_avg_5", "away_goals_conceded_avg_5",
    "h2h_home_win_rate", "h2h_draw_rate", "h2h_away_win_rate", "h2h_avg_goals", "h2h_n",
    "home_attack_str", "home_defence_str", "away_attack_str", "away_defence_str",
    "exp_home_goals", "exp_away_goals", "exp_total_goals",
    "home_btts_rate", "away_btts_rate", "home_over25_rate", "away_over25_rate",
    "imp_home_prob", "imp_draw_prob", "imp_away_prob", "market_margin",
    "home_days_rest", "away_days_rest",
]


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


def _days_rest(df: pd.DataFrame, pid: int, before: datetime) -> float:
    last = df[
        ((df.home_id == pid) | (df.away_id == pid)) & (df.match_date < before)
    ].sort_values("match_date", ascending=False).head(1)
    if last.empty: return 7.0
    return min((before - last.iloc[0].match_date).days, 30)


def build_row(db: Session, match: Match, df: pd.DataFrame, has_draw: bool = True) -> dict:
    hid, aid = match.home_id, match.away_id
    date = match.match_date
    h_elo = match.home.elo_rating if match.home else 1500.0
    a_elo = match.away.elo_rating if match.away else 1500.0

    elo_p = win_probabilities(h_elo, a_elo, has_draw)
    hf5 = _form(df, hid, date, 5)
    hf10 = _form(df, hid, date, 10)
    af5 = _form(df, aid, date, 5)
    af10 = _form(df, aid, date, 10)
    h2h = _h2h(df, hid, aid, date)
    hs = _strength(df, hid, date)
    as_ = _strength(df, aid, date)
    of = _odds_features(db, match.id)

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
    }


def build_training_matrix(db: Session, sport_key: str) -> pd.DataFrame:
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

    df = pd.DataFrame([{
        "id": m.id, "home_id": m.home_id, "away_id": m.away_id,
        "match_date": pd.to_datetime(m.match_date),
        "home_score": m.home_score or 0, "away_score": m.away_score or 0,
        "result": m.result,
    } for m in matches])

    rows = []
    for m in matches[20:]:   # skip first 20 (not enough form data)
        try:
            row = build_row(db, m, df, has_draw)
            row["result"] = m.result
            row["over25"] = int((m.home_score or 0) + (m.away_score or 0) > 2.5)
            row["btts"] = int((m.home_score or 0) > 0 and (m.away_score or 0) > 0)
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
    df = pd.DataFrame([{
        "id": m.id, "home_id": m.home_id, "away_id": m.away_id,
        "match_date": pd.to_datetime(m.match_date),
        "home_score": m.home_score or 0, "away_score": m.away_score or 0,
        "result": m.result,
    } for m in matches]) if matches else pd.DataFrame(columns=["id","home_id","away_id","match_date","home_score","away_score","result"])

    row = build_row(db, match, df, has_draw)
    return pd.DataFrame([row])[COMMON_FEATURES]
