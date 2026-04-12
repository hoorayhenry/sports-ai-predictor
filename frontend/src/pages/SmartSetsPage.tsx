import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Target, ChevronDown, ChevronUp, RefreshCw } from "lucide-react";
import { fetchSmartSets, triggerDecisionsNow } from "../api/client";
import Spinner from "../components/Spinner";
import { formatDate, outcomeShort, probTagColor } from "../utils/format";
import type { SmartSet, SmartSetMatch } from "../api/types";
import { Link } from "react-router-dom";

export default function SmartSetsPage() {
  const { data: sets = [], isLoading, refetch } = useQuery({
    queryKey: ["smart-sets"],
    queryFn: () => fetchSmartSets(),
    staleTime: 60_000,
  });

  const runNow = useMutation({
    mutationFn: () => triggerDecisionsNow(false),
    onSuccess: () => setTimeout(() => refetch(), 3000),
  });

  const playCount = sets.reduce(
    (s, set) => s + set.matches.filter((m) => m.ai_decision === "PLAY").length,
    0
  );

  return (
    <div className="min-h-screen pb-20 md:pb-6 px-4 pt-6">
      {/* Header */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-3">
          <div className="bg-purple-500/20 p-2 rounded-xl">
            <Target size={20} className="text-purple-400" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">Smart Sets</h2>
            <p className="text-xs text-slate-400">10 curated 10-match packages for today</p>
          </div>
        </div>
        <button
          onClick={() => runNow.mutate()}
          disabled={runNow.isPending}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors border border-slate-700 rounded-xl px-3 py-2"
        >
          <RefreshCw size={13} className={runNow.isPending ? "animate-spin" : ""} />
          Regenerate
        </button>
      </div>

      {/* Summary strip */}
      {sets.length > 0 && (
        <div className="flex gap-3 mb-4 mt-4">
          <StatPill label="Sets" value={sets.length} />
          <StatPill label="PLAY picks" value={playCount} color="text-green-400" />
          <StatPill label="Avg conf"
            value={`${(sets.reduce((s,x) => s + x.overall_confidence, 0) / sets.length).toFixed(0)}`}
            color="text-sky-400" />
        </div>
      )}

      {isLoading ? (
        <div className="flex justify-center py-20"><Spinner size={40} /></div>
      ) : sets.length === 0 ? (
        <div className="text-center py-20 text-slate-500">
          <p className="text-5xl mb-4">🎯</p>
          <p>No Smart Sets generated yet.</p>
          <button onClick={() => runNow.mutate()} className="btn-primary mt-4 text-sm">
            Generate Now
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {sets.map((set) => (
            <SmartSetCard key={set.id} set={set} />
          ))}
        </div>
      )}
    </div>
  );
}

function StatPill({ label, value, color = "text-white" }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="card px-3 py-2 text-center">
      <p className="text-[10px] text-slate-500 uppercase tracking-wide">{label}</p>
      <p className={`font-bold ${color}`}>{value}</p>
    </div>
  );
}

function SmartSetCard({ set }: { set: SmartSet }) {
  const [expanded, setExpanded] = useState(set.set_number === 1);
  const confColor =
    set.overall_confidence >= 75 ? "text-green-400" :
    set.overall_confidence >= 60 ? "text-yellow-400" : "text-red-400";
  const riskBg =
    set.risk_level === "HIGH" ? "bg-green-500/15 text-green-400" :
    set.risk_level === "MEDIUM" ? "bg-yellow-500/15 text-yellow-400" :
    "bg-red-500/15 text-red-400";

  return (
    <div className="card overflow-hidden">
      {/* Set header */}
      <button
        className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-slate-700/20 transition-colors"
        onClick={() => setExpanded((e) => !e)}
      >
        {/* Set number */}
        <div className="w-9 h-9 rounded-xl bg-purple-500/20 flex items-center justify-center shrink-0">
          <span className="text-purple-400 font-bold text-sm">#{set.set_number}</span>
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-lg font-bold ${confColor}`}>
              {set.overall_confidence.toFixed(0)}
            </span>
            <span className="text-slate-500 text-xs">confidence</span>
            <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${riskBg}`}>
              {set.risk_level}
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            {set.match_count} matches • Combined prob: {(set.combined_probability * 100).toFixed(2)}%
            {set.wins + set.losses > 0 && ` • ${set.wins}W/${set.losses}L`}
          </p>
        </div>

        <div className="text-slate-500 shrink-0">
          {expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
        </div>
      </button>

      {/* Matches table */}
      {expanded && (
        <div className="border-t border-slate-700/50">
          {set.matches.map((m, idx) => (
            <SmartSetMatchRow key={m.match_id} match={m} idx={idx} />
          ))}
          {/* Combined stats */}
          <div className="px-4 py-2 bg-slate-800/50 flex items-center gap-4 text-xs text-slate-400">
            <span>Combined prob: <span className="text-white font-medium">{(set.combined_probability * 100).toFixed(3)}%</span></span>
            <span>Avg odds: <span className="text-yellow-300 font-medium">{set.avg_odds.toFixed(2)}</span></span>
          </div>
        </div>
      )}
    </div>
  );
}

function SmartSetMatchRow({ match: m, idx }: { match: SmartSetMatch; idx: number }) {
  const { dot } = probTagColor(m.prob_tag);
  return (
    <Link to={`/match/${m.match_id}`}>
      <div className={`flex items-center gap-3 px-4 py-2.5 hover:bg-slate-700/20 transition-colors border-b border-slate-700/30 last:border-0 ${idx % 2 === 0 ? "" : "bg-slate-800/20"}`}>
        <span className="text-xs text-slate-600 w-4">{idx + 1}</span>
        <span className="text-sm">{m.sport_icon}</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-white truncate">
            {m.home_team} <span className="text-slate-500">vs</span> {m.away_team}
          </p>
          <p className="text-[11px] text-slate-500 truncate">{m.competition} • {formatDate(m.match_date)}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-sky-400 font-medium">{outcomeShort(m.predicted_outcome)}</span>
          <span className="text-[11px] text-slate-400">{dot} {Math.round(m.top_prob * 100)}%</span>
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
            m.ai_decision === "PLAY"
              ? "bg-green-500/15 text-green-400"
              : "bg-red-500/15 text-red-400"
          }`}>
            {m.ai_decision === "PLAY" ? "✅" : "❌"}
          </span>
        </div>
      </div>
    </Link>
  );
}
