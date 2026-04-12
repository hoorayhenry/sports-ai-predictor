import { Link } from "react-router-dom";
import { Zap } from "lucide-react";
import type { Match } from "../api/types";
import { formatDate, outcomeLabel, confidenceColor } from "../utils/format";

interface Props {
  match: Match;
}

function ProbBar({
  homeProb,
  drawProb,
  awayProb,
}: {
  homeProb: number;
  drawProb?: number;
  awayProb: number;
}) {
  const hp = Math.round((homeProb ?? 0) * 100);
  const dp = drawProb ? Math.round(drawProb * 100) : 0;
  const ap = Math.round((awayProb ?? 0) * 100);
  return (
    <div className="mt-3">
      <div className="flex rounded-full overflow-hidden h-2 bg-slate-700">
        <div className="bg-sky-500 transition-all" style={{ width: `${hp}%` }} />
        {dp > 0 && <div className="bg-slate-500 transition-all" style={{ width: `${dp}%` }} />}
        <div className="bg-orange-500 transition-all" style={{ width: `${ap}%` }} />
      </div>
      <div className="flex justify-between text-[11px] text-slate-400 mt-1">
        <span className="text-sky-400 font-medium">{hp}%</span>
        {dp > 0 && <span className="text-slate-400">{dp}%</span>}
        <span className="text-orange-400 font-medium">{ap}%</span>
      </div>
    </div>
  );
}

export default function MatchCard({ match }: Props) {
  const pred = match.prediction;
  const hasValue = pred?.is_value_bet;

  // Best h2h odds
  const h2hOdds = match.odds.filter((o) => o.market === "h2h");
  const bestHome = Math.max(0, ...h2hOdds.filter((o) => o.outcome === "home").map((o) => o.price));
  const bestDraw = Math.max(0, ...h2hOdds.filter((o) => o.outcome === "draw").map((o) => o.price));
  const bestAway = Math.max(0, ...h2hOdds.filter((o) => o.outcome === "away").map((o) => o.price));

  return (
    <Link to={`/match/${match.id}`}>
      <div
        className={`card p-4 hover:border-sky-500/40 transition-all cursor-pointer relative ${
          hasValue ? "border-yellow-500/40" : ""
        }`}
      >
        {/* Value bet badge */}
        {hasValue && (
          <div className="absolute top-3 right-3 flex items-center gap-1 bg-yellow-500/20 text-yellow-400 text-xs font-semibold px-2 py-0.5 rounded-full">
            <Zap size={11} />
            <span>Value</span>
          </div>
        )}

        {/* Header */}
        <div className="flex items-center gap-2 text-xs text-slate-500 mb-3">
          <span>{match.sport_icon}</span>
          <span className="truncate">{match.competition}</span>
          {match.country && <span className="text-slate-600">· {match.country}</span>}
          <span className="ml-auto shrink-0">{formatDate(match.match_date)}</span>
        </div>

        {/* Teams + odds */}
        <div className="flex items-center justify-between gap-2">
          {/* Home */}
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-sm truncate">{match.home_team}</p>
            {bestHome > 0 && (
              <p className="text-xs text-slate-400 mt-0.5">
                {bestHome.toFixed(2)}
              </p>
            )}
          </div>

          {/* VS / Score */}
          <div className="flex flex-col items-center shrink-0 px-2">
            {match.status === "finished" && match.home_score != null ? (
              <span className="text-lg font-bold">
                {match.home_score} – {match.away_score}
              </span>
            ) : (
              <>
                <span className="text-slate-500 text-xs font-medium">VS</span>
                {bestDraw > 0 && (
                  <span className="text-xs text-slate-400 mt-0.5">{bestDraw.toFixed(2)}</span>
                )}
              </>
            )}
          </div>

          {/* Away */}
          <div className="flex-1 min-w-0 text-right">
            <p className="font-semibold text-sm truncate">{match.away_team}</p>
            {bestAway > 0 && (
              <p className="text-xs text-slate-400 mt-0.5">
                {bestAway.toFixed(2)}
              </p>
            )}
          </div>
        </div>

        {/* Probability bar */}
        {pred?.home_win_prob != null && (
          <ProbBar
            homeProb={pred.home_win_prob}
            drawProb={pred.draw_prob ?? undefined}
            awayProb={pred.away_win_prob ?? 0}
          />
        )}

        {/* Value bet info */}
        {hasValue && pred?.value_outcome && (
          <div className="mt-3 flex items-center gap-2 text-xs">
            <span className="bg-yellow-500/10 text-yellow-300 border border-yellow-500/30 px-2 py-0.5 rounded-full font-medium">
              {outcomeLabel(pred.value_market!, pred.value_outcome)} @ {pred.value_odds?.toFixed(2)}
            </span>
            <span className="text-green-400 font-semibold">
              +{((pred.expected_value ?? 0) * 100).toFixed(1)}% EV
            </span>
            {pred.confidence && (
              <span className={`font-medium ${confidenceColor(pred.confidence)}`}>
                {pred.confidence.toUpperCase()}
              </span>
            )}
          </div>
        )}

        {/* Side markets */}
        {pred && (pred.over25_prob != null || pred.btts_prob != null) && (
          <div className="mt-2 flex gap-3 text-xs text-slate-400">
            {pred.over25_prob != null && (
              <span>
                O2.5 <span className="text-slate-200 font-medium">{Math.round(pred.over25_prob * 100)}%</span>
              </span>
            )}
            {pred.btts_prob != null && (
              <span>
                BTTS <span className="text-slate-200 font-medium">{Math.round(pred.btts_prob * 100)}%</span>
              </span>
            )}
          </div>
        )}
      </div>
    </Link>
  );
}
