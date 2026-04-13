import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { History, CheckCircle2, XCircle, Minus } from "lucide-react";
import { fetchPredictionHistory, fetchSports } from "../api/client";
import SportTabs from "../components/SportTabs";
import Spinner from "../components/Spinner";
import { formatDate } from "../utils/format";
import type { PredictionHistory } from "../api/types";

const DAYS_OPTIONS = [7, 30, 60, 90];

export default function HistoryPage() {
  const [sport, setSport] = useState("all");
  const [days, setDays]   = useState(30);

  const { data: sports = [] } = useQuery({
    queryKey: ["sports"],
    queryFn:  fetchSports,
    staleTime: 60_000,
  });

  const { data: history = [], isLoading } = useQuery({
    queryKey: ["history", sport, days],
    queryFn:  () => fetchPredictionHistory({
      sport:    sport === "all" ? undefined : sport,
      days,
      decision: "PLAY",   // only show picks the AI actually made
      limit:    500,
    }),
    staleTime: 60_000,
  });

  const wins   = history.filter((h) => h.is_correct).length;
  const total  = history.length;
  const winPct = total > 0 ? Math.round((wins / total) * 100) : 0;
  const pnl    = history.reduce((s, h) => s + h.profit_loss_units, 0);

  return (
    <div className="min-h-screen pb-20 md:pb-6 px-4 pt-6">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="bg-purple-500/20 p-2 rounded-xl">
              <History size={20} className="text-purple-400" />
            </div>
            <h2 className="text-xl font-bold text-white">Prediction History</h2>
          </div>
          <p className="text-xs text-slate-400 ml-11">
            Every AI pick resolved with real match outcomes
          </p>
        </div>

        {/* Days filter */}
        <div className="flex gap-1">
          {DAYS_OPTIONS.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`text-xs px-2 py-1 rounded-lg transition-colors ${
                days === d
                  ? "bg-purple-600 text-white"
                  : "text-slate-400 hover:text-white border border-slate-700"
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* KPI strip */}
      {total > 0 && (
        <div className="grid grid-cols-4 gap-2 mb-5">
          {[
            { label: "Picks", value: total, color: "text-white" },
            { label: "Wins",  value: wins,  color: "text-green-400" },
            { label: "Win %", value: `${winPct}%`, color: winPct >= 55 ? "text-green-400" : winPct >= 45 ? "text-yellow-400" : "text-red-400" },
            { label: "P&L",   value: `${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}u`, color: pnl >= 0 ? "text-green-400" : "text-red-400" },
          ].map(({ label, value, color }) => (
            <div key={label} className="card p-3 text-center">
              <p className={`text-lg font-bold ${color}`}>{value}</p>
              <p className="text-[10px] text-slate-500 mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      )}

      <div className="mb-4">
        <SportTabs sports={sports} selected={sport} onSelect={setSport} />
      </div>

      {isLoading ? (
        <div className="flex justify-center py-20"><Spinner size={40} /></div>
      ) : history.length === 0 ? (
        <div className="text-center py-20 text-slate-500">
          <p className="text-5xl mb-4">📊</p>
          <p className="text-sm">No resolved predictions yet for this period.</p>
          <p className="text-xs mt-2 text-slate-600">
            Results are fetched automatically every 2 hours after matches finish.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {history.map((h) => (
            <HistoryRow key={`${h.match_id}-${h.resolved_at}`} item={h} />
          ))}
        </div>
      )}
    </div>
  );
}

function HistoryRow({ item }: { item: PredictionHistory }) {
  const isPlay = item.ai_decision === "PLAY";

  return (
    <div className={`card p-3 transition-all border ${
      item.is_correct
        ? "border-green-500/25 bg-green-500/5"
        : "border-red-500/20 bg-red-500/5"
    }`}>
      <div className="flex items-center gap-3">
        {/* Result icon */}
        <div className="shrink-0">
          {item.is_correct ? (
            <CheckCircle2 size={22} className="text-green-400" />
          ) : isPlay ? (
            <XCircle size={22} className="text-red-400" />
          ) : (
            <Minus size={22} className="text-slate-500" />
          )}
        </div>

        {/* Match info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1 text-[10px] text-slate-500 mb-0.5">
            <span>{item.sport_icon}</span>
            <span className="truncate">{item.competition}</span>
            <span className="ml-auto shrink-0">{item.match_date ? formatDate(item.match_date) : "—"}</span>
          </div>
          <p className="text-sm font-semibold truncate">
            <span className="text-white">{item.home_team}</span>
            <span className="text-slate-500 mx-1">vs</span>
            <span className="text-white">{item.away_team}</span>
          </p>
        </div>

        {/* Right column */}
        <div className="flex flex-col items-end gap-0.5 shrink-0 text-right">
          {/* Predicted → Actual */}
          <div className="text-[11px]">
            <span className="text-slate-400">Pick: </span>
            <span className="text-sky-300 font-semibold">{item.predicted_outcome_label}</span>
          </div>
          <div className="text-[11px]">
            <span className="text-slate-400">Result: </span>
            <span className={`font-semibold ${item.is_correct ? "text-green-400" : "text-red-400"}`}>
              {item.actual_result_label}
            </span>
          </div>
          {/* P&L */}
          {isPlay && (
            <span className={`text-xs font-bold mt-0.5 ${
              item.profit_loss_units > 0
                ? "text-green-400"
                : item.profit_loss_units < 0
                ? "text-red-400"
                : "text-slate-500"
            }`}>
              {item.profit_loss_units > 0 ? "+" : ""}{item.profit_loss_units.toFixed(2)}u
            </span>
          )}
        </div>
      </div>

      {/* Confidence + odds bar */}
      <div className="mt-2 flex items-center gap-3 text-[10px] text-slate-500">
        <span>Conf <span className="text-slate-300">{Math.round(item.confidence_score)}</span></span>
        {item.predicted_prob && (
          <span>Prob <span className="text-slate-300">{Math.round(item.predicted_prob * 100)}%</span></span>
        )}
        {item.recommended_odds && (
          <span>Odds <span className="text-yellow-300">{item.recommended_odds.toFixed(2)}</span></span>
        )}
        <span className="ml-auto text-slate-600">
          {new Date(item.resolved_at).toLocaleDateString()}
        </span>
      </div>
    </div>
  );
}
