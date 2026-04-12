"""
Ingestion pipeline — pulls data from Sportybet + Odds API and stores to DB.
Handles all sports in a unified way.
"""
import random
import math
from datetime import datetime, timedelta
from loguru import logger
from sqlalchemy.orm import Session
from data.db_models.models import Sport, Competition, Participant, Match, MatchOdds
from data.database import get_sync_session
from data.sources.sportybet import SportybetClient
from data.sources.odds_api import OddsAPIClient

SPORTS_META = {
    "football":          {"name": "Football",          "icon": "⚽"},
    "basketball":        {"name": "Basketball",        "icon": "🏀"},
    "tennis":            {"name": "Tennis",            "icon": "🎾"},
    "american_football": {"name": "American Football", "icon": "🏈"},
    "table_tennis":      {"name": "Table Tennis",      "icon": "🏓"},
    "volleyball":        {"name": "Volleyball",        "icon": "🏐"},
    "ice_hockey":        {"name": "Ice Hockey",        "icon": "🏒"},
    "cricket":           {"name": "Cricket",           "icon": "🏏"},
    "rugby":             {"name": "Rugby",             "icon": "🏉"},
    "baseball":          {"name": "Baseball",          "icon": "⚾"},
}


def _get_or_create_sport(db: Session, key: str) -> Sport:
    s = db.query(Sport).filter_by(key=key).first()
    if not s:
        meta = SPORTS_META.get(key, {"name": key.title(), "icon": "🏆"})
        s = Sport(key=key, name=meta["name"], icon=meta["icon"])
        db.add(s); db.flush()
    return s


def _get_or_create_competition(db: Session, sport: Sport, name: str, country: str) -> Competition:
    ext_id = f"{sport.key}_{name}_{country}".replace(" ", "_").lower()[:100]
    c = db.query(Competition).filter_by(external_id=ext_id).first()
    if not c:
        c = Competition(sport_id=sport.id, external_id=ext_id, name=name, country=country)
        db.add(c); db.flush()
    return c


def _get_or_create_participant(db: Session, sport: Sport, name: str, ext_suffix: str = "") -> Participant:
    ext_id = f"{sport.key}_{name}{ext_suffix}".replace(" ", "_").lower()[:100]
    p = db.query(Participant).filter_by(external_id=ext_id).first()
    if not p:
        p = Participant(sport_id=sport.id, external_id=ext_id, name=name)
        db.add(p); db.flush()
    return p


def ingest_events(db: Session, events: list[dict]):
    saved = 0
    for ev in events:
        try:
            sport = _get_or_create_sport(db, ev["sport"])
            comp = _get_or_create_competition(db, sport, ev["competition"], ev.get("country", ""))
            home = _get_or_create_participant(db, sport, ev["home_name"])
            away = _get_or_create_participant(db, sport, ev["away_name"])

            match = db.query(Match).filter_by(external_id=ev["external_id"]).first()
            if not match:
                match = Match(
                    external_id=ev["external_id"],
                    competition_id=comp.id,
                    home_id=home.id,
                    away_id=away.id,
                    match_date=ev["match_date"],
                    status=ev.get("status", "scheduled"),
                )
                db.add(match); db.flush()
                saved += 1

            # Upsert odds — add new snapshot
            for o in ev.get("odds", []):
                db.add(MatchOdds(
                    match_id=match.id,
                    bookmaker=o["bookmaker"],
                    market=o["market"],
                    outcome=o["outcome"],
                    price=o["price"],
                    point=o.get("point"),
                ))
        except Exception as e:
            logger.warning(f"Ingest error for {ev.get('external_id')}: {e}")
            db.rollback()
            continue

    db.commit()
    return saved


def run_live_fetch():
    """Pull latest odds from Sportybet + Odds API."""
    sb = SportybetClient()
    oa = OddsAPIClient()

    sb_events = sb.get_all_sports(hours_ahead=72)
    oa_events = oa.fetch_all()
    all_events = sb_events + oa_events

    with get_sync_session() as db:
        saved = ingest_events(db, all_events)
    logger.info(f"Live fetch: {saved} new matches ingested")


def seed_demo_data():
    """
    Seed realistic demo data for all sports so the app works without API keys.
    Generates ~3 seasons of historical results + upcoming fixtures with odds.
    """
    random.seed(42)

    def poisson_goal(lam):
        L = math.exp(-lam); k, p = 0, 1.0
        while p > L:
            k += 1; p *= random.random()
        return k - 1

    def sim_match(h_elo, a_elo):
        lam_h = max(0.4, min(4.0, 1.3 * (h_elo + 100) / 1500))
        lam_a = max(0.4, min(4.0, 1.3 * a_elo / 1500))
        return poisson_goal(lam_h), poisson_goal(lam_a)

    FOOTBALL_TEAMS = [
        ("Manchester City", 1820), ("Arsenal", 1780), ("Liverpool", 1760),
        ("Chelsea", 1680), ("Tottenham", 1660), ("Newcastle", 1640),
        ("Man Utd", 1600), ("Aston Villa", 1580), ("West Ham", 1540),
        ("Brighton", 1530), ("Wolves", 1510), ("Fulham", 1490),
        ("Brentford", 1480), ("Crystal Palace", 1460), ("Everton", 1450),
        ("Bournemouth", 1440), ("Nottm Forest", 1420), ("Luton", 1390),
        ("Burnley", 1380), ("Sheffield Utd", 1360),
        # La Liga
        ("Real Madrid", 1900), ("Barcelona", 1860), ("Atletico Madrid", 1810),
        ("Sevilla", 1680), ("Real Sociedad", 1650), ("Villarreal", 1630),
        # Bundesliga
        ("Bayern Munich", 1880), ("Borussia Dortmund", 1780), ("RB Leipzig", 1740),
        ("Bayer Leverkusen", 1720), ("Eintracht Frankfurt", 1640),
        # Serie A
        ("Inter Milan", 1820), ("AC Milan", 1800), ("Juventus", 1780),
        ("Napoli", 1760), ("AS Roma", 1700), ("Lazio", 1680),
        # Nigeria
        ("Enyimba FC", 1540), ("Kano Pillars", 1530), ("Rivers United", 1520),
        ("Plateau United", 1500), ("Remo Stars", 1490),
    ]

    BASKETBALL_TEAMS = [
        ("Boston Celtics", 1820), ("Denver Nuggets", 1800), ("Milwaukee Bucks", 1780),
        ("Phoenix Suns", 1760), ("LA Lakers", 1750), ("Golden State Warriors", 1740),
        ("Miami Heat", 1720), ("Philadelphia 76ers", 1710), ("LA Clippers", 1700),
        ("Dallas Mavericks", 1690), ("Memphis Grizzlies", 1680), ("Cleveland Cavaliers", 1670),
    ]

    TENNIS_PLAYERS = [
        ("Novak Djokovic", 1950), ("Carlos Alcaraz", 1880), ("Jannik Sinner", 1860),
        ("Daniil Medvedev", 1840), ("Alexander Zverev", 1800), ("Holger Rune", 1760),
        ("Casper Ruud", 1750), ("Stefanos Tsitsipas", 1740), ("Andrey Rublev", 1720),
        ("Taylor Fritz", 1700), ("Frances Tiafoe", 1680), ("Ben Shelton", 1660),
    ]

    LEAGUES = {
        "football": [
            ("Premier League", "England", FOOTBALL_TEAMS[:20]),
            ("La Liga", "Spain", FOOTBALL_TEAMS[20:26] + FOOTBALL_TEAMS[:14]),
            ("Bundesliga", "Germany", FOOTBALL_TEAMS[26:31] + FOOTBALL_TEAMS[:15]),
            ("Serie A", "Italy", FOOTBALL_TEAMS[31:37] + FOOTBALL_TEAMS[:14]),
            ("Nigeria NPFL", "Nigeria", FOOTBALL_TEAMS[37:42] + FOOTBALL_TEAMS[:15]),
            ("UEFA Champions League", "Europe", FOOTBALL_TEAMS[:8] + FOOTBALL_TEAMS[20:28]),
        ],
        "basketball": [
            ("NBA", "USA", BASKETBALL_TEAMS),
        ],
        "tennis": [
            ("ATP Tour", "International", TENNIS_PLAYERS),
        ],
    }

    with get_sync_session() as db:
        for sport_key, leagues in LEAGUES.items():
            sport = _get_or_create_sport(db, sport_key)

            for league_name, country, teams in leagues:
                comp = _get_or_create_competition(db, sport, league_name, country)
                participants = [_get_or_create_participant(db, sport, name) for name, _ in teams]
                elos = {name: elo for name, elo in teams}

                # 3 seasons of historical matches
                season_start = datetime(2021, 9, 1)
                for season_idx in range(3):
                    season_date = season_start + timedelta(days=365 * season_idx)
                    rounds = 30 if sport_key == "football" else 20
                    matches_per_round = len(participants) // 2

                    for rnd in range(1, rounds + 1):
                        round_date = season_date + timedelta(days=7 * (rnd - 1) + random.randint(0, 2))
                        indices = list(range(len(participants)))
                        random.shuffle(indices)
                        pairs = [(indices[i], indices[i+1]) for i in range(0, len(indices) - 1, 2)]

                        for hi, ai in pairs:
                            h = participants[hi]; a = participants[ai]
                            h_elo = elos.get(h.name, 1500); a_elo = elos.get(a.name, 1500)
                            ext_id = f"demo_{sport_key}_{season_idx}_{rnd}_{h.id}_{a.id}"
                            if db.query(Match).filter_by(external_id=ext_id).first():
                                continue

                            hs, as_ = sim_match(h_elo, a_elo)
                            result = "H" if hs > as_ else ("A" if as_ > hs else "D")
                            m = Match(
                                external_id=ext_id,
                                competition_id=comp.id,
                                home_id=h.id, away_id=a.id,
                                match_date=round_date,
                                status="finished",
                                home_score=hs, away_score=as_, result=result,
                            )
                            db.add(m)

                db.commit()
                logger.info(f"Seeded historical: {league_name}")

                # Upcoming fixtures with odds (next 7 days)
                bookmakers = ["sportybet", "bet365", "betway", "1xbet", "betking"]
                indices = list(range(len(participants)))
                random.shuffle(indices)
                pairs = [(indices[i], indices[i+1]) for i in range(0, min(len(indices)-1, 16), 2)]

                for k, (hi, ai) in enumerate(pairs):
                    h = participants[hi]; a = participants[ai]
                    h_elo = elos.get(h.name, 1500); a_elo = elos.get(a.name, 1500)
                    match_date = datetime.utcnow() + timedelta(days=k % 5, hours=random.randint(12, 21))
                    ext_id = f"upcoming_{sport_key}_{h.id}_{a.id}_2024"
                    if db.query(Match).filter_by(external_id=ext_id).first():
                        continue

                    m = Match(
                        external_id=ext_id, competition_id=comp.id,
                        home_id=h.id, away_id=a.id,
                        match_date=match_date, status="scheduled",
                    )
                    db.add(m); db.flush()

                    # Generate realistic odds
                    from features.elo import win_probabilities
                    probs = win_probabilities(h_elo, a_elo, has_draw=(sport_key == "football"))
                    margin = 0.06
                    h_odds = max(1.05, round((1 / probs["home"]) * (1 - margin) + random.uniform(-0.05, 0.15), 2))
                    a_odds = max(1.05, round((1 / probs["away"]) * (1 - margin) + random.uniform(-0.05, 0.15), 2))

                    for bm in bookmakers:
                        noise = lambda x: max(1.05, round(x + random.uniform(-0.06, 0.06), 2))
                        db.add(MatchOdds(match_id=m.id, bookmaker=bm, market="h2h", outcome="home", price=noise(h_odds)))
                        db.add(MatchOdds(match_id=m.id, bookmaker=bm, market="h2h", outcome="away", price=noise(a_odds)))
                        if sport_key == "football":
                            d_prob = probs.get("draw", 0.26)
                            d_odds = max(2.4, round((1 / d_prob) * (1 - margin) + random.uniform(-0.1, 0.2), 2))
                            db.add(MatchOdds(match_id=m.id, bookmaker=bm, market="h2h", outcome="draw", price=noise(d_odds)))
                            db.add(MatchOdds(match_id=m.id, bookmaker=bm, market="totals", outcome="over", price=round(random.uniform(1.70, 2.10), 2), point=2.5))
                            db.add(MatchOdds(match_id=m.id, bookmaker=bm, market="totals", outcome="under", price=round(random.uniform(1.70, 2.10), 2), point=2.5))
                            db.add(MatchOdds(match_id=m.id, bookmaker=bm, market="btts", outcome="yes", price=round(random.uniform(1.65, 1.95), 2)))
                            db.add(MatchOdds(match_id=m.id, bookmaker=bm, market="btts", outcome="no", price=round(random.uniform(1.80, 2.10), 2)))
                        elif sport_key == "basketball":
                            db.add(MatchOdds(match_id=m.id, bookmaker=bm, market="totals", outcome="over", price=round(random.uniform(1.85, 1.95), 2), point=220.5))
                            db.add(MatchOdds(match_id=m.id, bookmaker=bm, market="totals", outcome="under", price=round(random.uniform(1.85, 1.95), 2), point=220.5))

                db.commit()
                logger.info(f"Seeded upcoming fixtures: {league_name}")

    logger.info("Demo data seeding complete.")
