"""
FastAPI application — entry point.
"""
import asyncio
from contextlib import asynccontextmanager
from loguru import logger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from config.settings import get_settings
from data.database import init_db
from api.routes import sports, matches, predictions

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Sports AI Predictor...")
    await init_db()
    logger.info("Database initialised.")

    # Auto-seed demo data if DB is empty
    try:
        from data.database import get_sync_session
        from data.db_models.models import Match
        with get_sync_session() as db:
            count = db.query(Match).count()
        if count == 0:
            logger.info("Empty database — seeding demo data...")
            from data.pipeline import seed_demo_data
            from features.elo import rebuild_elo
            seed_demo_data()
            with get_sync_session() as db:
                for sport_key in ["football", "basketball", "tennis"]:
                    rebuild_elo(db, sport_key)
            logger.info("Demo data seeded and ELO rebuilt.")
        else:
            logger.info(f"Database has {count} matches — skipping seed.")
    except Exception as e:
        logger.error(f"Seed/init error: {e}")

    # Auto-train models if not present
    try:
        _auto_train()
    except Exception as e:
        logger.error(f"Auto-train error: {e}")

    # Auto-predict upcoming
    try:
        _auto_predict()
    except Exception as e:
        logger.error(f"Auto-predict error: {e}")

    yield
    logger.info("Shutting down...")


def _auto_train():
    from ml.models.sport_model import SportModel, MODEL_DIR
    from features.engineering import build_training_matrix
    from data.database import get_sync_session

    for sport_key in ["football", "basketball", "tennis"]:
        model_path = MODEL_DIR / f"{sport_key}_model.pkl"
        if model_path.exists():
            continue
        logger.info(f"Training model for {sport_key}...")
        with get_sync_session() as db:
            df = build_training_matrix(db, sport_key)
        if df.empty:
            logger.warning(f"No training data for {sport_key}")
            continue
        model = SportModel(sport_key)
        model.train(df)
        model.save()
        logger.info(f"Model trained for {sport_key}")


def _auto_predict():
    from ml.models.sport_model import SportModel, MODEL_DIR
    from features.engineering import build_inference_row
    from betting.value_engine import evaluate_match, save_predictions
    from data.database import get_sync_session
    from data.db_models.models import Match, Competition, Sport, Prediction
    from sqlalchemy.orm import joinedload

    with get_sync_session() as db:
        matches = (
            db.query(Match)
            .join(Competition)
            .join(Sport)
            .options(
                joinedload(Match.home),
                joinedload(Match.away),
                joinedload(Match.competition).joinedload(Competition.sport),
            )
            .filter(Match.status == "scheduled")
            .all()
        )

        for m in matches:
            try:
                sport_key = m.competition.sport.key if m.competition and m.competition.sport else None
                if not sport_key:
                    continue
                model_path = MODEL_DIR / f"{sport_key}_model.pkl"
                if not model_path.exists():
                    continue
                model = SportModel.load(sport_key)
                X = build_inference_row(db, m, sport_key)
                if X.empty:
                    continue
                pred_probs = model.predict(X)
                value_bets = evaluate_match(db, m.id, pred_probs)
                save_predictions(db, m, pred_probs, value_bets)
            except Exception as e:
                logger.debug(f"Prediction error match {m.id}: {e}")

    logger.info("Auto-predict complete.")


app = FastAPI(
    title="Sports AI Predictor",
    description="Multi-sport match predictions with value bet detection",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sports.router, prefix="/api/v1")
app.include_router(matches.router, prefix="/api/v1")
app.include_router(predictions.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# Serve React frontend in production
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")
