"""Global search endpoint — teams, competitions, matches, news."""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from sqlalchemy.orm import selectinload

from data.database import get_async_session
from data.db_models.models import (
    Participant, Competition, Sport, Match, NewsArticle,
)

# Map competition name keywords → ESPN standings slug
# Used for fuzzy matching against competition names in DB
COMP_NAME_TO_ESPN: list[tuple[str, str]] = [
    ("premier league",      "eng.1"),
    ("english premier",     "eng.1"),
    ("epl",                 "eng.1"),
    ("la liga",             "esp.1"),
    ("bundesliga",          "ger.1"),
    ("serie a",             "ita.1"),
    ("ligue 1",             "fra.1"),
    ("primeira liga",       "por.1"),
    ("eredivisie",          "ned.1"),
    ("süper lig",           "tur.1"),
    ("super lig",           "tur.1"),
    ("scottish premiership","sco.1"),
    ("scottish prem",       "sco.1"),
    ("pro league",          "bel.1"),
    ("mls",                 "usa.1"),
    ("brasileirao",         "bra.1"),
    ("liga profesional",    "arg.1"),
    ("liga betplay",        "col.1"),
    ("liga mx",             "mex.1"),
    ("champions league",    "uefa.champions"),
    ("europa league",       "uefa.europa"),
    ("conference league",   "uefa.europa.conf"),
]

def _comp_to_espn_slug(comp_name: str) -> str | None:
    name_lower = comp_name.lower()
    for keyword, slug in COMP_NAME_TO_ESPN:
        if keyword in name_lower:
            return slug
    return None

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def search(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(default=5, le=10),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Search teams, competitions, upcoming matches, and news.
    Returns grouped results, each section capped at `limit`.
    """
    q = q.strip()
    if not q:
        return {"teams": [], "competitions": [], "matches": [], "news": []}

    pat = f"%{q}%"

    # ── Teams ─────────────────────────────────────────────────────────────────
    team_q = (
        select(Participant)
        .join(Sport, Participant.sport_id == Sport.id)
        .where(
            or_(
                Participant.name.ilike(pat),
                Participant.short_name.ilike(pat),
            )
        )
        .order_by(Participant.elo_rating.desc())
        .limit(limit)
    )
    team_rows = (await db.execute(team_q)).scalars().all()

    teams = []
    for t in team_rows:
        sport_row = await db.get(Sport, t.sport_id)

        # Find an ESPN-mappable competition for this team
        # Try all competitions the team has played in, pick first with a known slug
        comp_q2 = (
            select(Competition)
            .join(Match, Match.competition_id == Competition.id)
            .where(or_(Match.home_id == t.id, Match.away_id == t.id))
            .order_by(Match.match_date.desc())
            .limit(20)
        )
        comp_rows2 = (await db.execute(comp_q2)).scalars().all()
        espn_slug = None
        for cr in comp_rows2:
            slug_candidate = _comp_to_espn_slug(cr.name)
            if slug_candidate:
                espn_slug = slug_candidate
                break

        teams.append({
            "id": t.id,
            "external_id": t.external_id,
            "name": t.name,
            "short_name": t.short_name,
            "country": t.country,
            "logo_url": t.logo_url,
            "sport": sport_row.key if sport_row else None,
            "sport_icon": sport_row.icon if sport_row else "🏆",
            "elo": round(t.elo_rating),
            "espn_slug": espn_slug,   # e.g. "esp.1" for La Liga teams
        })

    # ── Competitions ──────────────────────────────────────────────────────────
    comp_q = (
        select(Competition)
        .join(Sport, Competition.sport_id == Sport.id)
        .where(Competition.name.ilike(pat))
        .order_by(Competition.name)
        .limit(limit)
    )
    comp_rows = (await db.execute(comp_q)).scalars().all()

    competitions = []
    seen_comp_slugs: set[str] = set()
    for c in comp_rows:
        espn_slug = _comp_to_espn_slug(c.name)
        # Deduplicate: same ESPN slug = same competition with different names in DB
        if espn_slug and espn_slug in seen_comp_slugs:
            continue
        if espn_slug:
            seen_comp_slugs.add(espn_slug)
        sport_row = await db.get(Sport, c.sport_id)
        competitions.append({
            "id": c.id,
            "external_id": c.external_id,
            "name": c.name,
            "country": c.country,
            "sport": sport_row.key if sport_row else None,
            "sport_icon": sport_row.icon if sport_row else "🏆",
            "espn_slug": espn_slug,
        })

    # ── Upcoming & recent matches ─────────────────────────────────────────────
    window_start = datetime.utcnow() - timedelta(days=3)
    window_end   = datetime.utcnow() + timedelta(days=14)

    match_q = (
        select(Match)
        .options(
            selectinload(Match.home),
            selectinload(Match.away),
            selectinload(Match.competition).selectinload(Competition.sport),
        )
        .join(Participant, Match.home_id == Participant.id)
        .join(Competition, Match.competition_id == Competition.id)
        .where(
            Match.match_date >= window_start,
            Match.match_date <= window_end,
            or_(
                Participant.name.ilike(pat),
                # also match away team name via subquery on away participant
                Match.away_id.in_(
                    select(Participant.id).where(Participant.name.ilike(pat))
                ),
                Competition.name.ilike(pat),
            ),
        )
        .order_by(Match.match_date)
        .limit(limit)
    )
    match_rows = (await db.execute(match_q)).scalars().all()

    matches = []
    for m in match_rows:
        sport = m.competition.sport if m.competition else None
        matches.append({
            "id": m.id,
            "home_team": m.home.name if m.home else "TBD",
            "away_team": m.away.name if m.away else "TBD",
            "home_logo": m.home.logo_url if m.home else None,
            "away_logo": m.away.logo_url if m.away else None,
            "competition": m.competition.name if m.competition else None,
            "match_date": m.match_date.isoformat() if m.match_date else None,
            "status": m.status,
            "home_score": m.home_score,
            "away_score": m.away_score,
            "sport": sport.key if sport else None,
            "sport_icon": sport.icon if sport else "🏆",
        })

    # ── News ──────────────────────────────────────────────────────────────────
    news_q = (
        select(NewsArticle)
        .where(
            or_(
                NewsArticle.title.ilike(pat),
                NewsArticle.summary.ilike(pat),
                NewsArticle.tags.ilike(pat),
            )
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(limit)
    )
    news_rows = (await db.execute(news_q)).scalars().all()

    news = []
    for n in news_rows:
        news.append({
            "id": n.id,
            "title": n.title,
            "summary": n.summary[:120] if n.summary else "",
            "image_url": n.image_url,
            "source_name": n.source_name,
            "published_at": n.published_at.isoformat() if n.published_at else None,
            "slug": n.slug,
            "category": n.category,
        })

    total = len(teams) + len(competitions) + len(matches) + len(news)
    return {
        "teams": teams,
        "competitions": competitions,
        "matches": matches,
        "news": news,
        "total": total,
    }
