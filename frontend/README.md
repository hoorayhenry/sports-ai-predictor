# PlaySigma Frontend

React + TypeScript + Tailwind CSS interface for the PlaySigma sports intelligence platform.

---

## Stack

| Component       | Technology                           |
|-----------------|--------------------------------------|
| Framework       | React 19 + TypeScript                |
| Routing         | React Router v7                      |
| Data fetching   | TanStack Query v5                    |
| Charts          | Recharts 3                           |
| Styling         | Tailwind CSS v3                      |
| Icons           | Lucide React                         |
| HTTP client     | Axios                                |
| Build tool      | Vite                                 |

---

## Prerequisites

- Node.js 18+
- npm 9+

---

## Setup

```bash
cd frontend
npm install
```

---

## Environment Variables

Create `frontend/.env`:

```env
VITE_API_URL=http://localhost:8000/api/v1
```

For production, point this to your deployed backend URL.

---

## Running

```bash
# Development server (hot reload)
npm run dev
# → http://localhost:5173

# Type check
npx tsc --noEmit

# Production build
npm run build
# Output in frontend/dist/

# Preview production build locally
npm run preview
```

---

## Pages

### Core prediction pages

| Route             | Page               | Description                                          |
|-------------------|--------------------|------------------------------------------------------|
| `/`               | Home               | Featured picks, live scores strip, news highlights   |
| `/picks`          | Daily Picks        | All PLAY decisions with confidence + probability     |
| `/sets`           | Smart Sets         | Curated 10-match sets generated daily by the AI      |
| `/match/:id`      | Match Detail       | Individual match deep-dive with all prediction data  |

### Intelligence & analytics

| Route             | Page               | Description                                          |
|-------------------|--------------------|------------------------------------------------------|
| `/analytics`      | Intelligence Dash  | Full Grafana-style model observability dashboard     |
| `/news`           | News               | AI-rewritten football news with smart interlinking   |
| `/live`           | Live               | Real-time match scores (SSE, updates every 60s)     |

### Exploration

| Route                          | Page           | Description                                    |
|--------------------------------|----------------|------------------------------------------------|
| `/tables`                      | Standings      | League tables (click row → team profile)       |
| `/team/:leagueSlug/:teamId`    | Team Profile   | Livescore-style: Overview/Results/Squad/News   |
| `/player/soccer/:playerId`     | Player Profile | Bio/Stats/News with headshot + career history  |
| `/player/search`               | Player Search  | ESPN player search with auto-redirect          |

### History & performance

| Route             | Page               | Description                                          |
|-------------------|--------------------|------------------------------------------------------|
| `/performance`    | Performance        | Win rate, ROI, resolved picks history                |
| `/history`        | History            | Full prediction log with outcomes                    |

---

## Project Structure

```
frontend/
├── public/
│   └── favicon.svg
├── src/
│   ├── api/
│   │   ├── client.ts          # Axios instance + base URL
│   │   └── types.ts           # Shared TypeScript types
│   ├── assets/
│   │   └── playsigma-logo.svg
│   ├── components/
│   │   ├── Footer.tsx         # Bottom nav (mobile) + desktop footer
│   │   ├── Navbar.tsx         # Top navigation bar
│   │   ├── MatchCard.tsx      # Match card used on picks + home page
│   │   └── Spinner.tsx        # Loading spinner
│   └── pages/
│       ├── AnalyticsPage.tsx  # Intelligence dashboard (Grafana-style)
│       ├── DailyPicksPage.tsx # PLAY picks
│       ├── HistoryPage.tsx    # Prediction history
│       ├── HomePage.tsx       # Landing / dashboard
│       ├── LivePage.tsx       # Live scores
│       ├── MatchDetailPage.tsx
│       ├── NewsPage.tsx       # News feed with smart tag linking
│       ├── PerformancePage.tsx
│       ├── PlayerDetailPage.tsx
│       ├── PlayerSearchPage.tsx
│       ├── PredictionsPage.tsx
│       ├── SmartSetsPage.tsx
│       ├── StandingsPage.tsx  # Clickable league tables
│       └── TeamDetailPage.tsx # Full team profile
├── index.html
├── package.json
├── tailwind.config.js
├── tsconfig.json
└── vite.config.ts
```

---

## Key Design Decisions

### Dark theme
The app uses a deep navy dark theme (`#070c19` base). All Tailwind colours are defined as CSS variables in `src/index.css`:
- `--pi-primary`, `--pi-secondary`, `--pi-muted` — text colours
- `--pi-surface`, `--pi-border` — card backgrounds and borders
- `--pi-indigo`, `--pi-emerald`, `--pi-amber`, `--pi-rose` — accent colours

### ESPN CDN for images
Team logos and player headshots are served directly from ESPN's CDN — no API key required:
- Logos: `https://a.espncdn.com/i/teamlogos/soccer/500/{team_id}.png`
- Headshots: `https://a.espncdn.com/i/headshots/soccer/players/full/{player_id}.png`

Headshots are only available for ~10% of soccer players. For the rest, a shirt-number fallback displays on a position-coloured background (Goalkeeper=amber, Defender=blue, Midfielder=green, Forward=rose).

### Smart news interlinking
The news feed auto-detects team and player names in article body text and converts them to clickable links using `linkifyParagraph()`. Known clubs navigate to their standings slug; multi-word names navigate to the player search page. This creates a navigable web of content without any manual tagging.

### Live scores (SSE)
The live page uses Server-Sent Events for real-time score updates. The backend pushes an event when scores change (polled from ESPN every 60 seconds). No WebSocket dependency.

### Caching strategy (TanStack Query)
| Data type          | Stale time  | Reason                                  |
|--------------------|-------------|-----------------------------------------|
| Live scores        | 30s         | Changes frequently during matches       |
| Match predictions  | 60s         | Updated every 3 hours by scheduler      |
| Team/player data   | 60s         | ESPN CDN, stable                        |
| Standings          | 60s         | Updated after each matchday             |
| Analytics          | 60–300s     | Heavy queries, acceptable staleness     |

---

## Analytics Dashboard (`/analytics`)

The operational intelligence centre for monitoring model performance. Shows:

1. **KPI strip** — accuracy, cumulative ROI, active picks, signal count, training data volume, last retrain time
2. **Accuracy timeline** — 14-day rolling accuracy plotted over 90 days with reference line at 55%
3. **ROI chart** — cumulative profit/loss in units over time (area chart)
4. **Market breakdown** — accuracy and ROI per market (1X2, Over/Under, BTTS) as horizontal bars
5. **League breakdown** — accuracy and ROI per competition with colour-coded bars
6. **Calibration curve** — predicted probability bucket vs actual win rate; perfect model = diagonal line
7. **Feature importance** — top 15 XGBoost features colour-coded by group (Elo, Market Odds, Shots/xG, etc.)
8. **Confidence histogram** — distribution of PLAY pick confidence scores
9. **PLAY/SKIP donut** — decision selectivity ratio
10. **Intelligence signals feed** — live injury/suspension signals with stacked daily volume chart
11. **Model health** — trained model files on disk, training history, data freshness date
12. **Automation schedule** — all background jobs and their cadence

All charts auto-refresh. Heavy charts (feature importance, calibration) refresh every 5 minutes. The KPI strip and signals feed refresh every minute.

---

## Tailwind Custom Classes

Defined in `tailwind.config.js` and used throughout:
- `.card` — dark glassmorphism card with border and subtle shadow
- `.btn-primary` — indigo filled button
- `.btn-secondary` — outlined secondary button
- `.section-label` — small all-caps section heading
- `.font-display` — display heading font (used for large numbers and headings)

---

## TypeScript

Strict mode is enabled. Run `npx tsc --noEmit` to type-check before committing.
The project targets ES2022 with React JSX transform (no `React` import needed).
