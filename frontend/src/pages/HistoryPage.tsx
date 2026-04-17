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
      decision: "PLAY",
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
            <div className="bg-pi-violet/15 p-2 rounded-xl">
              <History size={18} className="text-pi-violet" />
            </div>
            <h2 className="text-xl font-bold text-pi-primary font-display">Pick History</h2>
          </div>
          <p className="text-xs text-pi-secondary ml-11">
            Every pick resolved with real match outcomes
          </p>
        </div>

        <div className="flex gap-1">
          {DAYS_OPTIONS.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`text-xs px-2 py-1 rounded-lg transition-colors ${
                days === d ? "pill-active" : "pill-inactive"
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
            { label: "Picks", value: total, color: "text-pi-primary" },
            { label: "Wins",  value: wins,  color: "text-pi-emerald" },
            { label: "Win %", value: `${winPct}%`, color: winPct >= 55 ? "text-pi-emerald" : winPct >= 45 ? "text-pi-amber" : "text-pi-rose" },
            { label: "P&L",   value: `${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}u`, color: pnl >= 0 ? "text-pi-emerald" : "text-pi-rose" },
          ].map(({ label, value, color }) => (
            <div key={label} className="card p-3 text-center">
              <p className={`text-lg font-bold tabular-nums ${color}`}>{value}</p>
              <p className="text-[10px] text-pi-muted mt-0.5 section-label">{label}</p>
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
        <div className="text-center py-20 text-pi-muted">
          <p className="text-5xl mb-4">📊</p>
          <p className="text-sm">No resolved predictions yet for this period.</p>
          <p className="text-xs mt-2 text-pi-muted/60">
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
    <div className={`card p-3 transition-all ${
      item.is_correct
        ? "border-pi-emerald/25"
        : "border-pi-rose/20"
    }`}>
      <div className="flex items-center gap-3">
        <div className="shrink-0">
          {item.is_correct ? (
            <CheckCircle2 size={20} className="text-pi-emerald" />
          ) : isPlay ? (
            <XCircle size={20} className="text-pi-rose" />
          ) : (
            <Minus size={20} className="text-pi-muted" />
          )}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1 text-[10px] text-pi-muted mb-0.5">
            <span>{item.sport_icon}</span>
            <span className="truncate">{item.competition}</span>
            <span className="ml-auto shrink-0">{item.match_date ? formatDate(item.match_date) : "—"}</span>
          </div>
          <p className="text-sm font-semibold truncate font-display">
            <span className="text-pi-primary">{item.home_team}</span>
            <span className="text-pi-muted mx-1">vs</span>
            <span className="text-pi-primary">{item.away_team}</span>
          </p>
        </div>

        <div className="flex flex-col items-end gap-0.5 shrink-0 text-right">
          <div className="text-[11px]">
            <span className="text-pi-muted">Pick: </span>
            <span className="text-pi-sky font-semibold">{item.predicted_outcome_label}</span>
          </div>
          <div className="text-[11px]">
            <span className="text-pi-muted">Result: </span>
            <span className={`font-semibold ${item.is_correct ? "text-pi-emerald" : "text-pi-rose"}`}>
              {item.actual_result_label}
            </span>
          </div>
          {isPlay && (
            <span className={`text-xs font-bold mt-0.5 tabular-nums ${
              item.profit_loss_units > 0 ? "text-pi-emerald" :
              item.profit_loss_units < 0 ? "text-pi-rose" : "text-pi-muted"
            }`}>
              {item.profit_loss_units > 0 ? "+" : ""}{item.profit_loss_units.toFixed(2)}u
            </span>
          )}
        </div>
      </div>

      <div className="mt-2 flex items-center gap-3 text-[10px] text-pi-muted">
        <span>Conf <span className="text-pi-secondary">{Math.round(item.confidence_score)}</span></span>
        {item.predicted_prob && (
          <span>Prob <span className="text-pi-secondary">{Math.round(item.predicted_prob * 100)}%</span></span>
        )}
        {item.recommended_odds && (
          <span>Odds <span className="text-pi-amber">{item.recommended_odds.toFixed(2)}</span></span>
        )}
        <span className="ml-auto text-pi-muted/60">
          {new Date(item.resolved_at).toLocaleDateString()}
        </span>
      </div>
    </div>
  );
}
