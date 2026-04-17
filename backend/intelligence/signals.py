"""
Intelligence signal storage, retrieval, and confidence boost calculation.

Main entry point: run_intelligence_for_upcoming()
  - Finds matches kicking off in the next N hours
  - Scrapes news for both teams
  - Extracts signals via Claude Haiku
  - Persists IntelligenceSignal rows
  - Returns how many signals were saved

Confidence boost: get_intelligence_boost(db, match_id)
  - Returns a float in [-15, +15] added to the decision engine confidence score
  - Negative = bad news (injury, suspension) → less confident in PLAY
  - Positive = good news (key player returns, strong morale) → more confident
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger
from sqlalchemy.orm import Session

from data.db_models.models import IntelligenceSignal, Match, Participant, Competition, Sport
from intelligence.scraper import IntelligenceScraper
from intelligence.nlp_processor import extract_signals


# ── Persistence ───────────────────────────────────────────────────────

def save_signals(
    db: Session,
    match_id: int,
    team_id: int,
    team_name: str,
    signals: dict,
    source_url: str,
    source_type: str = "news",
) -> int:
    """Persist extracted signals. Returns number of rows saved."""
    saved = 0

    def _add(signal_type: str, entity: Optional[str], impact: float, conf: float, raw: str = ""):
        nonlocal saved
        sig = IntelligenceSignal(
            match_id=match_id,
            team_id=team_id,
            team_name=team_name,
            signal_type=signal_type,
            entity_name=entity,
            impact_score=max(-1.0, min(1.0, impact)),
            confidence=max(0.0, min(1.0, conf)),
            source_url=source_url[:512] if source_url else None,
            source_type=source_type,
            raw_text=raw[:500] if raw else None,
        )
        db.add(sig)
        saved += 1

    conf = signals.get("confidence", 0.5)

    for inj in signals.get("injuries", []):
        _add("injury", inj.get("player"), inj.get("impact", -0.5), conf)

    for sus in signals.get("suspensions", []):
        _add("suspension", sus.get("player"), sus.get("impact", -0.5), conf)

    for ret in signals.get("returns", []):
        _add("return", ret.get("player"), ret.get("impact", 0.3), conf)

    morale = signals.get("morale", {})
    if abs(morale.get("score", 0.0)) > 0.05:
        _add("morale", None, morale["score"], conf, morale.get("reason", ""))

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save signals for match {match_id}: {e}")
        return 0

    return saved


# ── Retrieval / boost calculation ─────────────────────────────────────

def get_intelligence_boost(db: Session, match_id: int, hours: int = 72) -> float:
    """
    Returns a confidence score adjustment in [-15, +15] for a match.
    Aggregates all intelligence signals for both teams in the match.
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    signals = (
        db.query(IntelligenceSignal)
        .filter(
            IntelligenceSignal.match_id == match_id,
            IntelligenceSignal.created_at >= cutoff,
        )
        .all()
    )
    if not signals:
        return 0.0

    total_weight = sum(s.confidence for s in signals)
    if total_weight == 0:
        return 0.0

    weighted = sum(s.impact_score * s.confidence for s in signals)
    raw_impact = weighted / total_weight   # -1.0 to +1.0

    # Scale to confidence score points: max ±15
    boost = raw_impact * 15.0
    return round(max(-15.0, min(15.0, boost)), 2)


def get_match_intelligence_summary(db: Session, match_id: int) -> dict:
    """Return formatted intelligence signals for API response."""
    signals = (
        db.query(IntelligenceSignal)
        .filter(IntelligenceSignal.match_id == match_id)
        .order_by(IntelligenceSignal.created_at.desc())
        .limit(20)
        .all()
    )
    if not signals:
        return {"has_intelligence": False, "signals": []}

    return {
        "has_intelligence": True,
        "signals": [
            {
                "type":       s.signal_type,
                "player":     s.entity_name,
                "team":       s.team_name,
                "impact":     s.impact_score,
                "confidence": s.confidence,
                "source":     s.source_type,
                "note":       s.raw_text or "",
            }
            for s in signals
        ],
    }


# ── Main runner ───────────────────────────────────────────────────────

def run_intelligence_for_upcoming(
    db: Session,
    api_key: str,
    hours_ahead: int = 48,
    max_matches: int = 15,
    max_runtime_seconds: int = 300,
) -> int:
    """
    Scrape + extract intelligence for upcoming matches.
    Caps at max_matches per run and enforces a wall-clock timeout so the
    scheduler job can never block the event loop for more than max_runtime_seconds.
    """
    import time as _time
    if not api_key:
        logger.warning("[Intelligence] GEMINI_API_KEY not set — skipping")
        return 0

    job_start = _time.monotonic()
    cutoff = datetime.utcnow() + timedelta(hours=hours_ahead)
    recent  = datetime.utcnow() - timedelta(hours=6)

    matches = (
        db.query(Match)
        .join(Competition)
        .join(Sport)
        .filter(
            Match.status == "scheduled",
            Match.match_date >= datetime.utcnow(),
            Match.match_date <= cutoff,
        )
        .all()
    )

    if not matches:
        logger.info("[Intelligence] No upcoming matches to process")
        return 0

    # Find matches that already have fresh signals
    already_processed = set(
        row[0] for row in
        db.query(IntelligenceSignal.match_id)
        .filter(IntelligenceSignal.created_at >= recent)
        .distinct()
        .all()
    )

    to_process = [m for m in matches if m.id not in already_processed][:max_matches]
    logger.info(f"[Intelligence] Processing {len(to_process)}/{len(matches)} matches (capped at {max_matches}, others have fresh signals)")

    total_saved = 0

    with IntelligenceScraper() as scraper:
        for match in to_process:
            if (_time.monotonic() - job_start) > max_runtime_seconds:
                logger.warning(f"[Intelligence] Hit {max_runtime_seconds}s wall-clock limit — stopping early")
                break
            home_name = match.home.name if match.home else ""
            away_name = match.away.name if match.away else ""
            home_id   = match.home_id
            away_id   = match.away_id

            if not home_name or not away_name:
                continue

            try:
                articles = scraper.fetch_for_match(home_name, away_name, hours=48)
                logger.debug(f"[Intelligence] {home_name} vs {away_name}: {len(articles)} articles")

                for article in articles[:6]:   # cap at 6 per match to save API cost
                    team_name = article.get("team", "")
                    team_id   = home_id if team_name == home_name else away_id

                    # Try snippet first; fetch full text if snippet is thin
                    text = article.get("snippet", "")
                    if len(text) < 200 and article.get("url"):
                        full = scraper.fetch_article_text(article["url"])
                        if full:
                            text = full

                    if not text or len(text) < 50:
                        continue

                    signals = extract_signals(text, team_name, api_key)

                    # Only save if meaningful signal found
                    if signals["confidence"] < 0.2 and signals["overall_team_impact"] == 0.0:
                        continue

                    saved = save_signals(
                        db=db,
                        match_id=match.id,
                        team_id=team_id,
                        team_name=team_name,
                        signals=signals,
                        source_url=article.get("url", ""),
                        source_type=article.get("source", "news"),
                    )
                    total_saved += saved

            except Exception as e:
                logger.error(f"[Intelligence] Error processing {home_name} vs {away_name}: {e}")
                continue

    logger.info(f"[Intelligence] Done — {total_saved} new signals saved")
    return total_saved
