from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Sports AI Predictor"
    app_version: str = "1.0.0"
    debug: bool = False

    database_url: str = "sqlite+aiosqlite:///./sports_ai.db"
    database_url_sync: str = "sqlite:///./sports_ai.db"

    # APIs
    odds_api_key: str = ""
    football_data_key: str = ""
    api_football_key: str = ""

    # ML
    model_dir: str = "ml/saved"
    confidence_threshold: float = 0.55
    ev_threshold: float = 0.04
    kelly_fraction: float = 0.25
    max_kelly_stake: float = 0.05
    min_train_samples: int = 150

    # CORS — list of allowed origins
    cors_origins: list = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
