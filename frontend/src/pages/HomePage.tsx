import { useState, useCallback } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { TrendingUp, Zap, RefreshCw, Flame, Target, ChevronRight, Calendar, Filter } from "lucide-react";
import { Link } from "react-router-dom";
import { fetchSports, fetchMatches, fetchDailyPicks, fetchLiveScores } from "../api/client";
import MatchCard from "../components/MatchCard";
import SportTabs from "../components/SportTabs";
import Spinner from "../components/Spinner";
import { outcomeShort, formatDate } from "../utils/format";
import type { MatchDecision } from "../api/types";

// Dynamic limit based on filter mode / days range

function dateKey(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

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

  const pageLimit = filterMode === "days"
    ? (days === 1 ? 40 : days === 3 ? 90 : days === 7 ? 200 : 350)
    : 100;

  const { data: sports = [] } = useQuery({
    queryKey: ["sports"],
    queryFn: fetchSports,
    staleTime: 300_000,
  });

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    refetch,
  } = useInfiniteQuery({
    queryKey: ["matches-infinite", sport, filterMode, days, dateFrom, dateTo, "v2"],
    queryFn: ({ pageParam = 0 }) => {
      const tomorrow = isoDate(new Date(Date.now() + 86_400_000));
      const rangeEnd  = isoDate(new Date(Date.now() + days * 86_400_000));
      return fetchMatches({
        sport: sport === "all" ? undefined : sport,
        limit: pageLimit,
        offset: pageParam as number,
        ...(filterMode === "days"
          ? days === 1
            ? { days: 1 }
            : { date_from: tomorrow, date_to: rangeEnd }
          : { date_from: dateFrom, date_to: dateTo }),
      });
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
    staleTime: 30_000,
  });

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

  const { data: liveData } = useQuery({
    queryKey: ["live-scores"],
    queryFn: fetchLiveScores,
    staleTime: 30_000,
    refetchInterval: 60_000, // auto-refresh every minute
  });
  const liveMatches = liveData?.matches ?? [];

  const allMatches = data?.pages.flatMap((p) => p.matches) ?? [];
  const total = data?.pages[0]?.total ?? 0;

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
      <div className="relative overflow-hidden rounded-b-2xl md:rounded-2xl md:mx-4 md:mt-4 mb-2">
        {/* Background image */}
        <img
          src="https://images.unsplash.com/photo-1517927033932-b3d18e61fb3a?w=1400&q=80&auto=format&fit=crop"
          alt=""
          className="absolute inset-0 w-full h-full object-cover object-center brightness-75 saturate-125 select-none pointer-events-none"
          aria-hidden="true"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/10 via-black/25 to-[#070c19]/92" />
        <div className="absolute inset-0 bg-gradient-to-r from-[#070c19]/80 via-transparent to-transparent" />

        <div className="relative px-5 pt-7 pb-6 md:pt-10 md:pb-8">
          <div className="flex items-center gap-2 mb-2">
            <span className="flex items-center gap-1.5 text-[10px] font-semibold tracking-widest text-pi-indigo-light uppercase section-label">
              <span className="w-1.5 h-1.5 rounded-full bg-pi-emerald animate-pulse inline-block" />
              Live Intelligence
            </span>
          </div>
          <h1 className="text-3xl md:text-[2.6rem] font-extrabold text-pi-primary font-display mb-2 leading-tight">
            Today's <span className="text-gradient">Picks</span>
          </h1>
          <p className="text-pi-secondary text-sm mb-5 max-w-sm leading-relaxed">
            Value detection across football, basketball, tennis &amp; more
          </p>
          <div className="flex gap-2 flex-wrap">
            <StatChip icon={<TrendingUp size={13} />} label="Predicted"  value={predicted.length} />
            <StatChip icon={<Zap size={13} />}         label="Value Bets" value={valueBets.length} color="text-pi-amber" />
            <StatChip icon={<Flame size={13} />}       label="Plays"      value={dailyPicks.filter((p) => p.ai_decision === "PLAY").length} color="text-pi-emerald" />
            <StatChip icon="🏆"                         label="Matches"    value={total} />
          </div>
        </div>
      </div>

      {/* ── Top Picks — image cards with pick overlay ───────────── */}
      {topPicks.length > 0 && (
        <section className="mb-5">
          <div className="flex items-center justify-between px-4 mb-3">
            <div className="flex items-center gap-2">
              <Flame size={15} className="text-pi-emerald" />
              <span className="font-semibold text-white text-sm font-display uppercase tracking-wide">Top Picks</span>
              <span className="text-xs text-slate-400">Highest confidence</span>
            </div>
            <Link to="/picks" className="flex items-center gap-1 text-xs text-indigo-400 hover:text-white transition-colors">
              See all <ChevronRight size={12} />
            </Link>
          </div>
          <div className="flex gap-3 overflow-x-auto px-4 pb-2" style={{ scrollbarWidth: "none" }}>
            {topPicks.map((pick, i) => (
              <TopPickCard key={pick.match_id} pick={pick} imgIndex={i} />
            ))}
          </div>
        </section>
      )}

      {/* Live matches */}
      {liveMatches.length > 0 && (
        <LiveSection matches={liveMatches} />
      )}

      {/* Smart Sets promo */}
      <section className="px-4 mb-5">
        <Link to="/sets">
          <div className="card p-4 flex items-center gap-3 hover:border-pi-violet/40 transition-all">
            <div className="bg-pi-violet/15 p-2.5 rounded-xl shrink-0">
              <Target size={18} className="text-pi-violet" />
            </div>
            <div className="flex-1">
              <p className="font-semibold text-pi-primary text-sm font-display">Smart Sets</p>
              <p className="text-xs text-pi-secondary">10 curated match packages — balanced risk</p>
            </div>
            <ChevronRight size={16} className="text-pi-muted" />
          </div>
        </Link>
      </section>

      {/* Filters */}
      <div className="px-4 space-y-3 mb-4">
        <SportTabs sports={sports} selected={sport} onSelect={setSport} />

        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex rounded-lg border border-pi-border overflow-hidden">
            <button
              onClick={() => setFilterMode("days")}
              className={`px-3 py-1.5 text-xs font-medium flex items-center gap-1 transition-all ${
                filterMode === "days"
                  ? "bg-pi-indigo/15 text-pi-indigo-light border-r border-pi-indigo/25"
                  : "text-pi-secondary hover:text-pi-primary border-r border-pi-border"
              }`}
            >
              <Filter size={11} /> Quick
            </button>
            <button
              onClick={() => setFilterMode("range")}
              className={`px-3 py-1.5 text-xs font-medium flex items-center gap-1 transition-all ${
                filterMode === "range"
                  ? "bg-pi-indigo/15 text-pi-indigo-light"
                  : "text-pi-secondary hover:text-pi-primary"
              }`}
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
                    days === d ? "pill-active" : "pill-inactive"
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
                className="bg-pi-surface border border-pi-border text-pi-primary text-xs rounded-lg px-2 py-1.5 focus:outline-none focus:border-pi-indigo"
              />
              <span className="text-pi-muted text-xs">to</span>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="bg-pi-surface border border-pi-border text-pi-primary text-xs rounded-lg px-2 py-1.5 focus:outline-none focus:border-pi-indigo"
              />
            </div>
          )}

          <button
            onClick={() => refetch()}
            className="ml-auto flex items-center gap-1 text-xs text-pi-secondary hover:text-pi-primary transition-colors"
          >
            <RefreshCw size={12} /> Refresh
          </button>
        </div>

        <p className="text-xs text-pi-muted">
          {isLoading ? "Loading..." : (() => {
            const from = days === 1
              ? new Date().toLocaleDateString("en-GB", { day: "numeric", month: "short" })
              : new Date(Date.now() + 86_400_000).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
            const to   = new Date(Date.now() + (filterMode === "days" ? days : 7) * 86_400_000)
              .toLocaleDateString("en-GB", { day: "numeric", month: "short" });
            return `${from} – ${to} · ${total} matches · showing ${allMatches.length}`;
          })()}
        </p>
      </div>

      {/* Match list grouped by date */}
      <div className="px-4">
        {isLoading ? (
          <div className="flex justify-center py-20"><Spinner size={40} /></div>
        ) : allMatches.length === 0 ? (
          <div className="text-center py-20 text-pi-muted">
            <p className="text-5xl mb-4">📭</p>
            <p>No matches found for this range.</p>
          </div>
        ) : (
          <>
            {Object.entries(grouped).map(([dateLabel, dayMatches]) => {
              const friendly = dayMatches[0]?.match_date ? friendlyDate(dayMatches[0].match_date) : dateLabel;
              return (
                <div key={dateLabel} className="mb-6">
                  <div className="date-divider mb-3 sticky top-0 z-10 py-2" style={{ background: "rgba(7,12,25,0.92)", backdropFilter: "blur(8px)" }}>
                    <span className="text-xs font-semibold text-pi-indigo-light section-label">
                      {friendly} · {dayMatches.length} match{dayMatches.length !== 1 ? "es" : ""}
                    </span>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 items-stretch">
                    {dayMatches.map((m) => (
                      <MatchCard key={m.id} match={m} />
                    ))}
                  </div>
                </div>
              );
            })}

            <div ref={observerRef} className="h-16 flex items-center justify-center">
              {isFetchingNextPage && <Spinner size={28} />}
              {!hasNextPage && allMatches.length > 0 && (
                <p className="text-xs text-pi-muted">All {total} matches loaded</p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── High-quality football images for Top Pick cards ──────────────
const PICK_IMAGES = [
  "https://images.unsplash.com/photo-1517927033932-b3d18e61fb3a?w=600&q=85&auto=format&fit=crop",
  "https://images.unsplash.com/photo-1579952363873-27f3bade9f55?w=600&q=85&auto=format&fit=crop",
  "https://images.unsplash.com/photo-1560272564-c83b66b1ad12?w=600&q=85&auto=format&fit=crop",
  "https://images.unsplash.com/photo-1553778263-73a83bab9b0c?w=600&q=85&auto=format&fit=crop",
  "https://images.unsplash.com/photo-1606925797300-0b35e9d1794e?w=600&q=85&auto=format&fit=crop",
  "https://images.unsplash.com/photo-1489944440615-453fc2b6a9a9?w=600&q=85&auto=format&fit=crop",
  "https://images.unsplash.com/photo-1522778526097-ce0a22ceb253?w=600&q=85&auto=format&fit=crop",
];

function TopPickCard({ pick, imgIndex }: { pick: MatchDecision; imgIndex: number }) {
  const img = PICK_IMAGES[imgIndex % PICK_IMAGES.length];
  const conf = Math.round(pick.top_prob * 100);
  const confColor = conf >= 75 ? "#10b981" : conf >= 60 ? "#f59e0b" : "#f43f5e";

  return (
    <Link to={`/match/${pick.match_id}`} className="shrink-0 w-60 group">
      <div className="relative rounded-2xl overflow-hidden" style={{ height: 160 }}>
        {/* Background image */}
        <img
          src={img}
          alt=""
          className="absolute inset-0 w-full h-full object-cover object-center brightness-75 saturate-110 group-hover:scale-105 transition-transform duration-500"
          aria-hidden="true"
        />
        {/* Gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/30 to-transparent" />

        {/* Confidence badge top-right */}
        <div
          className="absolute top-3 right-3 text-xs font-bold px-2.5 py-1 rounded-full backdrop-blur-sm"
          style={{ background: `${confColor}22`, border: `1px solid ${confColor}66`, color: confColor }}
        >
          {conf}%
        </div>

        {/* PLAY badge top-left */}
        <div className="absolute top-3 left-3 text-[10px] font-bold px-2 py-1 rounded-full bg-emerald-500/20 border border-emerald-500/50 text-emerald-400 backdrop-blur-sm uppercase tracking-wider">
          Play
        </div>

        {/* Match info bottom */}
        <div className="absolute bottom-0 left-0 right-0 p-3">
          <p className="text-white font-bold text-sm font-display leading-tight truncate">
            {pick.home_team} <span className="text-white/50 font-normal text-xs">vs</span> {pick.away_team}
          </p>
          <p className="text-white/60 text-[11px] mt-0.5 truncate">{pick.competition}</p>
          <p className="text-white/50 text-[10px] mt-0.5">{formatDate(pick.match_date)} · {outcomeShort(pick.predicted_outcome)}</p>
        </div>
      </div>
    </Link>
  );
}

// ── Live section with sport-category tabs ──────────────────────
import type { Match } from "../api/types";

function LiveSection({ matches }: { matches: Match[] }) {
  const [liveSport, setLiveSport] = useState("all");

  // Build unique sport tabs from live matches
  const sportCounts = matches.reduce<Record<string, number>>((acc, m) => {
    const icon = m.sport_icon ?? "🏆";
    acc[icon] = (acc[icon] ?? 0) + 1;
    return acc;
  }, {});
  const sportTabs = [
    { icon: "all", label: "All", count: matches.length },
    ...Object.entries(sportCounts).map(([icon, count]) => ({ icon, label: icon, count })),
  ];

  const filtered = liveSport === "all" ? matches : matches.filter((m) => m.sport_icon === liveSport);

  return (
    <section className="px-4 mb-5">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <span className="w-2 h-2 rounded-full bg-rose-400 animate-pulse inline-block" />
        <span className="font-semibold text-pi-primary text-sm font-display">Live Now</span>
        <span className="text-xs text-pi-muted">{matches.length} match{matches.length !== 1 ? "es" : ""} in progress</span>
      </div>

      {/* Sport tabs — only show when >1 sport */}
      {sportTabs.length > 2 && (
        <div className="flex gap-1.5 mb-3 flex-wrap">
          {sportTabs.map(({ icon, count }) => (
            <button
              key={icon}
              onClick={() => setLiveSport(icon)}
              className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium border transition-all ${
                liveSport === icon ? "pill-active" : "pill-inactive"
              }`}
            >
              {icon !== "all" && <span>{icon}</span>}
              {icon === "all" ? `All (${count})` : count}
            </button>
          ))}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 items-stretch">
        {filtered.map((m) => (
          <MatchCard key={m.id} match={m} />
        ))}
      </div>
    </section>
  );
}

function StatChip({ icon, label, value, color = "text-pi-sky" }: {
  icon: React.ReactNode; label: string; value: number; color?: string;
}) {
  return (
    <div className="stat-chip flex items-center gap-1.5 text-sm">
      <span className={color}>{icon}</span>
      <span className="text-pi-secondary text-xs">{label}</span>
      <span className="font-semibold text-pi-primary">{value}</span>
    </div>
  );
}
