import { Link } from "react-router-dom";
import { Zap, AlertTriangle } from "lucide-react";
import type { Match } from "../api/types";
import type { MatchDecision } from "../api/types";
import { formatDate, outcomeLabel, probTagColor, outcomeShort } from "../utils/format";

interface Props {
  match?: Match;
  decision?: MatchDecision;
}

function ProbBar({ home, draw, away }: { home: number; draw?: number; away: number }) {
  const h = Math.round(home * 100);
  const d = draw ? Math.round(draw * 100) : 0;
  const a = Math.round(away * 100);
  return (
    <div className="mt-3">
      <div className="flex rounded-full overflow-hidden h-2 bg-slate-700">
        <div className="bg-sky-500 transition-all" style={{ width: `${h}%` }} />
        {d > 0 && <div className="bg-slate-400 transition-all" style={{ width: `${d}%` }} />}
        <div className="bg-orange-500 transition-all" style={{ width: `${a}%` }} />
      </div>
      <div className="flex justify-between text-[11px] mt-1">
        <span className="text-sky-400 font-medium">{h}%</span>
        {d > 0 && <span className="text-slate-400">{d}%</span>}
        <span className="text-orange-400 font-medium">{a}%</span>
      </div>
    </div>
  );
}

function ConfidenceRing({ score }: { score: number }) {
  const color =
    score >= 75 ? "#4ade80" : score >= 60 ? "#facc15" : "#f87171";
  return (
    <div className="flex flex-col items-center justify-center w-10 h-10 rounded-full border-2 shrink-0"
      style={{ borderColor: color }}>
      <span className="text-xs font-bold" style={{ color }}>{Math.round(score)}</span>
    </div>
  );
}

function PlaySkipBadge({ decision }: { decision: "PLAY" | "SKIP" }) {
  const isPlay = decision === "PLAY";
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold border ${
      isPlay
        ? "bg-green-500/15 border-green-500/40 text-green-400"
        : "bg-red-500/15 border-red-500/40 text-red-400"
    }`}>
      {isPlay ? "✅ PLAY" : "❌ SKIP"}
    </span>
  );
}

function ProbTagBadge({ tag }: { tag: string }) {
  const { bg, text, dot } = probTagColor(tag);
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold ${bg} ${text}`}>
      {dot} {tag}
    </span>
  );
}

export default function MatchCard({ match, decision: dec }: Props) {
  // Support both Match and MatchDecision shapes
  const id          = match?.id ?? dec?.match_id;
  const homeTeam    = match?.home_team ?? dec?.home_team ?? "TBD";
  const awayTeam    = match?.away_team ?? dec?.away_team ?? "TBD";
  const competition = match?.competition ?? dec?.competition ?? "";
  const sportIcon   = match?.sport_icon ?? dec?.sport_icon ?? "🏆";
  const matchDate   = match?.match_date ?? dec?.match_date ?? "";
  const status      = match?.status ?? dec?.status ?? "scheduled";
  const homeScore   = match?.home_score;
  const awayScore   = match?.away_score;

  const pred        = match?.prediction;
  const aiDecision  = dec?.ai_decision ?? (pred ? undefined : undefined);
  const confScore   = dec?.confidence_score;
  const probTag     = dec?.prob_tag;
  const _topProb    = dec?.top_prob ?? (pred?.home_win_prob ?? 0); void _topProb;
  const predOutcome = dec?.predicted_outcome ?? pred?.predicted_result;
  const hasVolat    = dec?.has_volatility;
  const isValueBet  = pred?.is_value_bet ?? dec?.is_value_bet ?? false;
  const ev          = pred?.expected_value ?? dec?.expected_value;

  // Best H2H odds from match
  const h2hOdds = match?.odds?.filter((o) => o.market === "h2h") ?? [];
  const bestHome = Math.max(0, ...h2hOdds.filter((o) => o.outcome === "home").map((o) => o.price));
  const bestDraw = Math.max(0, ...h2hOdds.filter((o) => o.outcome === "draw").map((o) => o.price));
  const bestAway = Math.max(0, ...h2hOdds.filter((o) => o.outcome === "away").map((o) => o.price));

  const homeProb  = pred?.home_win_prob ?? dec?.home_win_prob ?? null;
  const drawProb  = pred?.draw_prob     ?? dec?.draw_prob     ?? null;
  const awayProb  = pred?.away_win_prob ?? dec?.away_win_prob ?? null;
  const over25    = pred?.over25_prob   ?? dec?.over25_prob   ?? null;
  const btts      = pred?.btts_prob     ?? dec?.btts_prob     ?? null;

  const highlightBorder =
    aiDecision === "PLAY"  ? "border-green-500/40"  :
    isValueBet             ? "border-yellow-500/40" :
    "";

  return (
    <Link to={`/match/${id}`}>
      <div className={`card p-4 hover:border-sky-500/40 transition-all cursor-pointer relative ${highlightBorder}`}>

        {/* Header row */}
        <div className="flex items-center gap-2 text-xs text-slate-500 mb-3">
          <span>{sportIcon}</span>
          <span className="truncate">{competition}</span>
          <span className="ml-auto shrink-0 text-slate-600">{formatDate(matchDate)}</span>
        </div>

        {/* Main content: teams + confidence ring + odds */}
        <div className="flex items-center gap-2">
          {/* Home */}
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-sm truncate">{homeTeam}</p>
            {bestHome > 0 && <p className="text-xs text-slate-400 mt-0.5">{bestHome.toFixed(2)}</p>}
          </div>

          {/* VS / Score / Confidence */}
          <div className="flex flex-col items-center shrink-0 gap-1">
            {status === "finished" && homeScore != null ? (
              <span className="text-lg font-bold">{homeScore} – {awayScore}</span>
            ) : (
              <>
                {confScore != null
                  ? <ConfidenceRing score={confScore} />
                  : <span className="text-slate-500 text-xs font-medium">VS</span>
                }
                {bestDraw > 0 && <span className="text-[11px] text-slate-500">{bestDraw.toFixed(2)}</span>}
              </>
            )}
          </div>

          {/* Away */}
          <div className="flex-1 min-w-0 text-right">
            <p className="font-semibold text-sm truncate">{awayTeam}</p>
            {bestAway > 0 && <p className="text-xs text-slate-400 mt-0.5">{bestAway.toFixed(2)}</p>}
          </div>
        </div>

        {/* Probability bar */}
        {homeProb != null && (
          <ProbBar home={homeProb} draw={drawProb ?? undefined} away={awayProb ?? 0} />
        )}

        {/* Badge row */}
        <div className="mt-3 flex items-center gap-2 flex-wrap">
          {aiDecision && <PlaySkipBadge decision={aiDecision} />}
          {probTag    && <ProbTagBadge  tag={probTag} />}
          {predOutcome && (
            <span className="text-xs text-slate-300 font-medium">
              Pick: <span className="text-sky-400">{outcomeShort(predOutcome)}</span>
            </span>
          )}
          {hasVolat && (
            <span className="ml-auto flex items-center gap-1 text-[11px] text-yellow-500/80">
              <AlertTriangle size={11} /> Volatile
            </span>
          )}
          {isValueBet && !hasVolat && (
            <span className="ml-auto flex items-center gap-1 text-[11px] text-yellow-400">
              <Zap size={11} /> Value
            </span>
          )}
        </div>

        {/* Value bet details */}
        {isValueBet && pred?.value_outcome && (
          <div className="mt-2 flex items-center gap-2 text-xs">
            <span className="bg-yellow-500/10 text-yellow-300 border border-yellow-500/30 px-2 py-0.5 rounded-full font-medium">
              {outcomeLabel(pred.value_market!, pred.value_outcome)} @ {pred.value_odds?.toFixed(2)}
            </span>
            {ev != null && (
              <span className="text-green-400 font-semibold">+{(ev * 100).toFixed(1)}% EV</span>
            )}
          </div>
        )}

        {/* Side markets */}
        {(over25 != null || btts != null) && (
          <div className="mt-2 flex gap-3 text-xs text-slate-400">
            {over25 != null && (
              <span>O2.5 <span className="text-slate-200 font-medium">{Math.round(over25 * 100)}%</span></span>
            )}
            {btts != null && (
              <span>BTTS <span className="text-slate-200 font-medium">{Math.round(btts * 100)}%</span></span>
            )}
            {confScore != null && (
              <span className="ml-auto">Conf <span className="text-slate-200 font-medium">{Math.round(confScore)}</span></span>
            )}
          </div>
        )}
      </div>
    </Link>
  );
}
