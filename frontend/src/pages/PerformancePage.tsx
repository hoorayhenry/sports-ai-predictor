import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart2, TrendingUp, TrendingDown } from "lucide-react";
import { fetchPerformance } from "../api/client";
import Spinner from "../components/Spinner";

export default function PerformancePage() {
  const [days, setDays] = useState(30);

  const { data: stats, isLoading } = useQuery({
    queryKey: ["performance", days],
    queryFn: () => fetchPerformance(undefined, days),
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <Spinner size={48} />
      </div>
    );
  }

  const winRate = (stats?.win_rate ?? 0) * 100;
  const roi     = stats?.roi_pct ?? 0;
  const roiPos  = roi >= 0;

  return (
    <div className="min-h-screen pb-20 md:pb-6 px-4 pt-6">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <BarChart2 className="text-sky-400" size={22} />
          <h2 className="text-xl font-bold text-white">Performance</h2>
        </div>
        <div className="flex gap-2">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1 text-xs font-medium rounded-lg border transition-all ${
                days === d
                  ? "bg-sky-500/20 border-sky-500/50 text-sky-400"
                  : "border-slate-700 text-slate-400 hover:text-white"
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Main KPIs */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <KpiCard label="Total PLAY Picks" value={stats?.total_picks ?? 0} />
        <KpiCard label="Win Rate"
          value={`${winRate.toFixed(1)}%`}
          color={winRate >= 55 ? "text-green-400" : winRate >= 45 ? "text-yellow-400" : "text-red-400"}
        />
        <KpiCard label="Wins" value={stats?.wins ?? 0} color="text-green-400" />
        <KpiCard label="Losses" value={stats?.losses ?? 0} color="text-red-400" />
      </div>

      {/* ROI card */}
      <div className="card p-4 mb-4 flex items-center gap-4">
        <div className={`p-3 rounded-xl ${roiPos ? "bg-green-500/20" : "bg-red-500/20"}`}>
          {roiPos
            ? <TrendingUp size={24} className="text-green-400" />
            : <TrendingDown size={24} className="text-red-400" />
          }
        </div>
        <div>
          <p className="text-slate-400 text-sm">ROI (last {days} days)</p>
          <p className={`text-3xl font-bold ${roiPos ? "text-green-400" : "text-red-400"}`}>
            {roiPos ? "+" : ""}{roi.toFixed(2)}%
          </p>
        </div>
        <div className="ml-auto text-right">
          <p className="text-slate-400 text-xs">P&L (units)</p>
          <p className={`text-xl font-bold ${roiPos ? "text-green-400" : "text-red-400"}`}>
            {roiPos ? "+" : ""}{(stats?.total_pnl_units ?? 0).toFixed(2)}u
          </p>
        </div>
      </div>

      {/* By sport */}
      {stats?.by_sport && Object.keys(stats.by_sport).length > 0 && (
        <div className="card p-4 mb-4">
          <h3 className="font-semibold text-sm mb-3">By Sport</h3>
          <div className="space-y-3">
            {Object.entries(stats.by_sport).map(([sport, s]) => (
              <div key={sport}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-slate-300 capitalize">{sport}</span>
                  <span className="text-slate-400">{s.wins}W / {s.total - s.wins}L</span>
                </div>
                <div className="h-2 bg-slate-700 rounded-full">
                  <div
                    className={`h-2 rounded-full ${s.win_rate >= 0.55 ? "bg-green-500" : s.win_rate >= 0.45 ? "bg-yellow-500" : "bg-red-500"}`}
                    style={{ width: `${s.win_rate * 100}%` }}
                  />
                </div>
                <p className="text-xs text-slate-500 mt-0.5">{(s.win_rate * 100).toFixed(1)}% win rate</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top competitions */}
      {stats?.top_competitions && stats.top_competitions.length > 0 && (
        <div className="card overflow-hidden mb-4">
          <div className="px-4 py-3 border-b border-slate-700/50">
            <h3 className="font-semibold text-sm">Best Performing Competitions</h3>
          </div>
          {stats.top_competitions.map((c, i) => (
            <div
              key={c.competition}
              className={`flex items-center px-4 py-2.5 text-sm ${i % 2 === 0 ? "" : "bg-slate-800/30"}`}
            >
              <span className="text-slate-500 w-6">{i + 1}</span>
              <span className="flex-1 text-slate-300 truncate">{c.competition}</span>
              <span className={`font-bold ${c.win_rate >= 0.6 ? "text-green-400" : "text-yellow-400"}`}>
                {(c.win_rate * 100).toFixed(0)}%
              </span>
              <span className="text-slate-600 text-xs ml-2">({c.sample})</span>
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!stats?.total_picks && (
        <div className="text-center py-20 text-slate-500">
          <p className="text-5xl mb-4">📊</p>
          <p>No resolved picks yet.</p>
          <p className="text-xs mt-2">Performance data appears after matches finish.</p>
        </div>
      )}
    </div>
  );
}

function KpiCard({ label, value, color = "text-white" }: {
  label: string; value: string | number; color?: string;
}) {
  return (
    <div className="card p-4 text-center">
      <p className="text-[11px] text-slate-500 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
    </div>
  );
}
