# PlaySigma Backend

FastAPI backend powering the prediction engine, data pipeline, scheduling, and all API routes.

---

## Stack

| Component       | Technology                         |
|-----------------|------------------------------------|
| Framework       | FastAPI (async)                    |
| Database        | SQLite (dev) / PostgreSQL (prod)   |
| ORM             | SQLAlchemy 2.0 (async + sync)      |
| ML              | XGBoost, LightGBM, scikit-learn    |
| Statistical     | SciPy (Dixon-Coles optimisation)   |
| Scheduling      | APScheduler (background jobs)      |
| HTTP client     | httpx                              |
| NLP             | Google Gemini Flash (free tier)    |
| Python          | 3.11+                              |

---

## Prerequisites

- Python 3.11+
- pip / venv

---

## Setup

```bash
cd backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate     # macOS/Linux
# venv\Scripts\activate      # Windows

# Install dependencies
pip install -r requirements.txt
```

---

## Environment Variables

Create `backend/.env`:

```env
# Database
DATABASE_URL=sqlite+aiosqlite:///./sports_ai.db
DATABASE_URL_SYNC=sqlite:///./sports_ai.db

# NLP — Google Gemini Flash (free: 1,500 req/day)
# Get key: https://aistudio.google.com → "Get API key"
GEMINI_API_KEY=your_gemini_key

# Betting odds (free: 500 req/month)
# Get key: https://the-odds-api.com
ODDS_API_KEY=your_odds_key

# Pre-match lineups + xG (free: 100 req/day)
# Get key: https://rapidapi.com/api-sports/api/api-football
API_FOOTBALL_KEY=your_key

# Decision thresholds (optional — defaults shown)
PLAY_PROB_THRESHOLD=0.65
PLAY_CONFIDENCE_THRESHOLD=70.0
CONFIDENCE_THRESHOLD=0.55
EV_THRESHOLD=0.04
```

---

## Running the Server

```bash
cd backend
source venv/bin/activate

# Development (auto-reload)
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Production
uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2
```

Server starts at `http://localhost:8000`
API docs: `http://localhost:8000/docs` (Swagger UI)

---

## Initial Data Load

On first run, the database will be empty. Run the historical data load to populate it:

```bash
cd backend
source venv/bin/activate

python -c "
from data.database import get_sync_session
from data.pipeline import run_historical_load
with get_sync_session() as db:
    run_historical_load(db)
"
```

This downloads and ingests ~36,000 football matches from football-data.co.uk across 8 seasons and 12 leagues. It takes approximately 3–5 minutes.

After loading data, train the model:

```bash
python -c "
from data.database import get_sync_session
from ml.continuous_learner import retrain_sport
with get_sync_session() as db:
    result = retrain_sport(db, 'football')
    print(result)
"
```

Then rebuild Elo ratings from scratch (applies seasonal decay correctly):

```bash
python -c "
from data.database import get_sync_session
from features.elo import rebuild_elo
with get_sync_session() as db:
    rebuild_elo(db, 'football')
"
```

---

## Background Jobs (Scheduler)

The scheduler starts automatically when the server starts. Jobs run in background threads.

| Job                    | Interval              | What it does                                          |
|------------------------|-----------------------|-------------------------------------------------------|
| `job_live_scores`      | Every 60 seconds      | Fetches live match scores from ESPN                   |
| `job_fetch_intelligence` | Every 30 minutes    | Scrapes news → Gemini NLP → injury/suspension signals |
| `job_fetch_lineups`    | Every 1 hour          | API-Football pre-match lineups for PLAY picks        |
| `job_run_predictions`  | Every 3 hours         | Runs ML model on all upcoming matches                 |
| `job_fetch_news`       | Every 3 hours         | Fetches news articles, rewrites with Gemini           |
| `job_fetch_odds`       | Every 6 hours         | Updates odds from Sportybet + Odds API                |
| `job_resolve_matches`  | Every 2 hours         | Marks finished matches, logs performance              |
| `job_daily_decisions`  | Daily 08:00 UTC       | Decision engine + smart sets + sends email            |
| `job_retrain_models`   | Weekly Sunday 03:00   | Full model retrain on all accumulated data            |

---

## API Routes

All routes are prefixed `/api/v1/`.

### Predictions & Decisions
| Endpoint                                  | Description                              |
|-------------------------------------------|------------------------------------------|
| `GET /matches/upcoming`                   | Upcoming matches with predictions        |
| `GET /decisions/daily`                    | Today's PLAY picks with confidence       |
| `GET /decisions/smart-sets`               | Today's curated 10-match sets            |
| `POST /decisions/analytics/trigger-retrain` | Trigger immediate model retraining     |
| `GET /decisions/analytics/system`         | System health snapshot                   |

### Analytics Dashboard
| Endpoint                             | Description                                    |
|--------------------------------------|------------------------------------------------|
| `GET /analytics/overview`            | KPI snapshot — accuracy, ROI, picks, signals   |
| `GET /analytics/accuracy-timeline`   | Rolling accuracy over time (daily, 90 days)    |
| `GET /analytics/roi-timeline`        | Cumulative P&L over time                       |
| `GET /analytics/market-performance`  | Accuracy + ROI by market (1X2, BTTS, O/U)     |
| `GET /analytics/league-performance`  | Accuracy + ROI by competition                  |
| `GET /analytics/calibration`         | Calibration curve data                         |
| `GET /analytics/feature-importance`  | XGBoost top-20 feature importance              |
| `GET /analytics/signals-feed`        | Recent intelligence signals + daily volume     |
| `GET /analytics/confidence-histogram`| Confidence score distribution                  |
| `GET /analytics/model-health`        | Model files, training history, data freshness  |

### Teams & Players (ESPN CDN, no API key)
| Endpoint                                | Description                            |
|-----------------------------------------|----------------------------------------|
| `GET /teams/{league_slug}/{team_id}`    | Team profile + standings               |
| `GET /teams/{league_slug}/{team_id}/schedule` | Upcoming fixture + recent results |
| `GET /teams/{league_slug}/{team_id}/squad`    | Squad list                        |
| `GET /teams/{league_slug}/{team_id}/news`     | Team-related articles             |
| `GET /players/soccer/{player_id}`       | Player bio + stats + career           |
| `GET /players/soccer/{player_id}/news`  | Player-related articles               |
| `GET /players/soccer/search`            | Search players by name (ESPN)         |

### News & Intelligence
| Endpoint                    | Description                            |
|-----------------------------|----------------------------------------|
| `GET /news/`                | Paginated news feed                    |
| `GET /news/{slug}`          | Single article                         |
| `GET /standings/{slug}`     | League standings with team IDs         |
| `GET /sports/live`          | Live match scores                      |

---

## Project Structure

```
backend/
├── api/
│   ├── main.py                  # FastAPI app entry point + lifespan
│   └── routes/
│       ├── analytics.py         # Intelligence dashboard API
│       ├── decisions.py         # PLAY/SKIP decisions + smart sets
│       ├── matches.py           # Match data + live scores
│       ├── news.py              # News feed
│       ├── standings.py         # League tables
│       ├── teams.py             # Team + player profiles (ESPN)
│       └── predictions.py      # Raw prediction data
├── betting/
│   ├── decision_engine.py      # PLAY/SKIP logic + smart sets
│   └── value_engine.py         # EV + Kelly staking
├── config/
│   └── settings.py             # Pydantic settings from .env
├── data/
│   ├── database.py             # SQLAlchemy engine + session factory
│   ├── pipeline.py             # Core ingest function
│   ├── live_scores.py          # ESPN live score fetcher
│   ├── live_bus.py             # SSE event bus for live scores
│   ├── db_models/
│   │   └── models.py           # All SQLAlchemy ORM models
│   ├── loaders/
│   │   ├── football_csv.py     # football-data.co.uk historical loader
│   │   ├── api_football.py     # API-Football client (lineups, xG)
│   │   └── nba_loader.py       # NBA stats API loader
│   └── sources/
│       ├── sportybet.py        # Sportybet odds scraper
│       └── odds_api.py         # The Odds API client
├── features/
│   ├── engineering.py          # All 50 feature computations
│   ├── elo.py                  # Elo ratings + seasonal decay
│   └── poisson.py              # Dixon-Coles Poisson model
├── intelligence/
│   ├── news_writer.py          # News scraper + Gemini rewriter
│   └── signals.py              # Intelligence signal extraction
├── ml/
│   ├── continuous_learner.py   # Weekly retrain pipeline
│   ├── models/
│   │   └── sport_model.py      # XGBoost + LightGBM + calibration
│   └── saved/                  # Trained model .pkl files
├── mailer/
│   └── daily_email.py          # Daily picks email
├── scheduler.py                # APScheduler job definitions
└── requirements.txt
```

---

## Database Models

| Table                  | Purpose                                           |
|------------------------|---------------------------------------------------|
| `sports`               | Sport registry (football, basketball, etc.)       |
| `competitions`         | Leagues and tournaments                           |
| `participants`         | Teams (and individual athletes for tennis)        |
| `matches`              | Match fixtures + results + extra_data (shots)     |
| `match_odds`           | Bookmaker odds snapshots per match                |
| `predictions`          | ML model probability outputs per match            |
| `match_decisions`      | PLAY/SKIP decisions with confidence scores        |
| `smart_sets`           | Daily curated 10-match sets                       |
| `performance_logs`     | Resolved pick outcomes for ROI tracking           |
| `intelligence_signals` | Injury/suspension/morale signals from news        |
| `model_training_logs`  | History of every retraining run                   |
| `news_articles`        | Scraped + AI-rewritten news articles              |
| `optimization_weights` | Per-competition confidence adjustment weights     |

---

## Troubleshooting

**Server won't start:**
Check that the venv is activated and all requirements are installed.

**No predictions appearing:**
The model needs to be trained first. Run `retrain_sport(db, 'football')`.

**Predictions not resolving:**
The resolve job runs every 2 hours. Force it: `job_resolve_matches()` in scheduler.py.

**Gemini NLP not working:**
Set `GEMINI_API_KEY` in `.env`. Without it, news and intelligence jobs are skipped (not errors).

**Empty analytics dashboard:**
Accumulate resolved picks first. Analytics requires 50+ resolved PLAY picks to show meaningful data.
