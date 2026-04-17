import { Link } from "react-router-dom";
import { Zap, AlertTriangle, Newspaper } from "lucide-react";
import type { Match, MatchDecision, IntelligenceSignal } from "../api/types";
import { formatDate, outcomeLabel, outcomeShort } from "../utils/format";

interface Props {
  match?: Match;
  decision?: MatchDecision;
}

// ── Probability bar with gradient fills ────────────────────────
function ProbBar({ home, draw, away }: { home: number; draw?: number; away: number }) {
  const h = Math.round(home * 100);
  const d = draw ? Math.round(draw * 100) : 0;
  const a = Math.round(away * 100);
  return (
    <div className="mt-3">
      <div className="flex rounded-full overflow-hidden h-1.5 bg-pi-surface gap-px">
        <div
          className="transition-all duration-500"
          style={{ width: `${h}%`, background: "linear-gradient(90deg, #38bdf8, #818cf8)" }}
        />
        {d > 0 && (
          <div className="bg-pi-muted/50 transition-all duration-500" style={{ width: `${d}%` }} />
        )}
        <div
          className="transition-all duration-500"
          style={{ width: `${a}%`, background: "linear-gradient(90deg, #f59e0b, #f43f5e)" }}
        />
      </div>
      <div className="flex justify-between text-[11px] mt-1.5">
        <span className="text-pi-sky font-semibold">{h}%</span>
        {d > 0 && <span className="text-pi-muted">{d}%</span>}
        <span className="text-amber-400 font-semibold">{a}%</span>
      </div>
    </div>
  );
}

// ── Confidence ring with color coding ──────────────────────────
function ConfidenceRing({ score }: { score: number }) {
  const cls =
    score >= 75 ? "conf-ring-high" :
    score >= 60 ? "conf-ring-medium" :
                  "conf-ring-low";
  return (
    <div className={`flex flex-col items-center justify-center w-10 h-10 rounded-full border-2 shrink-0 ${cls} shadow-sm`}>
      <span className="text-[11px] font-bold leading-none">{Math.round(score)}</span>
    </div>
  );
}

// ── PLAY / SKIP badge ───────────────────────────────────────────
function PlaySkipBadge({ decision }: { decision: "PLAY" | "SKIP" }) {
  return decision === "PLAY" ? (
    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold
      bg-pi-emerald/15 border border-pi-emerald/40 text-emerald-400">
      ▶ PLAY
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold
      bg-pi-rose/10 border border-pi-rose/30 text-rose-400">
      ✕ SKIP
    </span>
  );
}

// ── Probability tag badge ───────────────────────────────────────
function ProbTagBadge({ tag }: { tag: string }) {
  const styles: Record<string, string> = {
    HIGH:   "bg-emerald-500/12 border-emerald-500/35 text-emerald-400",
    MEDIUM: "bg-amber-500/12 border-amber-500/35 text-amber-400",
    RISKY:  "bg-rose-500/10 border-rose-500/30 text-rose-400",
  };
  const dots: Record<string, string> = { HIGH: "🟢", MEDIUM: "🟡", RISKY: "🔴" };
  const cls = styles[tag] ?? styles.RISKY;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold border ${cls}`}>
      {dots[tag] ?? "🔴"} {tag}
    </span>
  );
}

// ── Intelligence signal badges ──────────────────────────────────
function IntelligenceBadges({ signals }: { signals: IntelligenceSignal[] }) {
  if (!signals.length) return null;
  const icons: Record<string, string> = {
    injury: "🤕", suspension: "🟥", return: "✅", morale: "💬", lineup: "📋",
  };
  return (
    <div className="flex flex-wrap gap-1">
      {signals.slice(0, 4).map((s, i) => (
        <span
          key={i}
          className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border ${
            s.impact < 0
              ? "bg-rose-500/8 border-rose-500/25 text-rose-300"
              : "bg-emerald-500/8 border-emerald-500/25 text-emerald-300"
          }`}
        >
          {icons[s.type] ?? "📰"} {s.player ?? s.team}
        </span>
      ))}
      {signals.length > 4 && (
        <span className="text-[11px] text-pi-muted">+{signals.length - 4} more</span>
      )}
    </div>
  );
}

// ── Main card ───────────────────────────────────────────────────
export default function MatchCard({ match, decision: dec }: Props) {
  const id          = match?.id ?? dec?.match_id;
  const homeTeam    = match?.home_team ?? dec?.home_team ?? "TBD";
  const awayTeam    = match?.away_team ?? dec?.away_team ?? "TBD";
  const competition = match?.competition ?? dec?.competition ?? "";
  const sportIcon   = match?.sport_icon ?? dec?.sport_icon ?? "🏆";
  const matchDate   = match?.match_date ?? dec?.match_date ?? "";
  const status      = match?.status ?? dec?.status ?? "scheduled";
  const homeScore   = match?.home_score;
  const awayScore   = match?.away_score;
  const liveMinute  = match?.live_minute;

  const pred        = match?.prediction;
  const aiDecision  = dec?.ai_decision;
  const confScore   = dec?.confidence_score;
  const probTag     = dec?.prob_tag;
  const predOutcome = dec?.predicted_outcome ?? pred?.predicted_result;
  const hasVolat    = dec?.has_volatility;
  const isValueBet  = pred?.is_value_bet ?? dec?.is_value_bet ?? false;
  const ev          = pred?.expected_value ?? dec?.expected_value;

  const h2hOdds = match?.odds?.filter((o) => o.market === "h2h") ?? [];
  const bestHome = Math.max(0, ...h2hOdds.filter((o) => o.outcome === "home").map((o) => o.price));
  const bestDraw = Math.max(0, ...h2hOdds.filter((o) => o.outcome === "draw").map((o) => o.price));
  const bestAway = Math.max(0, ...h2hOdds.filter((o) => o.outcome === "away").map((o) => o.price));

  const homeProb = pred?.home_win_prob ?? dec?.home_win_prob ?? null;
  const drawProb = pred?.draw_prob     ?? dec?.draw_prob     ?? null;
  const awayProb = pred?.away_win_prob ?? dec?.away_win_prob ?? null;
  const over25   = pred?.over25_prob   ?? dec?.over25_prob   ?? null;
  const btts     = pred?.btts_prob     ?? dec?.btts_prob     ?? null;

  const signals  = match?.intelligence?.signals ?? [];

  // Card variant class
  const cardClass =
    aiDecision === "PLAY" ? "card card-play" :
    isValueBet            ? "card card-value" :
                            "card";

  return (
    <Link to={`/match/${id}`} className="block h-full animate-fade-up">
      <div className={`${cardClass} p-4 cursor-pointer flex flex-col h-full`}>

        {/* Accent stripe */}
        <div className="h-0.5 -mx-4 -mt-4 mb-3 rounded-t-[14px]" style={{
          background: aiDecision === "PLAY"
            ? "linear-gradient(90deg, #10b981, #059669)"
            : isValueBet
            ? "linear-gradient(90deg, #f59e0b, #d97706)"
            : "linear-gradient(90deg, #6366f1, #8b5cf6)"
        }} />

        {/* Header: competition + date */}
        <div className="flex items-center gap-2 text-xs text-pi-muted mb-3">
          <span className="text-base leading-none">{sportIcon}</span>
          <span className="truncate font-medium">{competition}</span>
          {status === "live" ? (
            <span className="ml-auto shrink-0 flex items-center gap-1 text-rose-400 font-bold text-[10px] px-1.5 py-0.5 rounded-full bg-rose-500/10 border border-rose-500/25">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-400 animate-pulse inline-block" />
              LIVE
            </span>
          ) : (
            <span className="ml-auto shrink-0 text-pi-muted/70 tabular-nums">{formatDate(matchDate)}</span>
          )}
        </div>

        {/* Teams + confidence ring + odds */}
        <div className="flex items-center gap-3">

          {/* Home */}
          <div className="flex-1 min-w-0">
            <p className="font-bold text-[16px] text-pi-primary truncate font-display">{homeTeam}</p>
            {bestHome > 0 && (
              <p className="text-xs text-pi-muted mt-0.5 tabular-nums">{bestHome.toFixed(2)}</p>
            )}
          </div>

          {/* Centre: score or confidence ring */}
          <div className="flex flex-col items-center shrink-0 gap-1">
            {status === "live" && homeScore != null ? (
              <div className="flex flex-col items-center gap-0.5">
                <span className="text-lg font-bold font-display tabular-nums text-pi-primary">
                  {homeScore} – {awayScore}
                </span>
                <span className="flex items-center gap-1 text-[10px] font-bold text-rose-400">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-rose-400 animate-pulse" />
                  {liveMinute ? `${liveMinute}'` : "LIVE"}
                </span>
              </div>
            ) : status === "finished" && homeScore != null ? (
              <span className="text-lg font-bold font-display tabular-nums">
                {homeScore} – {awayScore}
              </span>
            ) : confScore != null ? (
              <ConfidenceRing score={confScore} />
            ) : (
              <span className="text-pi-muted text-xs font-medium">VS</span>
            )}
            {bestDraw > 0 && status !== "finished" && status !== "live" && (
              <span className="text-[11px] text-pi-muted tabular-nums">{bestDraw.toFixed(2)}</span>
            )}
          </div>

          {/* Away */}
          <div className="flex-1 min-w-0 text-right">
            <p className="font-bold text-[16px] text-pi-primary truncate font-display">{awayTeam}</p>
            {bestAway > 0 && (
              <p className="text-xs text-pi-muted mt-0.5 tabular-nums">{bestAway.toFixed(2)}</p>
            )}
          </div>
        </div>

        {/* Probability bar */}
        {homeProb != null && (
          <ProbBar home={homeProb} draw={drawProb ?? undefined} away={awayProb ?? 0} />
        )}

        {/* Double-chance markets */}
        {homeProb != null && drawProb != null && awayProb != null && (
          <div className="mt-2 flex gap-2 text-[11px]">
            <span className="bg-pi-surface/60 border border-pi-border/50 rounded px-2 py-0.5 text-pi-secondary">
              1X <span className="text-pi-primary font-semibold">{Math.round((homeProb + drawProb) * 100)}%</span>
            </span>
            <span className="bg-pi-surface/60 border border-pi-border/50 rounded px-2 py-0.5 text-pi-secondary">
              X2 <span className="text-pi-primary font-semibold">{Math.round((drawProb + awayProb) * 100)}%</span>
            </span>
            <span className="bg-pi-surface/60 border border-pi-border/50 rounded px-2 py-0.5 text-pi-secondary">
              12 <span className="text-pi-primary font-semibold">{Math.round((homeProb + awayProb) * 100)}%</span>
            </span>
          </div>
        )}

        {/* Badge row */}
        <div className="mt-3 flex items-center gap-2 flex-wrap">
          {aiDecision && <PlaySkipBadge decision={aiDecision} />}
          {probTag    && <ProbTagBadge  tag={probTag} />}
          {predOutcome && (
            <span className="text-xs text-pi-secondary">
              Pick: <span className="text-pi-indigo-light font-semibold">{outcomeShort(predOutcome)}</span>
            </span>
          )}
          {hasVolat && (
            <span className="ml-auto flex items-center gap-1 text-[11px] text-amber-500/80">
              <AlertTriangle size={10} /> Uncertain
            </span>
          )}
          {isValueBet && !hasVolat && (
            <span className="ml-auto flex items-center gap-1 text-[11px] text-amber-400 font-medium">
              <Zap size={10} /> Value
            </span>
          )}
        </div>

        {/* Value bet detail */}
        {isValueBet && pred?.value_outcome && (
          <div className="mt-2 flex items-center gap-2 text-xs">
            <span className="bg-amber-500/10 text-amber-300 border border-amber-500/25 px-2 py-0.5 rounded-full font-medium">
              {outcomeLabel(pred.value_market!, pred.value_outcome)} @ {pred.value_odds?.toFixed(2)}
            </span>
            {ev != null && (
              <span className="text-emerald-400 font-semibold">+{(ev * 100).toFixed(1)}% edge</span>
            )}
          </div>
        )}

        {/* Side market probabilities */}
        {(over25 != null || btts != null) && (
          <div className="mt-2.5 pt-2.5 border-t border-pi-border/50 flex gap-3 text-xs text-pi-muted">
            {over25 != null && (
              <span>
                O2.5 <span className="text-pi-primary font-semibold tabular-nums">{Math.round(over25 * 100)}%</span>
              </span>
            )}
            {btts != null && (
              <span>
                BTTS <span className="text-pi-primary font-semibold tabular-nums">{Math.round(btts * 100)}%</span>
              </span>
            )}
            {confScore != null && (
              <span className="ml-auto text-pi-muted/70">
                Conf <span className="text-pi-secondary font-medium">{Math.round(confScore)}</span>
              </span>
            )}
          </div>
        )}

        {/* Intelligence signals */}
        {signals.length > 0 && (
          <div className="mt-2.5 pt-2.5 border-t border-pi-border/50">
            <div className="flex items-center gap-1 text-[10px] text-pi-muted mb-1.5 section-label">
              <Newspaper size={9} /> Intel
            </div>
            <IntelligenceBadges signals={signals} />
          </div>
        )}

        {/* When no predictions available — show odds panel or pending state */}
        {homeProb == null && (
          <div className="mt-3 pt-3 border-t border-pi-border/30">
            {(bestHome > 0 || bestAway > 0) ? (
              <div className="flex gap-2 text-[11px]">
                {bestHome > 0 && (
                  <div className="flex-1 bg-pi-surface/60 border border-pi-border/50 rounded-lg px-2 py-1.5 text-center">
                    <p className="text-pi-muted mb-0.5">Home Win</p>
                    <p className="font-bold text-pi-primary tabular-nums">{bestHome.toFixed(2)}</p>
                  </div>
                )}
                {bestDraw > 0 && (
                  <div className="flex-1 bg-pi-surface/60 border border-pi-border/50 rounded-lg px-2 py-1.5 text-center">
                    <p className="text-pi-muted mb-0.5">Draw</p>
                    <p className="font-bold text-pi-primary tabular-nums">{bestDraw.toFixed(2)}</p>
                  </div>
                )}
                {bestAway > 0 && (
                  <div className="flex-1 bg-pi-surface/60 border border-pi-border/50 rounded-lg px-2 py-1.5 text-center">
                    <p className="text-pi-muted mb-0.5">Away Win</p>
                    <p className="font-bold text-pi-primary tabular-nums">{bestAway.toFixed(2)}</p>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex items-center gap-1.5 text-[11px] text-pi-muted/60">
                <span className="w-1.5 h-1.5 rounded-full bg-pi-muted/30 inline-block" />
                Analysis pending
              </div>
            )}
          </div>
        )}

        {/* Spacer to equalise card heights in grid */}
        <div className="flex-1" />

      </div>
    </Link>
  );
}
