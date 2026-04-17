# Sports AI Predictor — Claude Context

## What this app is
Sports AI predictor showing match predictions, live scores, standings, fixtures, and smart bet picks across 10+ sports. Built by Henry (hoorayhenry). Goal: public launch.

## Stack
- **Backend**: Python, FastAPI, SQLAlchemy (async), PostgreSQL, APScheduler
- **Frontend**: React + TypeScript, Vite, Tailwind CSS, React Query
- **ML**: Custom sport models in `backend/ml/`
- **Intelligence**: News scraping + Gemini Flash NLP in `backend/intelligence/`
- **Scheduler**: `backend/scheduler.py` — drives all periodic data fetches

## Data Sources

### ESPN (`site.api.espn.com`) — server-side via backend
Used for major European football leagues and cup competitions:
Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Primeira Liga, Eredivisie, Süper Lig, Scottish Prem, Pro League, MLS, Brasileirão, Liga Profesional, Liga BetPlay, Liga MX, UCL, UEL, UECL.
Handled in `backend/api/routes/standings.py`.

### Sofascore (`api.sofascore.com`) — BROWSER-DIRECT from frontend
Used for everything ESPN doesn't cover well:
- Football: World Cup, AFCON, Copa América
- Basketball: NBA, EuroLeague, ACB, WNBA
- NFL, NCAA Football, NHL, KHL, SHL, MLB, NPB
- Cricket: IPL, T20 World Cup, Ashes, SA20, BBL
- Rugby, Tennis (all 4 Slams), Handball, Volleyball, MMA

**Why browser-direct?** Python httpx has a different TLS fingerprint than a browser → Sofascore returns 403 server-side. Browser's native TLS passes bot detection. Sofascore has `access-control-allow-origin: *` so browser calls are allowed.

**No automatic fallback between sources.** Each league is hard-coded to one source.

## Caching Strategy
**Core rule: user refresh must NOT trigger a direct Sofascore call. The system drives all Sofascore fetches.**

| Data | staleTime | Notes |
|---|---|---|
| ESPN standings (current season) | 10 min | |
| ESPN standings (historical) | 30 days | |
| ESPN / SS fixtures | 24 hours | Set once per day |
| ESPN / SS leaders | 24 hours | |
| SS teams | 24 hours | |
| SS seasons | 7 days | |
| Live scores cache | 20 seconds | Scheduler-driven, adaptive |

Global React Query: `refetchOnWindowFocus: false`, `refetchOnReconnect: false`.
All Sofascore queries spread `_noRefetch = { refetchOnWindowFocus: false, refetchOnReconnect: false }`.

Live scores: APScheduler updates cache every **20s** when live matches exist, **5min** otherwise.

## Key Architectural Decisions
- Sofascore moved to browser-direct calls (2026-04-17) — fixes TLS fingerprint 403
- `"odds": []` not `{}` on orphan fixtures — fixes React crash (`filter is not a function`)
- Dropdown `onMouseDown={e => e.stopPropagation()}` — fixes click race condition where document handler closed dropdown before click fired
- Live score count: shared `_LIVE_CACHE` dict in scheduler, both navbar and Live page read same cache

## Paid API Assessment (2026-04-17)
- Sportradar: $2k-10k+/month — enterprise only
- No affordable API covers all sports + all leagues + unlimited requests
- Decision: stay on ESPN + Sofascore until $500+/month revenue, then revisit Sportradar startup tier

## Deferred Work (build app first)
- API schema drift detection: fingerprint response keys every 6hr in scheduler, alert via email/Discord when structure changes. Frontend: zero-row guard in normalisers.

## Running the app
```bash
# Backend
cd backend && uvicorn api.main:app --reload

# Frontend
cd frontend && npm run dev
```
