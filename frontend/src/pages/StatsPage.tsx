import { useQuery } from "@tanstack/react-query";
import { BarChart2, TrendingUp, Target } from "lucide-react";
import { fetchPredictionStats, fetchValueBets } from "../api/client";
import Spinner from "../components/Spinner";

export default function StatsPage() {
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchPredictionStats,
    staleTime: 60_000,
  });

  const { data: valueBets = [], isLoading: vbLoading } = useQuery({
    queryKey: ["value-bets-stats"],
    queryFn: () => fetchValueBets(),
    staleTime: 60_000,
  });

  const totalEV = valueBets.reduce((s, b) => s + (b.expected_value ?? 0), 0);
  const avgEV = valueBets.length ? totalEV / valueBets.length : 0;
  const highConf = valueBets.filter((b) => b.confidence === "high").length;

  if (statsLoading || vbLoading) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <Spinner size={48} />
      </div>
    );
  }

  return (
    <div className="min-h-screen pb-20 md:pb-6 px-4 pt-6">
      <div className="flex items-center gap-2 mb-6">
        <BarChart2 className="text-sky-400" size={22} />
        <h2 className="text-xl font-bold text-white">Performance Stats</h2>
      </div>

      {/* Prediction accuracy */}
      <div className="card p-5 mb-4">
        <div className="flex items-center gap-2 mb-4">
          <Target size={16} className="text-sky-400" />
          <h3 className="font-semibold">Prediction Accuracy</h3>
        </div>
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="text-3xl font-bold text-white">{stats?.total_predicted ?? 0}</p>
            <p className="text-xs text-slate-400 mt-1">Total Predicted</p>
          </div>
          <div>
            <p className="text-3xl font-bold text-green-400">{stats?.correct ?? 0}</p>
            <p className="text-xs text-slate-400 mt-1">Correct</p>
          </div>
          <div>
            <p className="text-3xl font-bold text-sky-400">
              {stats?.total_predicted ? `${Math.round((stats.accuracy ?? 0) * 100)}%` : "—"}
            </p>
            <p className="text-xs text-slate-400 mt-1">Accuracy</p>
          </div>
        </div>

        {/* Accuracy bar */}
        {stats?.total_predicted > 0 && (
          <div className="mt-4">
            <div className="h-3 rounded-full bg-slate-700">
              <div
                className="h-3 rounded-full bg-gradient-to-r from-sky-500 to-green-400"
                style={{ width: `${Math.round((stats.accuracy ?? 0) * 100)}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Value bet stats */}
      <div className="card p-5 mb-4">
        <div className="flex items-center gap-2 mb-4">
          <TrendingUp size={16} className="text-yellow-400" />
          <h3 className="font-semibold">Value Bet Overview</h3>
        </div>
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="text-3xl font-bold text-white">{valueBets.length}</p>
            <p className="text-xs text-slate-400 mt-1">Active Bets</p>
          </div>
          <div>
            <p className="text-3xl font-bold text-green-400">+{(avgEV * 100).toFixed(1)}%</p>
            <p className="text-xs text-slate-400 mt-1">Avg EV</p>
          </div>
          <div>
            <p className="text-3xl font-bold text-sky-400">{highConf}</p>
            <p className="text-xs text-slate-400 mt-1">High Conf.</p>
          </div>
        </div>
      </div>

      {/* Model info */}
      <div className="card p-5">
        <h3 className="font-semibold mb-3">Model Information</h3>
        <div className="space-y-2 text-sm">
          {[
            { label: "Algorithm", value: "XGBoost + LightGBM Ensemble" },
            { label: "Features", value: "30+ (ELO, form, H2H, strength, odds)" },
            { label: "Markets", value: "1X2, Over/Under 2.5, BTTS" },
            { label: "Sports", value: "Football, Basketball, Tennis" },
            { label: "Data source", value: "Sportybet + Odds API" },
          ].map(({ label, value }) => (
            <div key={label} className="flex justify-between">
              <span className="text-slate-400">{label}</span>
              <span className="text-white font-medium text-right max-w-[55%]">{value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
