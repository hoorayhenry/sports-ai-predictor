import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Flame, RefreshCw } from "lucide-react";
import { fetchDailyPicks, fetchSports, triggerDecisionsNow } from "../api/client";
import SportTabs from "../components/SportTabs";
import Spinner from "../components/Spinner";
import { formatDate, probTagColor, outcomeShort } from "../utils/format";
import { Link } from "react-router-dom";
import type { MatchDecision } from "../api/types";

export default function DailyPicksPage() {
  const [sport, setSport] = useState("all");

  const { data: sports = [] } = useQuery({
    queryKey: ["sports"],
    queryFn: fetchSports,
    staleTime: 60_000,
  });

  const { data: picks = [], isLoading, refetch } = useQuery({
    queryKey: ["daily-picks", sport],
    queryFn: () => fetchDailyPicks(sport === "all" ? undefined : sport),
    staleTime: 30_000,
  });

  const runNow = useMutation({
    mutationFn: () => triggerDecisionsNow(false),
    onSuccess: () => setTimeout(() => refetch(), 3000),
  });

  const playPicks = picks.filter((p) => p.ai_decision === "PLAY");

  return (
    <div className="min-h-screen pb-20 md:pb-6 px-4 pt-6">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="bg-orange-500/20 p-2 rounded-xl">
              <Flame size={20} className="text-orange-400" />
            </div>
            <h2 className="text-xl font-bold text-white">AI Daily Picks</h2>
          </div>
          <p className="text-xs text-slate-400 ml-11">
            Next 7 days — top {playPicks.length} plays ranked by confidence
          </p>
        </div>
        <button
          onClick={() => runNow.mutate()}
          disabled={runNow.isPending}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors border border-slate-700 rounded-xl px-3 py-2"
        >
          <RefreshCw size={13} className={runNow.isPending ? "animate-spin" : ""} />
          {runNow.isPending ? "Running..." : "Refresh AI"}
        </button>
      </div>

      {/* Legend */}
      <div className="flex gap-3 mb-4 text-xs">
        {[
          { label: "✅ PLAY — clear, high-confidence pick", color: "text-green-400" },
          { label: "🟢 HIGH ≥75%", color: "text-green-400" },
          { label: "🟡 MEDIUM 60-74%", color: "text-yellow-400" },
          { label: "🔴 RISKY <60%", color: "text-red-400" },
        ].map(({ label, color }) => (
          <span key={label} className={`${color} hidden sm:inline`}>{label}</span>
        ))}
      </div>

      <div className="mb-4">
        <SportTabs sports={sports} selected={sport} onSelect={setSport} />
      </div>

      {isLoading ? (
        <div className="flex justify-center py-20"><Spinner size={40} /></div>
      ) : picks.length === 0 ? (
        <div className="text-center py-20 text-slate-500">
          <p className="text-5xl mb-4">🔥</p>
          <p>No picks yet for today.</p>
          <button onClick={() => runNow.mutate()} className="btn-primary mt-4 text-sm">
            Run AI Now
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {picks.map((pick, idx) => (
            <DailyPickRow key={pick.match_id} pick={pick} rank={idx + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

function DailyPickRow({ pick, rank }: { pick: MatchDecision; rank: number }) {
  const { dot, text } = probTagColor(pick.prob_tag);
  const isPlay = pick.ai_decision === "PLAY";
  const confColor =
    pick.confidence_score >= 75 ? "text-green-400" :
    pick.confidence_score >= 60 ? "text-yellow-400" : "text-red-400";

  return (
    <Link to={`/match/${pick.match_id}`}>
      <div className={`card p-4 transition-all hover:border-sky-500/30 ${isPlay ? "border-green-500/30" : "border-slate-700/30 opacity-70"}`}>
        <div className="flex items-center gap-3">
          {/* Rank */}
          <div className="w-7 h-7 rounded-full bg-slate-700/50 flex items-center justify-center shrink-0">
            <span className="text-xs font-bold text-slate-300">#{rank}</span>
          </div>

          {/* Match info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1 text-[11px] text-slate-500 mb-0.5">
              <span>{pick.sport_icon}</span>
              <span className="truncate">{pick.competition}</span>
              <span className="ml-auto shrink-0">{formatDate(pick.match_date)}</span>
            </div>
            <p className="font-semibold text-sm">
              <span className="text-white">{pick.home_team}</span>
              <span className="text-slate-500 mx-1">vs</span>
              <span className="text-white">{pick.away_team}</span>
            </p>
          </div>

          {/* Right col: confidence + pick + decision */}
          <div className="flex flex-col items-end gap-1 shrink-0">
            <div className={`text-xl font-bold ${confColor}`}>
              {Math.round(pick.confidence_score)}
            </div>
            <span className={`text-[11px] font-semibold ${text}`}>
              {dot} {outcomeShort(pick.predicted_outcome)} • {Math.round(pick.top_prob * 100)}%
            </span>
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
              isPlay ? "bg-green-500/15 text-green-400" : "bg-red-500/15 text-red-400"
            }`}>
              {isPlay ? "✅ PLAY" : "❌ SKIP"}
            </span>
          </div>
        </div>

        {/* Score breakdown bar */}
        {pick.score_breakdown && (
          <div className="mt-3 grid grid-cols-4 gap-1">
            {[
              { label: "Prob", val: pick.score_breakdown.probability, max: 40 },
              { label: "EV",   val: pick.score_breakdown.expected_value, max: 20 },
              { label: "Form", val: pick.score_breakdown.form, max: 20 },
              { label: "Hist", val: pick.score_breakdown.consistency, max: 20 },
            ].map(({ label, val, max }) => (
              <div key={label}>
                <div className="flex justify-between text-[10px] text-slate-500 mb-0.5">
                  <span>{label}</span>
                  <span>{val.toFixed(0)}</span>
                </div>
                <div className="h-1 bg-slate-700 rounded-full">
                  <div
                    className="h-1 bg-sky-500 rounded-full"
                    style={{ width: `${Math.min(100, (val / max) * 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Odds + stake */}
        {pick.recommended_odds && (
          <div className="mt-2 flex gap-3 text-xs text-slate-400">
            <span>Best odds: <span className="text-yellow-300 font-semibold">{pick.recommended_odds.toFixed(2)}</span></span>
            {pick.recommended_stake_pct && (
              <span>Kelly stake: <span className="text-sky-300 font-semibold">{(pick.recommended_stake_pct * 100).toFixed(1)}%</span></span>
            )}
            {pick.has_volatility && (
              <span className="text-yellow-500/80 ml-auto">⚠ Volatile</span>
            )}
          </div>
        )}
      </div>
    </Link>
  );
}
