"""ELO rating system — works for all sports."""
import math

HOME_ADV = 100.0
DEFAULT_ELO = 1500.0
BASE_K = 32.0


def expected_score(elo_a: float, elo_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def update_elo(home_elo, away_elo, home_score, away_score, k=BASE_K):
    h_exp = expected_score(home_elo + HOME_ADV, away_elo)
    a_exp = 1.0 - h_exp
    if home_score > away_score:
        h_act, a_act = 1.0, 0.0
    elif home_score < away_score:
        h_act, a_act = 0.0, 1.0
    else:
        h_act, a_act = 0.5, 0.5

    # Goal/score difference multiplier (capped)
    diff = abs(home_score - away_score)
    mult = 1.0 + min(diff * 0.15, 0.75)

    return (
        home_elo + k * mult * (h_act - h_exp),
        away_elo + k * mult * (a_act - a_exp),
    )


def win_probabilities(home_elo: float, away_elo: float, has_draw: bool = True) -> dict:
    h_win = expected_score(home_elo + HOME_ADV, away_elo)
    a_win = 1.0 - h_win

    if has_draw:
        elo_diff = abs(home_elo + HOME_ADV - away_elo)
        draw_prob = 0.26 * math.exp(-elo_diff / 600.0)
        draw_prob = max(0.05, min(0.35, draw_prob))
        scale = 1.0 - draw_prob
        return {
            "home": h_win * scale,
            "draw": draw_prob,
            "away": a_win * scale,
        }
    return {"home": h_win, "away": a_win}


def apply_seasonal_decay(elo: float, decay: float = 0.30) -> float:
    """
    Partially reset a team's Elo toward the mean (1500) between seasons.
    decay=0.30 means 30% regression: a team at 1700 becomes 1640 at season start.

    Why: summer transfers, managerial changes and promotions/relegations mean
    prior-season ratings are stale. Full carryover overfits to old form.
    """
    return elo + decay * (DEFAULT_ELO - elo)


def rebuild_elo(db_session, sport_key: str):
    """Rebuild ELO from scratch for a sport's finished matches."""
    from data.db_models.models import Match, Participant, Sport, Competition  # noqa: F811
    from sqlalchemy.orm import joinedload

    sport = db_session.query(Sport).filter_by(key=sport_key).first()
    if not sport:
        return

    # Reset all participants for this sport
    participants = db_session.query(Participant).filter_by(sport_id=sport.id).all()
    for p in participants:
        p.elo_rating = DEFAULT_ELO
    db_session.commit()

    matches = (
        db_session.query(Match)
        .join(Match.competition)
        .filter(
            Match.result.isnot(None),
            Competition.sport_id == sport.id,
        )
        .options(joinedload(Match.home), joinedload(Match.away))
        .order_by(Match.match_date)
        .all()
    )

    has_draw = (sport_key == "football")
    current_season_year: int | None = None

    for m in matches:
        if not m.home or not m.away:
            continue

        # Detect season boundary (July = start of new football season).
        # When the month crosses into July, apply decay to all participants
        # to account for summer transfers and squad changes.
        match_year_month = (m.match_date.year, m.match_date.month)
        season_year = m.match_date.year if m.match_date.month >= 7 else m.match_date.year - 1

        if current_season_year is not None and season_year != current_season_year:
            # New season started — decay all team Elo ratings toward 1500
            all_teams = db_session.query(Participant).filter_by(sport_id=sport.id).all()
            for t in all_teams:
                t.elo_rating = apply_seasonal_decay(t.elo_rating)
            db_session.flush()

        current_season_year = season_year

        h_new, a_new = update_elo(
            m.home.elo_rating, m.away.elo_rating,
            m.home_score or 0, m.away_score or 0
        )
        m.home.elo_rating = h_new
        m.away.elo_rating = a_new

    db_session.commit()
    print(f"ELO rebuilt for {sport_key}: {len(matches)} matches (with seasonal decay)")
