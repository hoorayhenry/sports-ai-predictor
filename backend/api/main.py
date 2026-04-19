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
from api.routes import decisions as decisions_router
from api.routes import news as news_router
from api.routes.standings import router as standings_router
from api.routes.teams import teams_router, players_router
from api.routes.analytics import router as analytics_router
from api.routes.sports_data import router as sports_data_router
from api.routes.search import router as search_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Sports AI Predictor v2...")
    await init_db()
    logger.info("Database initialised.")

    # On empty DB: fetch real live fixtures from Sportybet + Odds API.
    # Full historical load (CSV + NBA + ATP) must be run separately via:
    #   python scripts/setup.py
    try:
        from data.database import get_sync_session
        from data.db_models.models import Match
        with get_sync_session() as db:
            count = db.query(Match).count()
        if count == 0:
            logger.info("Empty database — fetching real fixtures from Sportybet + Odds API...")
            from data.pipeline import run_live_fetch
            run_live_fetch()
            with get_sync_session() as db:
                new_count = db.query(Match).count()
            logger.info(f"Initial fetch complete — {new_count} matches loaded.")
        else:
            logger.info(f"Database has {count} matches.")
    except Exception as e:
        logger.error(f"Initial data fetch error: {e}")

    # Auto-train + auto-predict in background — never block server startup
    asyncio.get_event_loop().run_in_executor(None, _auto_train_and_predict_safe)

    # Register event loop for the live scores event bus
    try:
        from data.live_bus import register_loop
        register_loop(asyncio.get_event_loop())
        logger.info("Live scores event bus registered.")
    except Exception as e:
        logger.error(f"Live bus registration error: {e}")

    # Start background scheduler
    try:
        from scheduler import start_scheduler
        start_scheduler()
        logger.info("Background scheduler started.")
    except Exception as e:
        logger.error(f"Scheduler start error: {e}")

    # Run decision engine in the background — don't block startup
    asyncio.get_event_loop().run_in_executor(None, _auto_decisions_safe)

    yield

    logger.info("Shutting down...")
    try:
        from scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass


def _auto_train():
    from ml.models.sport_model import SportModel, MODEL_DIR
    from features.engineering import build_training_matrix
    from data.database import get_sync_session
    import ml.training_progress as tp

    sport_keys = [
        "football", "basketball", "tennis", "baseball",
        "american_football", "ice_hockey", "cricket", "rugby",
        "handball", "volleyball",
    ]

    tp.start_training()
    try:
        for sport_key in sport_keys:
            model_path = MODEL_DIR / f"{sport_key}_model.pkl"
            if model_path.exists():
                tp.sport_done(sport_key, accuracy=None, skipped=True)
                continue
            logger.info(f"Training model for {sport_key}...")
            with get_sync_session() as db:
                df = build_training_matrix(db, sport_key)
            if df.empty:
                logger.warning(f"No training data for {sport_key}")
                tp.sport_done(sport_key, accuracy=None, skipped=True)
                continue
            tp.sport_started(sport_key, rows=len(df))
            model = SportModel(sport_key)
            scores = model.train(df, market_callback=lambda m: tp.market_done(sport_key, m))
            model.save()
            accuracy = scores.get("result")
            tp.sport_done(sport_key, accuracy=accuracy)
            logger.info(f"Model trained for {sport_key}")
    finally:
        tp.finish_training()


def _auto_predict():
    from ml.models.sport_model import SportModel, MODEL_DIR
    from features.engineering import build_inference_row
    from betting.value_engine import evaluate_match, save_predictions
    from data.database import get_sync_session
    from data.db_models.models import Match, Competition, Sport, Prediction
    from sqlalchemy.orm import joinedload

    with get_sync_session() as db:
        # Only predict matches that don't already have a prediction
        predicted_ids = {p.match_id for p in db.query(Prediction.match_id).all()}
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
        unpredicted = [m for m in matches if m.id not in predicted_ids]
        logger.info(f"Auto-predict: {len(unpredicted)} new matches to predict (skipping {len(predicted_ids)} already done)")

        for m in unpredicted:
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


def _auto_train_and_predict_safe():
    try:
        _auto_train()
    except Exception as e:
        logger.error(f"Auto-train background error: {e}")
    try:
        _auto_predict()
    except Exception as e:
        logger.error(f"Auto-predict background error: {e}")


def _auto_decisions_safe():
    try:
        _auto_decisions()
    except Exception as e:
        logger.error(f"Auto-decisions background error: {e}")


def _auto_decisions():
    from data.database import get_sync_session
    from betting.decision_engine import process_decisions, generate_smart_sets
    from data.db_models.models import MatchDecision

    with get_sync_session() as db:
        existing = db.query(MatchDecision).count()
        play_count = process_decisions(db)
        # Generate smart sets if none exist today
        from datetime import datetime
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0)
        from data.db_models.models import SmartSet
        today_sets = db.query(SmartSet).filter(SmartSet.generated_date >= today_start).count()
        if today_sets == 0:
            generate_smart_sets(db)
    logger.info(f"Decisions ready: {play_count} PLAY decisions")


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
app.include_router(decisions_router.router, prefix="/api/v1")
app.include_router(news_router.router, prefix="/api/v1")
app.include_router(standings_router, prefix="/api/v1")
app.include_router(teams_router,    prefix="/api/v1")
app.include_router(players_router,  prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(sports_data_router, prefix="/api/v1")
app.include_router(search_router,     prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# Serve React frontend in production
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    # Serve static assets (JS, CSS, images) directly
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    # SPA catch-all: serve index.html for every non-API route so React Router works
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        file_path = frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(frontend_dist / "index.html"))
