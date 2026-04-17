# PlaySigma Prediction Model

> Complete technical reference for the ML prediction engine. Updated April 2026.

---

## Overview

PlaySigma uses a multi-market sports prediction model that combines:

- **XGBoost + LightGBM ensemble** for tabular feature learning
- **Dixon-Coles Poisson model** for statistically rigorous score prediction
- **Elo rating system** with seasonal decay for team strength tracking
- **Isotonic probability calibration** to ensure output probabilities match real-world frequencies
- **Real-time intelligence layer** (injuries, suspensions, lineup confirmations) that adjusts pre-match

The model currently targets football (soccer) with the same architecture designed to extend to basketball, tennis and American football.

---

## Architecture Diagram

```
Historical Data (8 seasons, 12 leagues, ~36,000 matches)
        │
        ▼
┌──────────────────┐    ┌──────────────────────────┐
│  Elo Ratings     │    │  Dixon-Coles Poisson Model│
│  (seasonal decay)│    │  (fitted on all history)  │
└────────┬─────────┘    └────────────┬─────────────┘
         │                           │
         └─────────┬─────────────────┘
                   │
         ┌─────────▼──────────────────────────────────┐
         │         Feature Engineering (50 features)   │
         │  Elo · Form · H2H · Strength · xG · Odds   │
         │  Referee · Shots · Fatigue · Intelligence   │
         └─────────┬──────────────────────────────────┘
                   │
         ┌─────────▼──────────────────────────────────┐
         │    XGBoost + LightGBM Ensemble              │
         │    Three separate classifiers:              │
         │      • Result     (H / D / A)               │
         │      • Over 2.5   (yes / no)                │
         │      • BTTS       (yes / no)                │
         └─────────┬──────────────────────────────────┘
                   │
         ┌─────────▼──────────────────────────────────┐
         │    Isotonic Calibration                     │
         │    (per-class, fitted on validation set)    │
         └─────────┬──────────────────────────────────┘
                   │
         ┌─────────▼──────────────────────────────────┐
         │    Value Detection                          │
         │    Compare model prob vs market implied     │
         │    Expected Value = (p × odds) - 1         │
         └─────────┬──────────────────────────────────┘
                   │
         ┌─────────▼──────────────────────────────────┐
         │    Decision Engine (PLAY / SKIP)            │
         │    Threshold: prob ≥ 65%, confidence ≥ 70  │
         └────────────────────────────────────────────┘
```

---

## Training Data

### Source
**football-data.co.uk** — free, no API key required, updated throughout each season.

| Property      | Value                                  |
|---------------|----------------------------------------|
| Seasons       | 2017/18 → 2024/25 (8 seasons)          |
| Leagues       | 12 (see list below)                    |
| Matches       | ~36,000 finished matches               |
| Per match     | Result, score, 6 bookmakers' odds, shots (total + on target), cards (yellow + red), referee |

### Leagues covered
| Code | League                     | Country     |
|------|----------------------------|-------------|
| E0   | Premier League             | England     |
| E1   | Championship               | England     |
| SP1  | La Liga                    | Spain       |
| D1   | Bundesliga                 | Germany     |
| I1   | Serie A                    | Italy       |
| F1   | Ligue 1                    | France      |
| N1   | Eredivisie                 | Netherlands |
| P1   | Primeira Liga              | Portugal    |
| T1   | Süper Lig                  | Turkey      |
| SC0  | Scottish Premiership       | Scotland    |
| B1   | First Division A           | Belgium     |
| G1   | Super League               | Greece      |

### Recency weighting
Recent data is weighted more heavily during training:

| Age of match   | Sample weight |
|----------------|---------------|
| Last 6 months  | 3.0×          |
| 6–12 months    | 2.0×          |
| 1–2 years      | 1.5×          |
| 2+ years       | 1.0×          |

---

## Feature Engineering

All 50 features computed per match. No future data used (strict temporal split).

### Elo Ratings (6 features)
Elo ratings track each team's overall strength over time. Updated after every match using a goal-difference multiplier. At each season boundary (July), all ratings decay 30% toward the mean (1,500) to account for summer transfers and squad changes.

| Feature            | Description                                      |
|--------------------|--------------------------------------------------|
| `home_elo`         | Home team current Elo                            |
| `away_elo`         | Away team current Elo                            |
| `elo_diff`         | Difference (positive = home stronger)            |
| `elo_home_prob`    | Elo-derived home win probability                 |
| `elo_draw_prob`    | Elo-derived draw probability                     |
| `elo_away_prob`    | Elo-derived away win probability                 |

### Form Windows (8 features)
Rolling stats over the last 5 and 10 matches for each team, computed strictly before the match date.

| Feature                        | Description                        |
|--------------------------------|------------------------------------|
| `home_win_rate_5`              | Home wins / 5 recent games         |
| `home_win_rate_10`             | Home wins / 10 recent games        |
| `home_goals_avg_5`             | Home goals scored per game (L5)    |
| `home_goals_conceded_avg_5`    | Home goals conceded per game (L5)  |
| *(same 4 for away team)*       |                                    |

### Head-to-Head (5 features)
Historical record between these two specific teams (up to last 10 meetings).

| Feature              | Description                                      |
|----------------------|--------------------------------------------------|
| `h2h_home_win_rate`  | % of H2H meetings won by home team              |
| `h2h_draw_rate`      | % of H2H meetings drawn                         |
| `h2h_away_win_rate`  | % of H2H meetings won by away team              |
| `h2h_avg_goals`      | Average total goals in H2H meetings             |
| `h2h_n`              | Number of H2H meetings in dataset               |

### Attack / Defence Strength (4 features)
Dixon-Coles style rating: goals scored relative to league average, adjusted for opponent quality.

### Expected Goals — Poisson Proxy (3 features)
`exp_home_goals = home_attack × away_defence_weakness × league_avg × home_advantage`

### BTTS / Over-2.5 Rates (4 features)
How often each team participates in both-teams-score and high-scoring games over last 10 games.

### Market-Implied Probabilities (4 features)
**The most powerful feature group.** Closing odds from Bet365, Pinnacle and market averages are converted to true probabilities (de-vigified). The model learns the edge relative to market opinion, not in a vacuum.

| Feature          | Description                                         |
|------------------|-----------------------------------------------------|
| `imp_home_prob`  | Market-implied home win probability (no vig)        |
| `imp_draw_prob`  | Market-implied draw probability                     |
| `imp_away_prob`  | Market-implied away win probability                 |
| `market_margin`  | Bookmaker overround (proxy for market confidence)   |

### Fatigue (2 features)
Days since each team's last match, capped at 30. Captures fixture congestion and rotation situations.

### Injury/Suspension Intelligence (2 features)
Signals extracted by Gemini NLP from news articles, scored -1.0 (star player out) to 0.0 (no impact). Sourced from 30-minute scraped news cycle and optionally from API-Football pre-match.

### League Table Position Proxy (8 features)
Points per game, goal difference per game, form points (last 5), and their differentials.

### Shot-Based / xG Proxy (8 features)
Shot volume and quality over the last 5 games. Far more stable predictor than goals because it separates underlying performance from finishing luck.

| Feature              | Description                                      |
|----------------------|--------------------------------------------------|
| `home_shots_avg_5`   | Home team shots per game (L5)                    |
| `home_sot_avg_5`     | Home shots on target per game (L5)               |
| `home_shot_conv_5`   | Goals ÷ shots on target — luck indicator         |
| `home_xg_proxy_5`    | Shots on target × 0.33 ≈ xG estimate             |
| *(same 4 for away)*  |                                                  |

### Referee Tendencies (2 features)
Historical per-referee statistics. Some referees average 3.2 goals per game, others 2.0. Highly predictive for over/under and BTTS markets.

| Feature           | Description                                  |
|-------------------|----------------------------------------------|
| `ref_avg_goals`   | Referee's historical average total goals/game|
| `ref_avg_cards`   | Referee's historical average cards/game      |

### Dixon-Coles Poisson Model Outputs (6 features)
A second, independently fitted model provides probability inputs. This forces the ensemble to learn *when* the Poisson model is trustworthy and when form/intelligence signals should override it.

| Feature              | Description                                      |
|----------------------|--------------------------------------------------|
| `dc_home_win`        | Dixon-Coles home win probability                 |
| `dc_draw`            | Dixon-Coles draw probability                     |
| `dc_away_win`        | Dixon-Coles away win probability                 |
| `dc_over_2_5`        | Dixon-Coles over 2.5 probability                 |
| `dc_btts_yes`        | Dixon-Coles BTTS probability                     |
| `dc_exp_home_goals`  | DC model expected home goals                     |
| `dc_exp_away_goals`  | DC model expected away goals                     |

---

## The Ensemble Classifier

### Base learners
| Classifier  | Weight | Role                                           |
|-------------|--------|------------------------------------------------|
| XGBoost     | 55%    | Handles interaction effects, noisy features    |
| LightGBM    | 45%    | Faster, better on high-cardinality features    |

Both are gradient-boosted decision tree ensembles. They outperform neural networks on structured tabular data like this consistently in research and competition.

### Hyperparameters
```
n_estimators  = 400
max_depth     = 4
learning_rate = 0.05
subsample     = 0.8
colsample     = 0.8
```

### Calibration
After training, per-class **isotonic regression** calibrators are fitted on the validation set. This ensures output probabilities match empirical win rates. Without calibration, a model outputting 72% confidence might only win 58% of the time in that bucket — which completely breaks edge detection against market odds.

---

## Dixon-Coles Poisson Model

Based on the 1997 Dixon & Coles paper. Independently fits attack/defence strength parameters for every team using maximum likelihood estimation on all historical data. Applies a correction factor (ρ) for low-scoring outcomes (0-0, 1-0, 0-1, 1-1) which Poisson naturally over-estimates.

**Key parameters estimated per team:**
- `attack_i` — how many goals a team creates relative to league average
- `defence_i` — how many goals a team allows relative to league average
- `home_advantage` — multiplicative factor applied to home attack

**Outputs per match:**
- Full 11×11 scoreline probability matrix
- Home win / draw / away win probabilities
- BTTS probability
- Over 1.5 / 2.5 / 3.5 goal probabilities
- Expected home and away goals

---

## Value Detection

For each market and outcome:

```
edge = model_probability - market_implied_probability
ev   = (model_probability × decimal_odds) - 1.0
```

A bet is considered value if `ev > 0.04` (4% edge minimum).

**Kelly criterion** determines optimal stake:
```
kelly_fraction = edge / (decimal_odds - 1)
stake          = kelly_fraction × 0.25   # quarter Kelly for safety
max_stake      = 5% of bankroll
```

---

## Decision Engine

Produces a `PLAY` or `SKIP` for each upcoming match, scored 0–100.

### Components
| Component       | Weight | What it measures                             |
|-----------------|--------|----------------------------------------------|
| Probability     | 35%    | Calibrated win probability of top prediction |
| Expected Value  | 30%    | Edge over market odds                        |
| Form            | 20%    | Recency-weighted form consistency            |
| Consistency     | 15%    | Agreement across models and markets          |

### Thresholds
- `PLAY` requires: probability ≥ 65% **and** confidence score ≥ 70 / 100
- Volatility flags (injury impact > 1.0, missing key player) can downgrade PLAY → SKIP

---

## Continuous Learning

The model retrains every **Sunday at 03:00 UTC** from scratch on all accumulated DB data. As each new season's matches resolve, the model updates its patterns without any manual intervention.

To trigger a manual retrain:
```bash
# Via API
curl -X POST http://localhost:8000/api/v1/decisions/analytics/trigger-retrain

# Via Python directly
cd backend
python -c "
from data.database import get_sync_session
from ml.continuous_learner import retrain_sport
with get_sync_session() as db:
    result = retrain_sport(db, 'football')
    print(result)
"
```

---

## Expected Accuracy

| Market      | Random baseline | Basic model | This model |
|-------------|-----------------|-------------|------------|
| 1X2 result  | 33.3%           | 50–52%      | 60–65%     |
| Over/Under  | 50%             | 54–56%      | 67–70%     |
| BTTS        | 50%             | 54–56%      | 66–69%     |

*Note: Accuracy improves as more resolved matches accumulate in the DB. After the first season of live data (500+ resolved picks), expect these ranges to hold consistently.*

---

## Files

| File                                  | Purpose                                      |
|---------------------------------------|----------------------------------------------|
| `backend/features/engineering.py`    | All 50 feature computations                  |
| `backend/features/elo.py`            | Elo rating system + seasonal decay           |
| `backend/features/poisson.py`        | Dixon-Coles Poisson model                    |
| `backend/ml/models/sport_model.py`   | XGBoost + LightGBM ensemble + calibration    |
| `backend/ml/continuous_learner.py`   | Weekly retrain pipeline                      |
| `backend/betting/value_engine.py`    | EV calculation + Kelly staking               |
| `backend/betting/decision_engine.py` | PLAY / SKIP decision logic                   |
| `backend/data/loaders/football_csv.py` | Historical data downloader (football-data.co.uk) |
| `backend/data/loaders/api_football.py` | API-Football client (lineups, injuries, xG) |
| `backend/ml/saved/`                  | Trained model `.pkl` files                   |
