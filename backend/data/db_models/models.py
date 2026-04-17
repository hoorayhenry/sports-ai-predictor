"""
Unified multi-sport database schema.
One schema handles Football, Basketball, Tennis, and any future sport.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Integer, String, Float, Boolean, DateTime,
    ForeignKey, UniqueConstraint, Index, Text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase, MappedAsDataclass
from sqlalchemy import MetaData

convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=convention)


class Sport(Base):
    __tablename__ = "sports"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)   # football | basketball | tennis
    name: Mapped[str] = mapped_column(String(64))
    icon: Mapped[str] = mapped_column(String(8), default="⚽")

    competitions: Mapped[list["Competition"]] = relationship(back_populates="sport")


class Competition(Base):
    __tablename__ = "competitions"
    id: Mapped[int] = mapped_column(primary_key=True)
    sport_id: Mapped[int] = mapped_column(ForeignKey("sports.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    country: Mapped[str] = mapped_column(String(64), default="")
    logo_url: Mapped[Optional[str]] = mapped_column(String(256))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    sport: Mapped["Sport"] = relationship(back_populates="competitions")
    matches: Mapped[list["Match"]] = relationship(back_populates="competition")


class Participant(Base):
    """Teams (football/basketball) or Players (tennis)."""
    __tablename__ = "participants"
    id: Mapped[int] = mapped_column(primary_key=True)
    sport_id: Mapped[int] = mapped_column(ForeignKey("sports.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    short_name: Mapped[Optional[str]] = mapped_column(String(32))
    country: Mapped[Optional[str]] = mapped_column(String(64))
    logo_url: Mapped[Optional[str]] = mapped_column(String(256))
    elo_rating: Mapped[float] = mapped_column(Float, default=1500.0)
    elo_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # API-Football numeric team ID — used for lineup/injury/xG lookups
    api_football_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)


class Match(Base):
    __tablename__ = "matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), index=True)
    home_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), index=True)
    away_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), index=True)
    match_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(16), default="scheduled")  # scheduled|live|finished
    round: Mapped[Optional[str]] = mapped_column(String(32))

    # Scores (filled after match)
    home_score: Mapped[Optional[int]] = mapped_column(Integer)
    away_score: Mapped[Optional[int]] = mapped_column(Integer)
    result: Mapped[Optional[str]] = mapped_column(String(1))   # H/D/A

    # Sport-specific extras (JSON-like stored as text)
    extra_data: Mapped[Optional[str]] = mapped_column(Text)    # e.g. sets for tennis, quarters for basketball

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    competition: Mapped["Competition"] = relationship(back_populates="matches")
    home: Mapped["Participant"] = relationship(foreign_keys=[home_id])
    away: Mapped["Participant"] = relationship(foreign_keys=[away_id])
    odds: Mapped[list["MatchOdds"]] = relationship(back_populates="match", cascade="all, delete-orphan")
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="match", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_match_date_status", "match_date", "status"),)


class MatchOdds(Base):
    __tablename__ = "match_odds"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    bookmaker: Mapped[str] = mapped_column(String(64))
    market: Mapped[str] = mapped_column(String(32))       # h2h | totals | btts | handicap
    outcome: Mapped[str] = mapped_column(String(64))      # home | draw | away | over | under | yes | no
    price: Mapped[float] = mapped_column(Float)
    point: Mapped[Optional[float]] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    match: Mapped["Match"] = relationship(back_populates="odds")


class Prediction(Base):
    """One summary prediction row per match (updated on retrain)."""
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True, unique=True)
    model_version: Mapped[str] = mapped_column(String(32), default="1.0.0")

    # Result market
    predicted_result: Mapped[Optional[str]] = mapped_column(String(4))   # H/D/A
    home_win_prob: Mapped[Optional[float]] = mapped_column(Float)
    draw_prob: Mapped[Optional[float]] = mapped_column(Float)
    away_win_prob: Mapped[Optional[float]] = mapped_column(Float)

    # Side markets
    over25_prob: Mapped[Optional[float]] = mapped_column(Float)
    btts_prob: Mapped[Optional[float]] = mapped_column(Float)

    # Value bet info (best opportunity found)
    is_value_bet: Mapped[bool] = mapped_column(Boolean, default=False)
    value_market: Mapped[Optional[str]] = mapped_column(String(32))    # h2h|totals|btts
    value_outcome: Mapped[Optional[str]] = mapped_column(String(32))   # home|draw|away|over|under|yes|no
    value_odds: Mapped[Optional[float]] = mapped_column(Float)
    expected_value: Mapped[Optional[float]] = mapped_column(Float)
    kelly_stake: Mapped[Optional[float]] = mapped_column(Float)
    confidence: Mapped[Optional[str]] = mapped_column(String(16))      # high|medium|low

    # Post-match resolution
    correct: Mapped[Optional[bool]] = mapped_column(Boolean)
    profit_loss: Mapped[Optional[float]] = mapped_column(Float)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    match: Mapped["Match"] = relationship(back_populates="predictions")

    __table_args__ = (
        Index("ix_pred_value", "is_value_bet", "expected_value"),
    )


class MatchDecision(Base):
    """AI decision layer on top of ML predictions. One row per match."""
    __tablename__ = "match_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True, unique=True)

    # Scores
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)   # 0-100
    prob_tag: Mapped[str] = mapped_column(String(8), default="RISKY")      # HIGH|MEDIUM|RISKY
    ai_decision: Mapped[str] = mapped_column(String(8), default="SKIP")   # PLAY|SKIP

    # Top predicted outcome
    top_prob: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_outcome: Mapped[Optional[str]] = mapped_column(String(16))  # H/D/A/over/under

    # Volatility
    has_volatility: Mapped[bool] = mapped_column(Boolean, default=False)
    volatility_reason: Mapped[Optional[str]] = mapped_column(String(128))

    # Component scores (for transparency)
    prob_component: Mapped[float] = mapped_column(Float, default=0.0)
    ev_component: Mapped[float] = mapped_column(Float, default=0.0)
    form_component: Mapped[float] = mapped_column(Float, default=0.0)
    consistency_component: Mapped[float] = mapped_column(Float, default=0.0)

    # Recommended odds and stake
    recommended_odds: Mapped[Optional[float]] = mapped_column(Float)
    recommended_stake_pct: Mapped[Optional[float]] = mapped_column(Float)  # % of bankroll

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    match: Mapped["Match"] = relationship()

    __table_args__ = (
        Index("ix_decision_play", "ai_decision", "confidence_score"),
    )


class SmartSet(Base):
    """A curated set of 10 matches generated daily by the AI."""
    __tablename__ = "smart_sets"
    id: Mapped[int] = mapped_column(primary_key=True)
    set_number: Mapped[int] = mapped_column(Integer)          # 1-10
    generated_date: Mapped[datetime] = mapped_column(DateTime, index=True)

    # Matches stored as JSON
    matches_json: Mapped[str] = mapped_column(Text)           # [{match_id, ...}, ...]
    match_count: Mapped[int] = mapped_column(Integer, default=10)

    # Aggregate stats
    overall_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    combined_probability: Mapped[float] = mapped_column(Float, default=0.0)  # product
    avg_odds: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(8), default="MEDIUM")    # LOW|MEDIUM|HIGH

    # Resolution
    status: Mapped[str] = mapped_column(String(16), default="pending")      # pending|partial|resolved
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    roi: Mapped[Optional[float]] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("set_number", "generated_date"),
    )


class PerformanceLog(Base):
    """Tracks resolved prediction outcomes for ROI and self-optimization."""
    __tablename__ = "performance_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    sport_key: Mapped[str] = mapped_column(String(32))
    competition: Mapped[str] = mapped_column(String(128))

    # What we predicted
    ai_decision: Mapped[str] = mapped_column(String(8))        # PLAY|SKIP
    confidence_score: Mapped[float] = mapped_column(Float)
    predicted_outcome: Mapped[str] = mapped_column(String(16)) # H/D/A/over/under
    predicted_prob: Mapped[float] = mapped_column(Float)
    odds_used: Mapped[Optional[float]] = mapped_column(Float)
    stake_pct: Mapped[Optional[float]] = mapped_column(Float)

    # Actual result
    actual_result: Mapped[Optional[str]] = mapped_column(String(16))
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean)
    profit_loss_units: Mapped[Optional[float]] = mapped_column(Float)  # +ve = profit

    log_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    match: Mapped["Match"] = relationship()

    __table_args__ = (
        Index("ix_perf_sport_comp", "sport_key", "competition"),
    )


class OptimizationWeight(Base):
    """Per-competition/sport confidence boosts from self-optimization."""
    __tablename__ = "optimization_weights"
    id: Mapped[int] = mapped_column(primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # scope_key examples: "football", "football_Premier League", "global"
    scope_type: Mapped[str] = mapped_column(String(16))   # sport|competition|global
    weight: Mapped[float] = mapped_column(Float, default=0.0)  # -10 to +10
    success_rate: Mapped[float] = mapped_column(Float, default=0.5)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IntelligenceSignal(Base):
    """News/social intelligence signals extracted via Claude Haiku NLP."""
    __tablename__ = "intelligence_signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[Optional[int]] = mapped_column(ForeignKey("matches.id"), index=True)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("participants.id"), index=True)
    team_name: Mapped[str] = mapped_column(String(128), default="")

    # Signal classification
    signal_type: Mapped[str] = mapped_column(String(32))   # injury|suspension|return|morale|lineup
    entity_name: Mapped[Optional[str]] = mapped_column(String(128))  # player name if applicable

    # Scoring: -1.0 (very negative for team) to +1.0 (very positive)
    impact_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)   # 0-1

    # Source
    source_url: Mapped[Optional[str]] = mapped_column(String(512))
    source_type: Mapped[str] = mapped_column(String(32), default="news")  # news|rss|twitter
    raw_text: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    match: Mapped[Optional["Match"]] = relationship(foreign_keys=[match_id])
    team: Mapped[Optional["Participant"]] = relationship(foreign_keys=[team_id])

    __table_args__ = (
        Index("ix_intel_match_team", "match_id", "team_id"),
    )


class ModelTrainingLog(Base):
    """Tracks every continuous learning retraining run."""
    __tablename__ = "model_training_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    sport_key: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="trained")   # trained|skipped|error
    training_rows: Mapped[int] = mapped_column(Integer, default=0)
    accuracy_json: Mapped[Optional[str]] = mapped_column(Text)           # {market: log_loss, ...}
    trained_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LeagueSeasonCache(Base):
    """
    Permanent store for historical league data fetched from ESPN.
    Keyed by (league_slug, season, data_type) — fetched ONCE, stored forever.
    Historical data never changes so there is no need to re-fetch.

    data_type values: 'standings' | 'fixtures' | 'leaders'
    json_data: the full serialised API response dict.
    """
    __tablename__ = "league_season_cache"

    id:          Mapped[int]      = mapped_column(primary_key=True)
    league_slug: Mapped[str]      = mapped_column(String(32),  index=True)
    season:      Mapped[int]      = mapped_column(Integer)
    data_type:   Mapped[str]      = mapped_column(String(16))   # standings|fixtures|leaders
    json_data:   Mapped[str]      = mapped_column(Text)          # full JSON payload
    fetched_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("league_slug", "season", "data_type",
                         name="uq_league_season_cache_key"),
        Index("ix_league_season_cache_lookup", "league_slug", "season", "data_type"),
    )


class NewsArticle(Base):
    """Rewritten news articles for the PlaySigma news feed."""
    __tablename__ = "news_articles"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    slug: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    source_url: Mapped[str] = mapped_column(String(1024))
    source_name: Mapped[str] = mapped_column(String(128), default="")
    category: Mapped[str] = mapped_column(String(64), default="football")  # football|transfers|injuries|general
    summary: Mapped[str] = mapped_column(Text, default="")   # 1-2 sentence hook
    body: Mapped[str] = mapped_column(Text, default="")      # rewritten full article
    tags: Mapped[Optional[str]] = mapped_column(Text)        # comma-separated team/player names
    image_url: Mapped[Optional[str]] = mapped_column(String(1024))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    # "published" = AI-rewritten by Gemini (safe to serve publicly)
    # "draft"     = raw scraped text only — held back until Gemini rewrites it
    status: Mapped[str] = mapped_column(String(16), default="published", index=True)
