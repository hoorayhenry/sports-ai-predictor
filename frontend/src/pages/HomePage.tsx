import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp, Zap, RefreshCw, Flame, Target, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { fetchSports, fetchMatches, fetchDailyPicks } from "../api/client";
import MatchCard from "../components/MatchCard";
import SportTabs from "../components/SportTabs";
import Spinner from "../components/Spinner";
import { outcomeShort, probTagColor, formatDate } from "../utils/format";
import type { MatchDecision } from "../api/types";

export default function HomePage() {
  const [sport, setSport] = useState("all");
  const [days, setDays] = useState(7);

  const { data: sports = [] } = useQuery({
    queryKey: ["sports"],
    queryFn: fetchSports,
    staleTime: 60_000,
  });

  const { data: matches = [], isLoading: matchLoading, refetch } = useQuery({
    queryKey: ["matches", sport, days],
    queryFn: () => fetchMatches({ sport: sport === "all" ? undefined : sport, days }),
    staleTime: 30_000,
  });

  const { data: dailyPicks = [] } = useQuery({
    queryKey: ["daily-picks-home"],
    queryFn: () => fetchDailyPicks(),
    staleTime: 60_000,
  });

  const valueBets = matches.filter((m) => m.prediction?.is_value_bet);
  const predicted  = matches.filter((m) => m.prediction);
  const topPicks   = dailyPicks.slice(0, 5);

  return (
    <div className="min-h-screen pb-20 md:pb-6">
      {/* Hero */}
      <div className="bg-gradient-to-b from-sky-900/30 to-transparent px-4 pt-6 pb-6 md:pt-10">
        <h1 className="text-2xl md:text-4xl font-bold text-white mb-1">
          Sports <span className="text-sky-400">AI</span> Predictor
        </h1>
        <p className="text-slate-400 text-sm mb-4">
          Autonomous AI betting assistant — thinks, filters, decides
        </p>
        <div className="flex gap-3 flex-wrap">
          <StatChip icon={<TrendingUp size={14} />}  label="Predicted"   value={predicted.length} />
          <StatChip icon={<Zap size={14} />}          label="Value Bets"  value={valueBets.length} />
          <StatChip icon={<Flame size={14} />}        label="AI Plays"    value={dailyPicks.filter(p => p.ai_decision === "PLAY").length} color="text-orange-400" />
          <StatChip icon="🏆"                          label="Matches"     value={matches.length} />
        </div>
      </div>

      {/* ── AI Daily Picks strip ──────────────────────────────────── */}
      {topPicks.length > 0 && (
        <section className="px-4 mb-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Flame size={16} className="text-orange-400" />
              <span className="font-bold text-white">🔥 AI Daily Picks</span>
              <span className="text-xs text-slate-500">Today & Tomorrow</span>
            </div>
            <Link to="/picks" className="flex items-center gap-1 text-xs text-sky-400 hover:text-sky-300 transition-colors">
              See all <ChevronRight size={13} />
            </Link>
          </div>

          <div className="space-y-2">
            {topPicks.map((pick) => (
              <DailyPickMini key={pick.match_id} pick={pick} />
            ))}
          </div>
        </section>
      )}

      {/* ── Smart Sets promo ─────────────────────────────────────── */}
      <section className="px-4 mb-5">
        <Link to="/sets">
          <div className="card p-4 flex items-center gap-3 border-purple-500/30 hover:border-purple-500/60 transition-all">
            <div className="bg-purple-500/20 p-2.5 rounded-xl shrink-0">
              <Target size={20} className="text-purple-400" />
            </div>
            <div className="flex-1">
              <p className="font-semibold text-white">Smart Sets</p>
              <p className="text-xs text-slate-400">10 curated 10-match sets for today — mixed sports, balanced risk</p>
            </div>
            <ChevronRight size={18} className="text-slate-500" />
          </div>
        </Link>
      </section>

      {/* ── All matches ──────────────────────────────────────────── */}
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
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      <div className="px-4">
        {matchLoading ? (
          <div className="flex justify-center py-20"><Spinner size={40} /></div>
        ) : matches.length === 0 ? (
          <div className="text-center py-20 text-slate-500">
            <p className="text-5xl mb-4">📭</p>
            <p>No matches found.</p>
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

function DailyPickMini({ pick }: { pick: MatchDecision }) {
  const { dot, text } = probTagColor(pick.prob_tag);
  const isPlay = pick.ai_decision === "PLAY";
  return (
    <Link to={`/match/${pick.match_id}`}>
      <div className={`card px-3 py-2.5 flex items-center gap-3 hover:border-green-500/30 transition-all ${isPlay ? "border-green-500/20" : "opacity-60"}`}>
        <span className="text-base">{pick.sport_icon}</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-white truncate">
            {pick.home_team} <span className="text-slate-500">vs</span> {pick.away_team}
          </p>
          <p className="text-[11px] text-slate-500">{pick.competition} · {formatDate(pick.match_date)}</p>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <span className="text-xs text-sky-400 font-medium">{outcomeShort(pick.predicted_outcome)}</span>
          <div className="flex items-center gap-1.5">
            <span className={`text-[11px] font-semibold ${text}`}>{dot} {Math.round(pick.top_prob * 100)}%</span>
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${isPlay ? "bg-green-500/15 text-green-400" : "bg-slate-700 text-slate-400"}`}>
              {isPlay ? "PLAY" : "SKIP"}
            </span>
          </div>
        </div>
      </div>
    </Link>
  );
}

function StatChip({ icon, label, value, color = "text-sky-400" }: {
  icon: React.ReactNode; label: string; value: number; color?: string;
}) {
  return (
    <div className="flex items-center gap-1.5 bg-[#1e293b] border border-slate-700/50 rounded-xl px-3 py-1.5 text-sm">
      <span className={color}>{icon}</span>
      <span className="text-slate-400 text-xs">{label}</span>
      <span className="font-semibold text-white">{value}</span>
    </div>
  );
}
