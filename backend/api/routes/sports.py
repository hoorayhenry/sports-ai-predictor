"""Sports and competitions listing endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from data.database import get_async_session
from data.db_models.models import Sport, Competition, Match, Participant

router = APIRouter(prefix="/sports", tags=["sports"])


@router.get("")
async def list_sports(db: AsyncSession = Depends(get_async_session)):
    result = await db.execute(select(Sport).order_by(Sport.name))
    sports = result.scalars().all()
    out = []
    for s in sports:
        cnt = await db.execute(
            select(func.count(Match.id))
            .join(Competition, Match.competition_id == Competition.id)
            .where(Competition.sport_id == s.id, Match.status == "scheduled")
        )
        out.append({
            "id": s.id, "key": s.key, "name": s.name, "icon": s.icon,
            "upcoming_matches": cnt.scalar() or 0,
        })
    return out


@router.get("/{sport_key}/competitions")
async def list_competitions(sport_key: str, db: AsyncSession = Depends(get_async_session)):
    sport_res = await db.execute(select(Sport).where(Sport.key == sport_key))
    sport = sport_res.scalar_one_or_none()
    if not sport:
        return []
    result = await db.execute(
        select(Competition).where(Competition.sport_id == sport.id).order_by(Competition.name)
    )
    return [{"id": c.id, "name": c.name, "country": c.country} for c in result.scalars().all()]
