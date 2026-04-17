"""News feed API endpoints."""
from typing import Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, delete
from data.database import get_async_session
from data.db_models.models import NewsArticle
from config.settings import get_settings

router = APIRouter(prefix="/news", tags=["news"])


def _fmt_article(a: NewsArticle) -> dict:
    return {
        "id": a.id,
        "title": a.title,
        "slug": a.slug,
        "source_url": a.source_url,
        "source_name": a.source_name,
        "category": a.category,
        "summary": a.summary,
        "body": a.body,
        "tags": [t.strip() for t in (a.tags or "").split(",") if t.strip()],
        "published_at": a.published_at.isoformat() if a.published_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "image_url": a.image_url,
    }


@router.get("")
async def list_news(
    category: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    latest: bool = Query(False, description="If true, return only articles published in the last 24 hours"),
    db: AsyncSession = Depends(get_async_session),
):
    """
    List published articles. Supports pagination for infinite scroll.
    Pass latest=true to fetch only articles from the last 24 hours (for the Latest strip).
    """
    q = select(NewsArticle).where(NewsArticle.status == "published").order_by(desc(NewsArticle.created_at))
    if category:
        q = q.where(NewsArticle.category == category)
    if latest:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        q = q.where(NewsArticle.created_at >= cutoff)

    total_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(total_q)).scalar_one()

    result = await db.execute(q.offset(offset).limit(limit))
    articles = result.scalars().all()

    draft_q = select(func.count()).where(NewsArticle.status == "draft")
    drafts_pending = (await db.execute(draft_q)).scalar_one()

    return {
        "articles": [_fmt_article(a) for a in articles],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < total,
        "drafts_pending": drafts_pending,
    }


@router.get("/{article_id}")
async def get_article(
    article_id: int,
    db: AsyncSession = Depends(get_async_session),
):
    result = await db.execute(select(NewsArticle).where(NewsArticle.id == article_id))
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return _fmt_article(article)


@router.post("/backfill-images")
async def backfill_images(background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_async_session)):
    """
    Backfill og:image for existing articles that have no image_url.
    Runs in background — safe to call repeatedly (skips articles that already have images).
    """
    missing = (await db.execute(
        select(func.count()).where(NewsArticle.image_url.is_(None))
    )).scalar_one()

    def _run():
        from data.database import get_sync_session
        from intelligence.news_writer import _fetch_og_image
        from data.db_models.models import NewsArticle as _NA
        from sqlalchemy import select as _sel

        with get_sync_session() as sdb:
            articles = sdb.execute(
                _sel(_NA).where(_NA.image_url.is_(None)).limit(100)
            ).scalars().all()
            updated = 0
            for a in articles:
                img = _fetch_og_image(a.source_url)
                if img:
                    a.image_url = img
                    updated += 1
            if updated:
                sdb.commit()

    background_tasks.add_task(_run)
    return {"status": "started", "articles_without_images": missing,
            "message": f"Fetching images for up to 100 articles in background."}


@router.post("/clear-watermarked-images")
async def clear_watermarked_images(db: AsyncSession = Depends(get_async_session)):
    """One-time: clear image_url for articles from watermarked sources."""
    watermarked_domains = ["bbci.co.uk", "ichef.bbc", "skysports.com", "espncdn.com", "theguardian.com"]
    result = await db.execute(
        select(NewsArticle).where(NewsArticle.image_url.isnot(None))
    )
    articles = result.scalars().all()
    cleared = 0
    for a in articles:
        if a.image_url and any(d in a.image_url for d in watermarked_domains):
            a.image_url = None
            cleared += 1
    await db.commit()
    return {"cleared": cleared}


@router.post("/reset")
async def reset_articles(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Wipe ALL articles and immediately trigger a fresh 20-article scrape from today's news.
    Use this to start clean. Articles are fetched from RSS feeds published in the last 24 hours.
    """
    # Hard delete everything
    deleted = (await db.execute(select(func.count()).where(NewsArticle.id.isnot(None)))).scalar_one()
    await db.execute(delete(NewsArticle))
    await db.commit()

    settings = get_settings()

    def _fresh_scrape():
        from data.database import get_sync_session
        from intelligence.news_writer import run_news_pipeline_sync
        with get_sync_session() as sdb:
            run_news_pipeline_sync(sdb, settings.gemini_api_key, hours=24, max_articles=20)

    background_tasks.add_task(_fresh_scrape)

    return {
        "status": "reset",
        "deleted": deleted,
        "message": "All articles deleted. Fetching 20 fresh articles from the last 24 hours. Refresh in ~60 seconds.",
    }


@router.post("/trigger")
async def trigger_news_pipeline(background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_async_session)):
    """Manually trigger the news pipeline + draft retry."""
    settings = get_settings()

    # Snapshot current published count so frontend can compare after refetch
    published_before = (await db.execute(select(func.count()).where(NewsArticle.status == "published"))).scalar_one()
    drafts_before = (await db.execute(select(func.count()).where(NewsArticle.status == "draft"))).scalar_one()

    def _run_sync():
        from data.database import get_sync_session
        from intelligence.news_writer import run_news_pipeline_sync, retry_draft_articles
        api_key = settings.gemini_api_key
        with get_sync_session() as db:
            new_saved  = run_news_pipeline_sync(db, api_key, hours=48, max_articles=20)
            promoted   = retry_draft_articles(db, api_key, max_articles=15)
        return new_saved, promoted

    background_tasks.add_task(_run_sync)
    return {
        "status":           "started",
        "published_before": published_before,
        "drafts_pending":   drafts_before,
        "message":          "Fetching and rewriting articles in the background. Refresh in ~30 seconds.",
    }
