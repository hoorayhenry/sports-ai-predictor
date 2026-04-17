import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Zap } from "lucide-react";
import { fetchMatch } from "../api/client";
import Spinner from "../components/Spinner";
import { formatDate, outcomeLabel, confidenceColor, pct, resultLabel } from "../utils/format";
import type { Odds } from "../api/types";

export default function MatchDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: match, isLoading } = useQuery({
    queryKey: ["match", id],
    queryFn: () => fetchMatch(Number(id)),
    enabled: !!id,
  });

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <Spinner size={48} />
      </div>
    );
  }

  if (!match) {
    return (
      <div className="flex justify-center items-center min-h-screen text-slate-400">
        Match not found.
      </div>
    );
  }

  const pred = match.prediction;
  const h2hOdds = match.odds.filter((o) => o.market === "h2h");
  const totalsOdds = match.odds.filter((o) => o.market === "totals");
  const bttsOdds = match.odds.filter((o) => o.market === "btts");

  return (
    <div className="min-h-screen pb-20 md:pb-6">
      {/* Top bar */}
      <div className="sticky top-0 z-10 navbar-glass px-4 py-3 flex items-center gap-3">
        <Link to="/" className="text-slate-400 hover:text-white transition-colors">
          <ArrowLeft size={20} />
        </Link>
        <div className="min-w-0">
          <p className="text-xs text-slate-500 truncate">
            {match.sport_icon} {match.competition}
          </p>
          <p className="text-sm font-semibold truncate">
            {match.home_team} vs {match.away_team}
          </p>
        </div>
        <p className="ml-auto text-xs text-slate-500 shrink-0">{formatDate(match.match_date)}</p>
      </div>

      <div className="px-4 pt-6 space-y-4">
        {/* Scoreboard */}
        <div className="card p-6 text-center">
          {match.status === "finished" && match.home_score != null ? (
            <>
              <div className="text-5xl font-bold mb-2">
                {match.home_score} – {match.away_score}
              </div>
              <p className="text-slate-400 text-sm">{resultLabel(match.result)}</p>
            </>
          ) : (
            <p className="text-slate-400 text-sm uppercase tracking-wider">{match.status}</p>
          )}
          <div className="flex justify-between items-start mt-4">
            <div className="flex-1 text-left">
              <p className="font-bold text-lg">{match.home_team}</p>
              <p className="text-xs text-slate-500">ELO {Math.round(match.home_elo)}</p>
            </div>
            <div className="text-slate-600 font-bold">VS</div>
            <div className="flex-1 text-right">
              <p className="font-bold text-lg">{match.away_team}</p>
              <p className="text-xs text-slate-500">ELO {Math.round(match.away_elo)}</p>
            </div>
          </div>
        </div>

        {/* Prediction card */}
        {pred && (
          <div className={`card p-4 ${pred.is_value_bet ? "border-yellow-500/40" : ""}`}>
            <div className="flex items-center gap-2 mb-4">
              <h3 className="font-semibold font-display">Prediction</h3>
              {pred.is_value_bet && (
                <span className="flex items-center gap-1 bg-yellow-500/20 text-yellow-400 text-xs px-2 py-0.5 rounded-full font-semibold">
                  <Zap size={11} /> Value Bet
                </span>
              )}
            </div>

            {/* Result probs */}
            {pred.home_win_prob != null && (
              <div className="space-y-2 mb-4">
                <ProbRow label={match.home_team} prob={pred.home_win_prob} color="sky" />
                {pred.draw_prob != null && pred.draw_prob > 0 && (
                  <ProbRow label="Draw" prob={pred.draw_prob} color="slate" />
                )}
                <ProbRow label={match.away_team} prob={pred.away_win_prob ?? 0} color="orange" />
              </div>
            )}

            {/* Side markets */}
            <div className="grid grid-cols-2 gap-3 mb-4">
              {pred.over25_prob != null && (
                <div className="bg-[#0f172a] rounded-xl p-3">
                  <p className="text-xs text-slate-400 mb-1">Over 2.5 Goals</p>
                  <p className="text-xl font-bold text-white">{pct(pred.over25_prob)}</p>
                  <div className="h-1 rounded-full bg-slate-700 mt-2">
                    <div
                      className="h-1 rounded-full bg-purple-500"
                      style={{ width: pct(pred.over25_prob) }}
                    />
                  </div>
                </div>
              )}
              {pred.btts_prob != null && (
                <div className="bg-[#0f172a] rounded-xl p-3">
                  <p className="text-xs text-slate-400 mb-1">Both Teams Score</p>
                  <p className="text-xl font-bold text-white">{pct(pred.btts_prob)}</p>
                  <div className="h-1 rounded-full bg-slate-700 mt-2">
                    <div
                      className="h-1 rounded-full bg-green-500"
                      style={{ width: pct(pred.btts_prob) }}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Value bet detail */}
            {pred.is_value_bet && pred.value_outcome && (
              <div className="bg-yellow-500/5 border border-yellow-500/30 rounded-xl p-4">
                <p className="text-xs text-yellow-400/70 font-semibold uppercase tracking-wider mb-2">Value Bet</p>
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="font-bold text-white">
                    {outcomeLabel(pred.value_market!, pred.value_outcome)}
                  </span>
                  <span className="text-xl font-bold text-yellow-300">@ {pred.value_odds?.toFixed(2)}</span>
                </div>
                <div className="flex gap-4 mt-2 text-sm">
                  <div>
                    <p className="text-slate-400 text-xs">Expected Value</p>
                    <p className="text-green-400 font-bold">+{((pred.expected_value ?? 0) * 100).toFixed(1)}%</p>
                  </div>
                  <div>
                    <p className="text-slate-400 text-xs">Kelly Stake</p>
                    <p className="text-sky-400 font-bold">{((pred.kelly_stake ?? 0) * 100).toFixed(1)}% bankroll</p>
                  </div>
                  {pred.confidence && (
                    <div className="ml-auto">
                      <p className="text-slate-400 text-xs">Confidence</p>
                      <p className={`font-bold ${confidenceColor(pred.confidence)}`}>
                        {pred.confidence.toUpperCase()}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Odds comparison */}
        {h2hOdds.length > 0 && (
          <OddsTable title="Match Result Odds (1X2)" odds={h2hOdds} />
        )}
        {totalsOdds.length > 0 && (
          <OddsTable title="Totals" odds={totalsOdds} />
        )}
        {bttsOdds.length > 0 && (
          <OddsTable title="Both Teams To Score" odds={bttsOdds} />
        )}
      </div>
    </div>
  );
}

function ProbRow({ label, prob, color }: { label: string; prob: number; color: string }) {
  const colors: Record<string, string> = {
    sky: "bg-sky-500",
    slate: "bg-slate-400",
    orange: "bg-orange-500",
  };
  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-slate-300 w-28 truncate">{label}</span>
      <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-2 rounded-full ${colors[color] || "bg-sky-500"} transition-all`}
          style={{ width: `${Math.round(prob * 100)}%` }}
        />
      </div>
      <span className="text-sm font-semibold text-white w-10 text-right">
        {Math.round(prob * 100)}%
      </span>
    </div>
  );
}

function OddsTable({ title, odds }: { title: string; odds: Odds[] }) {
  // Group by bookmaker, deduplicate
  const byBookmaker: Record<string, Odds[]> = {};
  for (const o of odds) {
    if (!byBookmaker[o.bookmaker]) byBookmaker[o.bookmaker] = [];
    const exists = byBookmaker[o.bookmaker].find((x) => x.outcome === o.outcome);
    if (!exists || exists.price < o.price) {
      byBookmaker[o.bookmaker] = byBookmaker[o.bookmaker].filter((x) => x.outcome !== o.outcome);
      byBookmaker[o.bookmaker].push(o);
    }
  }

  const outcomes = [...new Set(odds.map((o) => o.outcome))];
  const bookmakers = Object.keys(byBookmaker);

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-700/50">
        <h3 className="font-semibold text-sm">{title}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="text-left px-4 py-2 text-slate-500 font-medium text-xs">Bookmaker</th>
              {outcomes.map((o) => (
                <th key={o} className="text-right px-3 py-2 text-slate-500 font-medium text-xs capitalize">
                  {o}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bookmakers.map((bm, i) => (
              <tr key={bm} className={i % 2 === 0 ? "bg-[#1a2744]/30" : ""}>
                <td className="px-4 py-2.5 text-slate-300 capitalize font-medium text-xs">{bm}</td>
                {outcomes.map((out) => {
                  const entry = byBookmaker[bm]?.find((o) => o.outcome === out);
                  return (
                    <td key={out} className="px-3 py-2.5 text-right font-semibold">
                      {entry ? (
                        <span className="text-white">{entry.price.toFixed(2)}</span>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
