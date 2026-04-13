import { useState, useCallback, useRef } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { TrendingUp, Zap, RefreshCw, Flame, Target, ChevronRight, Calendar, Filter } from "lucide-react";
import { Link } from "react-router-dom";
import { fetchSports, fetchMatches, fetchDailyPicks } from "../api/client";
import MatchCard from "../components/MatchCard";
import SportTabs from "../components/SportTabs";
import Spinner from "../components/Spinner";
import { outcomeShort, probTagColor, formatDate } from "../utils/format";
import type { MatchDecision } from "../api/types";

const PAGE_SIZE = 30;

// Format a date key like "Mon, 14 Apr" for grouping
function dateKey(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

// "Today", "Tomorrow", or the date string
function friendlyDate(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === tomorrow.toDateString()) return "Tomorrow";
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "short" });
}

function isoDate(d: Date) {
  return d.toISOString().split("T")[0];
}

export default function HomePage() {
  const [sport, setSport] = useState("all");
  const [filterMode, setFilterMode] = useState<"days" | "range">("days");
  const [days, setDays] = useState(7);
  const [dateFrom, setDateFrom] = useState(isoDate(new Date()));
  const [dateTo, setDateTo] = useState(isoDate(new Date(Date.now() + 7 * 86400000)));
  const loadMoreRef = useRef<HTMLDivElement>(null);

  const { data: sports = [] } = useQuery({
    queryKey: ["sports"],
    queryFn: fetchSports,
    staleTime: 300_000,
  });

  // Infinite query for matches
  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    refetch,
  } = useInfiniteQuery({
    queryKey: ["matches-infinite", sport, filterMode, days, dateFrom, dateTo],
    queryFn: ({ pageParam = 0 }) =>
      fetchMatches({
        sport: sport === "all" ? undefined : sport,
        limit: PAGE_SIZE,
        offset: pageParam as number,
        ...(filterMode === "days"
          ? { days }
          : { date_from: dateFrom, date_to: dateTo }),
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
    staleTime: 30_000,
  });

  // IntersectionObserver for infinite scroll
  const observerRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (!node) return;
      const observer = new IntersectionObserver(
        (entries) => {
          if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) {
            fetchNextPage();
          }
        },
        { threshold: 0.1 }
      );
      observer.observe(node);
      return () => observer.disconnect();
    },
    [hasNextPage, isFetchingNextPage, fetchNextPage]
  );

  const { data: dailyPicks = [] } = useQuery({
    queryKey: ["daily-picks-home"],
    queryFn: () => fetchDailyPicks(),
    staleTime: 60_000,
  });

  // Flatten all pages
  const allMatches = data?.pages.flatMap((p) => p.matches) ?? [];
  const total = data?.pages[0]?.total ?? 0;

  // Group matches by date
  const grouped: Record<string, typeof allMatches> = {};
  for (const m of allMatches) {
    const key = m.match_date ? dateKey(m.match_date) : "Unknown";
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(m);
  }

  const valueBets = allMatches.filter((m) => m.prediction?.is_value_bet);
  const predicted = allMatches.filter((m) => m.prediction);
  const topPicks  = dailyPicks.filter((p) => p.ai_decision === "PLAY").slice(0, 5);

  return (
    <div className="min-h-screen pb-24 md:pb-8">
      {/* Hero */}
      <div className="bg-gradient-to-b from-sky-900/30 to-transparent px-4 pt-6 pb-4 md:pt-10">
        <h1 className="text-2xl md:text-4xl font-bold text-white mb-1">
          Sports <span className="text-sky-400">AI</span> Predictor
        </h1>
        <p className="text-slate-400 text-sm mb-4">
          Autonomous AI betting assistant — thinks, filters, decides
        </p>
        <div className="flex gap-3 flex-wrap">
          <StatChip icon={<TrendingUp size={14} />} label="Predicted"  value={predicted.length} />
          <StatChip icon={<Zap size={14} />}         label="Value Bets" value={valueBets.length} />
          <StatChip icon={<Flame size={14} />}       label="AI Plays"   value={dailyPicks.filter((p) => p.ai_decision === "PLAY").length} color="text-orange-400" />
          <StatChip icon="🏆"                         label="Matches"    value={total} />
        </div>
      </div>

      {/* AI Daily Picks strip */}
      {topPicks.length > 0 && (
        <section className="px-4 mb-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Flame size={16} className="text-orange-400" />
              <span className="font-bold text-white">🔥 AI Daily Picks</span>
              <span className="text-xs text-slate-500">Highest confidence</span>
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

      {/* Smart Sets promo */}
      <section className="px-4 mb-5">
        <Link to="/sets">
          <div className="card p-4 flex items-center gap-3 border-purple-500/30 hover:border-purple-500/60 transition-all">
            <div className="bg-purple-500/20 p-2.5 rounded-xl shrink-0">
              <Target size={20} className="text-purple-400" />
            </div>
            <div className="flex-1">
              <p className="font-semibold text-white">Smart Sets</p>
              <p className="text-xs text-slate-400">10 curated 10-match sets — mixed sports, balanced risk</p>
            </div>
            <ChevronRight size={18} className="text-slate-500" />
          </div>
        </Link>
      </section>

      {/* Filters */}
      <div className="px-4 space-y-3 mb-4">
        <SportTabs sports={sports} selected={sport} onSelect={setSport} />

        {/* Toggle days vs date range */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex rounded-lg border border-slate-700 overflow-hidden">
            <button
              onClick={() => setFilterMode("days")}
              className={`px-3 py-1.5 text-xs font-medium flex items-center gap-1 transition-all ${filterMode === "days" ? "bg-sky-500/20 text-sky-400 border-r border-sky-500/30" : "text-slate-400 hover:text-white border-r border-slate-700"}`}
            >
              <Filter size={11} /> Quick
            </button>
            <button
              onClick={() => setFilterMode("range")}
              className={`px-3 py-1.5 text-xs font-medium flex items-center gap-1 transition-all ${filterMode === "range" ? "bg-sky-500/20 text-sky-400" : "text-slate-400 hover:text-white"}`}
            >
              <Calendar size={11} /> Date Range
            </button>
          </div>

          {filterMode === "days" ? (
            <div className="flex gap-2">
              {[1, 3, 7, 14].map((d) => (
                <button
                  key={d}
                  onClick={() => setDays(d)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-all ${
                    days === d
                      ? "bg-sky-500/20 border-sky-500/50 text-sky-400"
                      : "border-slate-700 text-slate-400 hover:text-white"
                  }`}
                >
                  {d === 1 ? "Today" : d === 3 ? "3 days" : d === 7 ? "7 days" : "14 days"}
                </button>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="bg-[#1e293b] border border-slate-700 text-slate-200 text-xs rounded-lg px-2 py-1.5 focus:outline-none focus:border-sky-500"
              />
              <span className="text-slate-500 text-xs">to</span>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="bg-[#1e293b] border border-slate-700 text-slate-200 text-xs rounded-lg px-2 py-1.5 focus:outline-none focus:border-sky-500"
              />
            </div>
          )}

          <button
            onClick={() => refetch()}
            className="ml-auto flex items-center gap-1 text-xs text-slate-400 hover:text-white transition-colors"
          >
            <RefreshCw size={13} /> Refresh
          </button>
        </div>

        <p className="text-xs text-slate-500">
          {isLoading ? "Loading..." : `${total} matches found · showing ${allMatches.length}`}
        </p>
      </div>

      {/* Match list — grouped by date */}
      <div className="px-4">
        {isLoading ? (
          <div className="flex justify-center py-20"><Spinner size={40} /></div>
        ) : allMatches.length === 0 ? (
          <div className="text-center py-20 text-slate-500">
            <p className="text-5xl mb-4">📭</p>
            <p>No matches found for this range.</p>
          </div>
        ) : (
          <>
            {Object.entries(grouped).map(([dateLabel, dayMatches]) => {
              const friendly = dayMatches[0]?.match_date ? friendlyDate(dayMatches[0].match_date) : dateLabel;
              return (
                <div key={dateLabel} className="mb-6">
                  {/* Date header */}
                  <div className="flex items-center gap-3 mb-3 sticky top-0 z-10 bg-[#0a0f1e]/90 backdrop-blur-sm py-2">
                    <div className="h-px flex-1 bg-slate-700/50" />
                    <span className="text-xs font-semibold text-sky-400 px-3 py-1 bg-sky-500/10 border border-sky-500/20 rounded-full">
                      {friendly} · {dayMatches.length} match{dayMatches.length !== 1 ? "es" : ""}
                    </span>
                    <div className="h-px flex-1 bg-slate-700/50" />
                  </div>
                  <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                    {dayMatches.map((m) => (
                      <MatchCard key={m.id} match={m} />
                    ))}
                  </div>
                </div>
              );
            })}

            {/* Infinite scroll sentinel */}
            <div ref={observerRef} className="h-16 flex items-center justify-center">
              {isFetchingNextPage && <Spinner size={28} />}
              {!hasNextPage && allMatches.length > 0 && (
                <p className="text-xs text-slate-600">All {total} matches loaded</p>
              )}
            </div>
          </>
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
