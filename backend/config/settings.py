from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Sports AI Predictor"
    app_version: str = "2.0.0"
    debug: bool = False

    database_url:      str = "sqlite+aiosqlite:///./sports_ai.db"
    database_url_sync: str = "sqlite:///./sports_ai.db"

    # ── External API keys ─────────────────────────────────────────────
    # The Odds API  — https://the-odds-api.com  (free: 500 req/mo)
    odds_api_key: str = ""

    # API-Football  — https://www.api-football.com  (free: 100 req/day)
    # Also accepts RapidAPI key from https://rapidapi.com/api-sports/api/api-football
    api_football_key: str = ""

    # football-data.org  (optional, supplements football-data.co.uk CSVs)
    football_data_key: str = ""

    # ── ML hyperparameters ────────────────────────────────────────────
    model_dir:            str   = "ml/saved"
    confidence_threshold: float = 0.55
    ev_threshold:         float = 0.04
    kelly_fraction:       float = 0.25
    max_kelly_stake:      float = 0.05
    min_train_samples:    int   = 150

    # ── CORS ──────────────────────────────────────────────────────────
    cors_origins: list = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]

    # ── Email (SMTP) ──────────────────────────────────────────────────
    email_smtp_host: str = ""                           # e.g. smtp.gmail.com
    email_smtp_port: int = 587                          # 587 = TLS, 465 = SSL
    email_smtp_user: str = ""
    email_smtp_pass: str = ""                           # Gmail app password
    email_from:      str = "Sports AI <noreply@sportsai.local>"
    email_recipient: str = ""                           # who gets the daily email

    # ── Decision thresholds ───────────────────────────────────────────
    play_prob_threshold:       float = 0.65
    play_confidence_threshold: float = 70.0
    daily_email_hour:          int   = 8                # UTC hour for daily email


@lru_cache
def get_settings() -> Settings:
    return Settings()
