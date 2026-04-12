import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp, Zap, RefreshCw } from "lucide-react";
import { fetchSports, fetchMatches } from "../api/client";
import MatchCard from "../components/MatchCard";
import SportTabs from "../components/SportTabs";
import Spinner from "../components/Spinner";

export default function HomePage() {
  const [sport, setSport] = useState("all");
  const [days, setDays] = useState(7);

  const { data: sports = [] } = useQuery({
    queryKey: ["sports"],
    queryFn: fetchSports,
    staleTime: 60_000,
  });

  const { data: matches = [], isLoading, refetch } = useQuery({
    queryKey: ["matches", sport, days],
    queryFn: () => fetchMatches({ sport: sport === "all" ? undefined : sport, days }),
    staleTime: 30_000,
  });

  const valueBets = matches.filter((m) => m.prediction?.is_value_bet);
  const predicted = matches.filter((m) => m.prediction);

  return (
    <div className="min-h-screen pb-20 md:pb-6">
      {/* Hero */}
      <div className="bg-gradient-to-b from-sky-900/30 to-transparent px-4 pt-6 pb-8 md:pt-10">
        <h1 className="text-2xl md:text-4xl font-bold text-white mb-1">
          Sports <span className="text-sky-400">AI</span> Predictor
        </h1>
        <p className="text-slate-400 text-sm md:text-base mb-6">
          AI-powered predictions for Football, Basketball, Tennis & more
        </p>

        {/* Stats strip */}
        <div className="flex gap-3 flex-wrap">
          <StatChip icon={<TrendingUp size={14} />} label="Predictions" value={predicted.length} />
          <StatChip icon={<Zap size={14} />} label="Value Bets" value={valueBets.length} />
          <StatChip icon="🏆" label="Matches" value={matches.length} />
        </div>
      </div>

      {/* Controls */}
      <div className="px-4 space-y-4 mb-4">
        <SportTabs sports={sports} selected={sport} onSelect={setSport} />

        <div className="flex items-center justify-between">
          <div className="flex gap-2">
            {[1, 3, 7].map((d) => (
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
          <button
            onClick={() => refetch()}
            className="flex items-center gap-1 text-xs text-slate-400 hover:text-white transition-colors"
          >
            <RefreshCw size={13} />
            Refresh
          </button>
        </div>
      </div>

      {/* Match list */}
      <div className="px-4">
        {isLoading ? (
          <div className="flex justify-center py-20">
            <Spinner size={40} />
          </div>
        ) : matches.length === 0 ? (
          <div className="text-center py-20 text-slate-500">
            <p className="text-5xl mb-4">📭</p>
            <p>No matches found for the selected filters.</p>
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {matches.map((m) => (
              <MatchCard key={m.id} match={m} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StatChip({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
}) {
  return (
    <div className="flex items-center gap-1.5 bg-[#1e293b] border border-slate-700/50 rounded-xl px-3 py-1.5 text-sm">
      <span className="text-sky-400">{icon}</span>
      <span className="text-slate-400 text-xs">{label}</span>
      <span className="font-semibold text-white">{value}</span>
    </div>
  );
}
