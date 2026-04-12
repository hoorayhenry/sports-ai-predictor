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
