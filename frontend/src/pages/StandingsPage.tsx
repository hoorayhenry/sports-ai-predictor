import React, { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  Trophy, Zap, Clock, Calendar, Users, ChevronRight,
  Newspaper, Star, ExternalLink,
} from "lucide-react";
import Spinner from "../components/Spinner";
import { api } from "../api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

interface StandingRow {
  rank: number;
  team_id: string;
  team_name: string;
  team_short: string;
  team_logo: string;
  points: number;
  played: number;
  win: number;
  draw: number;
  lose: number;
  goals_for: number;
  goals_against: number;
  goal_diff: number;
  form: string[];
  description: string | null;
  group: string | null;
}

interface StandingsResponse {
  slug: string;
  league_name: string;
  country: string;
  flag: string;
  season: number;
  groups: StandingRow[][];
  source: string;
  cached?: boolean;
  stale?: boolean;
}

interface FixtureTeam {
  id: string;
  name: string;
  short: string;
  logo: string;
  score: number | null;
}

interface FixtureItem {
  id: string;
  date: string;
  status: "scheduled" | "live" | "finished";
  live_minute: number | null;
  home: FixtureTeam;
  away: FixtureTeam;
  venue: string;
  league_slug: string;
}

interface FixturesResponse {
  fixtures: FixtureItem[];
  slug: string;
  total: number;
}

interface NewsArticle {
  id: string;
  headline: string;
  description: string;
  published: string;
  image: string;
  url: string;
}

interface LeaderEntry {
  rank: number;
  value: number;
  display: string;
  player_id: string;
  name: string;
  headshot: string;
  team_id: string;
  team_name: string;
  team_logo: string;
  league_slug: string;
}

interface LeaderCategory {
  name: string;
  abbr: string;
  leaders: LeaderEntry[];
}

// ── Constants ─────────────────────────────────────────────────────────────────

const LEAGUES: { slug: string; name: string; flag?: string; logo?: string }[] = [
  { slug: "eng.1",            name: "Premier League",    flag: "🏴󠁧󠁢󠁥󠁮󠁧󠁿" },
  { slug: "esp.1",            name: "La Liga",           flag: "🇪🇸" },
  { slug: "ger.1",            name: "Bundesliga",        flag: "🇩🇪" },
  { slug: "ita.1",            name: "Serie A",           flag: "🇮🇹" },
  { slug: "fra.1",            name: "Ligue 1",           flag: "🇫🇷" },
  { slug: "por.1",            name: "Primeira Liga",     flag: "🇵🇹" },
  { slug: "ned.1",            name: "Eredivisie",        flag: "🇳🇱" },
  { slug: "tur.1",            name: "Süper Lig",         flag: "🇹🇷" },
  { slug: "sco.1",            name: "Scottish Prem.",    flag: "🏴󠁧󠁢󠁳󠁣󠁴󠁿" },
  { slug: "bel.1",            name: "Pro League",        flag: "🇧🇪" },
  { slug: "usa.1",            name: "MLS",               flag: "🇺🇸" },
  { slug: "bra.1",            name: "Brasileirão",       flag: "🇧🇷" },
  { slug: "arg.1",            name: "Liga Profesional",  flag: "🇦🇷" },
  { slug: "col.1",            name: "Liga BetPlay",      flag: "🇨🇴" },
  { slug: "uefa.champions",   name: "Champions League",  logo: "https://a.espncdn.com/i/leaguelogos/soccer/500/2.png" },
  { slug: "uefa.europa",      name: "Europa League",     logo: "https://a.espncdn.com/i/leaguelogos/soccer/500/2310.png" },
  { slug: "uefa.europa.conf", name: "Conference League", logo: "https://a.espncdn.com/i/leaguelogos/soccer/500/20296.png" },
];

const CURRENT_SEASON = 2025;
const SEASONS = Array.from({ length: 10 }, (_, i) => CURRENT_SEASON - i);

type PageTab = "standings" | "matches" | "news" | "teams" | "players";

// ── Helpers ───────────────────────────────────────────────────────────────────

function seasonLabel(s: number): string {
  return `${s}/${String(s + 1).slice(-2)}`;
}

function fmtDateLabel(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00Z" : "Z"));
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

function fmtTime(iso: string): string {
  if (!iso) return "";
  return new Date(iso + "Z").toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function timeAgo(iso: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3_600_000);
  if (h < 1) return "just now";
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function groupFixturesByDate(fixtures: FixtureItem[]): [string, FixtureItem[]][] {
  const map: Record<string, FixtureItem[]> = {};
  for (const f of fixtures) {
    const day = f.date.slice(0, 10);
    if (!map[day]) map[day] = [];
    map[day].push(f);
  }
  return Object.entries(map).sort(([a], [b]) => a.localeCompare(b));
}

// ── Sub-components ────────────────────────────────────────────────────────────

function QualBand({ description }: { description: string | null }) {
  if (!description) return null;
  const d = description.toLowerCase();
  if (d.includes("champions"))     return <span className="w-0.5 absolute left-0 inset-y-0 bg-sky-500/80 rounded-r" />;
  if (d.includes("europa league")) return <span className="w-0.5 absolute left-0 inset-y-0 bg-amber-500/80 rounded-r" />;
  if (d.includes("conference"))    return <span className="w-0.5 absolute left-0 inset-y-0 bg-lime-500/80 rounded-r" />;
  if (d.includes("relega"))        return <span className="w-0.5 absolute left-0 inset-y-0 bg-rose-500/80 rounded-r" />;
  return null;
}

function TeamLogo({ id, logo, name, size = "w-6 h-6" }: { id: string; logo: string; name: string; size?: string }) {
  const [failed, setFailed] = useState(false);
  const src = (!failed && logo) ? logo
    : id ? `https://a.espncdn.com/i/teamlogos/soccer/500/${id}.png`
    : "";
  return src ? (
    <img src={src} alt={name} className={`${size} object-contain shrink-0`}
      onError={() => { if (!failed) setFailed(true); }} />
  ) : (
    <div className={`${size} rounded-full bg-pi-surface border border-pi-border/30 shrink-0`} />
  );
}

function PlayerHeadshot({ id, src, name, size = "w-9 h-9" }: { id: string; src: string; name: string; size?: string }) {
  const [failed, setFailed] = useState(false);
  const url = (!failed && src) ? src
    : id ? `https://a.espncdn.com/i/headshots/soccer/players/full/${id}.png`
    : "";
  if (url) {
    return (
      <img src={url} alt={name} className={`${size} rounded-full object-cover object-top shrink-0`}
        onError={() => { if (!failed) setFailed(true); }} />
    );
  }
  return (
    <div className={`${size} rounded-full bg-pi-surface border border-pi-border/30 shrink-0 flex items-center justify-center`}>
      <Star size={12} className="text-pi-muted" />
    </div>
  );
}

// ── Fixture row ───────────────────────────────────────────────────────────────

function StatusBadge({ fixture }: { fixture: FixtureItem }) {
  if (fixture.status === "live") {
    return (
      <div className="flex flex-col items-center gap-0.5 shrink-0 min-w-[52px]">
        <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400 bg-emerald-500/15 border border-emerald-500/30 px-1.5 py-0.5 rounded-full">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse shrink-0" />
          LIVE
        </span>
        {fixture.live_minute != null && (
          <span className="text-[10px] text-emerald-400/70 font-mono">{fixture.live_minute}&apos;</span>
        )}
      </div>
    );
  }
  if (fixture.status === "finished") {
    return (
      <div className="flex flex-col items-center gap-0.5 shrink-0 min-w-[52px]">
        <span className="text-[10px] font-bold text-pi-muted bg-pi-surface border border-pi-border/30 px-1.5 py-0.5 rounded">FT</span>
        <span className="text-sm font-bold text-pi-primary tabular-nums">
          {fixture.home.score ?? "–"} – {fixture.away.score ?? "–"}
        </span>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center gap-0.5 shrink-0 min-w-[52px]">
      <span className="text-sm font-bold text-pi-primary">{fmtTime(fixture.date)}</span>
      <span className="text-[10px] text-pi-muted/60">KO</span>
    </div>
  );
}

function FixtureRow({ fixture, slug }: { fixture: FixtureItem; slug: string }) {
  const fin = fixture.status === "finished";
  const homeWin = fin && fixture.home.score != null && fixture.away.score != null && fixture.home.score > fixture.away.score;
  const awayWin = fin && fixture.home.score != null && fixture.away.score != null && fixture.away.score > fixture.home.score;

  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-pi-border/10 last:border-0 hover:bg-white/[0.02] transition-colors">
      <div className="flex items-center gap-2 flex-1 justify-end min-w-0">
        <span className={`text-[13px] font-semibold truncate ${homeWin ? "text-pi-primary" : "text-pi-secondary"}`}>
          {fixture.home.short || fixture.home.name}
        </span>
        {fixture.home.id ? (
          <Link to={`/team/${slug}/${fixture.home.id}`} onClick={e => e.stopPropagation()}>
            <TeamLogo id={fixture.home.id} logo={fixture.home.logo} name={fixture.home.name} />
          </Link>
        ) : (
          <TeamLogo id={fixture.home.id} logo={fixture.home.logo} name={fixture.home.name} />
        )}
      </div>

      <StatusBadge fixture={fixture} />

      <div className="flex items-center gap-2 flex-1 min-w-0">
        {fixture.away.id ? (
          <Link to={`/team/${slug}/${fixture.away.id}`} onClick={e => e.stopPropagation()}>
            <TeamLogo id={fixture.away.id} logo={fixture.away.logo} name={fixture.away.name} />
          </Link>
        ) : (
          <TeamLogo id={fixture.away.id} logo={fixture.away.logo} name={fixture.away.name} />
        )}
        <span className={`text-[13px] font-semibold truncate ${awayWin ? "text-pi-primary" : "text-pi-secondary"}`}>
          {fixture.away.short || fixture.away.name}
        </span>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function StandingsPage() {
  const [searchParams] = useSearchParams();
  const urlSlug = searchParams.get("slug");
  const validUrlSlug = urlSlug && LEAGUES.some(l => l.slug === urlSlug) ? urlSlug : null;

  const [slug, setSlug]       = useState(validUrlSlug ?? "eng.1");
  const [season, setSeason]   = useState(CURRENT_SEASON);
  const [pageTab, setPageTab] = useState<PageTab>("standings");

  // Sync when URL param changes (e.g. user clicks a competition link from another page)
  useEffect(() => {
    if (validUrlSlug && validUrlSlug !== slug) {
      setSlug(validUrlSlug);
      setPageTab("standings");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [validUrlSlug]);

  const isHistorical   = season !== CURRENT_SEASON;
  const selectedLeague = LEAGUES.find(l => l.slug === slug);



  // ── Queries ─────────────────────────────────────────────────────────────────
  const { data, isLoading, isError, error } = useQuery<StandingsResponse>({
    queryKey:  ["standings", slug, season],
    queryFn:   () => api.get(`/standings?slug=${slug}&season=${season}`).then(r => r.data),
    staleTime: isHistorical ? 30 * 24 * 60 * 60 * 1000 : 60_000,
    gcTime:    isHistorical ? 30 * 24 * 60 * 60 * 1000 : 300_000,
    retry: 2,
    refetchOnMount: true,
  });

  const { data: fixturesData, isLoading: fixturesLoading } = useQuery<FixturesResponse>({
    queryKey:  ["league-fixtures", slug, season],
    queryFn:   () => api.get(`/standings/fixtures?slug=${slug}&season=${season}`).then(r => r.data),
    enabled:   pageTab === "matches",
    staleTime: isHistorical ? 30 * 24 * 60 * 60 * 1000 : 120_000,
    retry: 1,
  });

  const { data: newsData, isLoading: newsLoading } = useQuery<{ articles: NewsArticle[] }>({
    queryKey:  ["league-news", slug],
    queryFn:   () => api.get(`/standings/news?slug=${slug}`).then(r => r.data),
    enabled:   pageTab === "news",
    staleTime: 600_000,
    retry: 1,
  });

  const { data: leadersData, isLoading: leadersLoading } = useQuery<{ categories: LeaderCategory[] }>({
    queryKey:  ["league-leaders", slug, season],
    queryFn:   () => api.get(`/standings/leaders?slug=${slug}&season=${season}`).then(r => r.data),
    enabled:   pageTab === "players",
    staleTime: isHistorical ? 30 * 24 * 60 * 60 * 1000 : 1_800_000,
    retry: 1,
  });

  const groups   = data?.groups ?? [];
  const allTeams = groups.flatMap(g => g);

  const PAGE_TABS: { key: PageTab; label: string; icon: React.ReactNode }[] = [
    { key: "standings", label: "Table",       icon: <Trophy size={12} /> },
    { key: "matches",   label: "Matches",     icon: <Calendar size={12} /> },
    { key: "news",      label: "News",        icon: <Newspaper size={12} /> },
    { key: "teams",     label: "Clubs",       icon: <Users size={12} /> },
    { key: "players",   label: "Top Players", icon: <Star size={12} /> },
  ];

  return (
    <div className="min-h-screen pb-24 md:pb-8">

      {/* ── Hero ─────────────────────────────────────────────── */}
      <div className="relative overflow-hidden rounded-b-2xl md:rounded-2xl md:mx-4 md:mt-4 mb-0" style={{ minHeight: 140 }}>
        <img
          src="https://images.unsplash.com/photo-1551958219-acbc608c6377?w=1400&q=80&auto=format&fit=crop"
          alt=""
          className="absolute inset-0 w-full h-full object-cover object-bottom brightness-75 saturate-125 select-none pointer-events-none"
          aria-hidden
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/10 via-black/20 to-[#070c19]/90" />
        <div className="absolute inset-0 bg-gradient-to-r from-[#070c19]/75 via-transparent to-transparent" />

        <div className="relative px-5 pt-7 pb-5 flex items-end justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <div className="bg-pi-amber/20 p-1.5 rounded-lg backdrop-blur-sm">
                <Trophy size={15} className="text-amber-400" />
              </div>
              <span className="section-label text-amber-400/80">{selectedLeague?.name ?? "League"}</span>
            </div>
            <h1 className="text-3xl md:text-4xl font-extrabold text-white font-display leading-none mb-1 drop-shadow-lg">
              {selectedLeague?.name ?? "Tables"}
            </h1>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              {!isHistorical ? (
                <span className="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-400/90 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 rounded-full backdrop-blur-sm">
                  <Zap size={9} /> Live · Updates after every match
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-[11px] font-semibold text-amber-400/80 bg-amber-500/10 border border-amber-500/20 px-2.5 py-1 rounded-full backdrop-blur-sm">
                  <Clock size={9} /> {seasonLabel(season)} season
                </span>
              )}
            </div>
          </div>
          <div className="shrink-0">
            <select
              value={season}
              onChange={e => setSeason(Number(e.target.value))}
              className="bg-pi-surface/80 backdrop-blur-sm border border-pi-border/60 text-pi-primary text-xs font-semibold rounded-lg px-3 py-2 cursor-pointer focus:outline-none focus:border-pi-indigo/50 transition-colors"
            >
              {SEASONS.map(s => <option key={s} value={s}>{seasonLabel(s)}</option>)}
            </select>
          </div>
        </div>
      </div>

      <div className="px-4 pt-4">

        {/* ── League pills ──────────────────────────────────── */}
        <div className="flex gap-2 mb-4 flex-wrap">
          {LEAGUES.map(({ slug: s, name, flag, logo }) => (
            <button
              key={s}
              onClick={() => { setSlug(s); setPageTab("standings"); }}
              className={`px-3 py-1.5 text-xs font-semibold rounded-full border transition-all flex items-center gap-1.5 whitespace-nowrap ${
                slug === s ? "pill-active" : "pill-inactive"
              }`}
            >
              {logo ? (
                <img
                  src={logo}
                  alt={name}
                  className="w-5 h-5 object-contain shrink-0 brightness-125 drop-shadow-[0_0_4px_rgba(255,255,255,0.4)]"
                />
              ) : (
                <span className="text-sm leading-none">{flag}</span>
              )}
              {name}
            </button>
          ))}
        </div>

        {/* ── Page tabs ─────────────────────────────────────── */}
        <div className="flex gap-0 border-b border-pi-border/30 mb-5 overflow-x-auto">
          {PAGE_TABS.map(({ key, label, icon }) => (
            <button
              key={key}
              onClick={() => setPageTab(key)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold whitespace-nowrap transition-all border-b-2 -mb-px ${
                pageTab === key
                  ? "border-pi-indigo text-pi-indigo-light"
                  : "border-transparent text-pi-muted hover:text-pi-secondary"
              }`}
            >
              {icon}{label}
            </button>
          ))}
        </div>

        {/* ════════════════════════════════════════════════════ */}
        {/* STANDINGS                                           */}
        {/* ════════════════════════════════════════════════════ */}
        {pageTab === "standings" && (
          <>
            {isLoading ? (
              <div className="flex flex-col items-center py-24 gap-3"><Spinner size={44} /></div>
            ) : isError ? (
              <div className="card p-8 text-center">
                <Trophy size={24} className="text-amber-400/50 mx-auto mb-4" />
                <p className="font-display text-lg font-bold text-pi-primary mb-1">Data Unavailable</p>
                <p className="text-sm text-pi-muted max-w-sm mx-auto">
                  {(error as { response?: { status?: number } })?.response?.status === 400
                    ? "This league isn't available."
                    : "Standings couldn't be reached. Try again in a moment."}
                </p>
                <button onClick={() => setSeason(CURRENT_SEASON)} className="mt-4 btn-secondary text-xs">
                  Back to {seasonLabel(CURRENT_SEASON)}
                </button>
              </div>
            ) : groups.length === 0 ? (
              <div className="card p-8 text-center">
                <Trophy size={28} className="text-pi-muted mx-auto mb-3" />
                <p className="font-display text-base font-bold text-pi-primary mb-1">No Standings Data</p>
                <p className="text-sm text-pi-muted">Season may not have started yet.</p>
              </div>
            ) : (
              <div className="space-y-6">
                {groups.map((group, gi) => (
                  <div key={gi} className="card overflow-hidden">
                    <div className="px-4 py-3 border-b border-pi-border/40 flex items-center gap-2.5 bg-pi-surface/40">
                      <div className="flex-1 min-w-0">
                        <p className="font-display font-bold text-pi-primary text-sm tracking-wide leading-none">
                          {data?.league_name}{groups.length > 1 && group[0]?.group ? ` — ${group[0].group}` : ""}
                        </p>
                        <p className="text-[11px] text-pi-muted mt-0.5">
                          {data?.country} · {seasonLabel(Number(data?.season))} Season
                        </p>
                      </div>
                      <div className="shrink-0">
                        {!isHistorical ? (
                          <div className="flex items-center gap-1.5 text-[10px] text-emerald-400/70 font-semibold">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />Live data
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5 text-[10px] text-amber-400/60 font-semibold">
                            <Clock size={9} />Final
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="grid grid-cols-[2.5rem_1fr_2.5rem_2.5rem_2.5rem_2.5rem_3rem_3.5rem] gap-x-1 px-4 py-2 text-[10px] font-bold text-pi-muted uppercase tracking-widest border-b border-pi-border/15">
                      <span className="text-center">#</span><span>Club</span>
                      <span className="text-center">P</span><span className="text-center">W</span>
                      <span className="text-center">D</span><span className="text-center">L</span>
                      <span className="text-center">GD</span><span className="text-center text-pi-indigo-light">PTS</span>
                    </div>

                    {group.map((row, i) => {
                      const rowContent = (
                        <>
                          <QualBand description={row.description} />
                          <span className="text-xs font-bold text-pi-muted text-center tabular-nums">{row.rank}</span>
                          <div className="flex items-center gap-2 min-w-0">
                            {row.team_logo ? (
                              <img src={row.team_logo} alt={row.team_name} className="w-5 h-5 object-contain shrink-0"
                                onError={e => { (e.target as HTMLImageElement).style.display = "none"; }} />
                            ) : (
                              <div className="w-5 h-5 rounded-full bg-pi-surface border border-pi-border shrink-0" />
                            )}
                            <span className="font-semibold text-pi-primary truncate text-[13px] leading-none group-hover:text-pi-indigo-light transition-colors">
                              {row.team_name}
                            </span>
                          </div>
                          <span className="text-center text-[12px] text-pi-secondary tabular-nums">{row.played}</span>
                          <span className="text-center text-[12px] text-emerald-400 font-semibold tabular-nums">{row.win}</span>
                          <span className="text-center text-[12px] text-pi-muted tabular-nums">{row.draw}</span>
                          <span className="text-center text-[12px] text-rose-400 tabular-nums">{row.lose}</span>
                          <span className={`text-center text-[12px] font-semibold tabular-nums ${(row.goal_diff ?? 0) > 0 ? "text-emerald-400" : (row.goal_diff ?? 0) < 0 ? "text-rose-400" : "text-pi-muted"}`}>
                            {(row.goal_diff ?? 0) > 0 ? `+${row.goal_diff}` : row.goal_diff}
                          </span>
                          <span className="text-center text-sm font-bold text-pi-primary tabular-nums">{row.points}</span>
                        </>
                      );
                      const rowClass = `group relative grid grid-cols-[2.5rem_1fr_2.5rem_2.5rem_2.5rem_2.5rem_3rem_3.5rem] gap-x-1 px-4 py-2.5 items-center text-sm transition-colors hover:bg-white/[0.035] cursor-pointer ${i !== group.length - 1 ? "border-b border-pi-border/10" : ""}`;
                      return row.team_id ? (
                        <Link key={`${row.team_name}-${i}`} to={`/team/${slug}/${row.team_id}`} className={rowClass}>{rowContent}</Link>
                      ) : (
                        <div key={`${row.team_name}-${i}`} className={rowClass}>{rowContent}</div>
                      );
                    })}

                    <div className="px-4 py-2.5 border-t border-pi-border/15 flex flex-wrap gap-x-4 gap-y-1">
                      {[
                        { color: "bg-sky-500/80",   label: "Champions League" },
                        { color: "bg-amber-500/80", label: "Europa League" },
                        { color: "bg-lime-500/80",  label: "Conference League" },
                        { color: "bg-rose-500/80",  label: "Relegation" },
                      ].map(({ color, label }) => (
                        <div key={label} className="flex items-center gap-1.5">
                          <span className={`w-2 h-2 rounded-sm ${color}`} />
                          <span className="text-[10px] text-pi-muted">{label}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* ════════════════════════════════════════════════════ */}
        {/* MATCHES                                             */}
        {/* ════════════════════════════════════════════════════ */}
        {pageTab === "matches" && (
          <>
            {fixturesLoading ? (
              <div className="flex flex-col items-center py-24 gap-3">
                <Spinner size={44} />
                <p className="text-xs text-pi-muted">Loading fixtures…</p>
              </div>
            ) : !fixturesData?.fixtures.length ? (
              <div className="card p-8 text-center">
                <Calendar size={28} className="text-pi-muted mx-auto mb-3" />
                <p className="font-display text-base font-bold text-pi-primary mb-1">No Fixtures</p>
                <p className="text-sm text-pi-muted">No matches found for {selectedLeague?.name} in the next two weeks.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {groupFixturesByDate(fixturesData.fixtures).map(([day, dayFixtures]) => (
                  <div key={day} className="card overflow-hidden">
                    <div className="px-4 py-2.5 border-b border-pi-border/30 bg-pi-surface/40 flex items-center gap-2">
                      <Calendar size={12} className="text-pi-indigo-light" />
                      <span className="text-xs font-bold text-pi-secondary">{fmtDateLabel(day)}</span>
                      <span className="ml-auto text-[10px] text-pi-muted">{dayFixtures.length} match{dayFixtures.length !== 1 ? "es" : ""}</span>
                    </div>
                    {dayFixtures.map(f => <FixtureRow key={f.id} fixture={f} slug={slug} />)}
                  </div>
                ))}
                <p className="text-[11px] text-pi-muted/40 text-center pb-2">
                  Click a team logo to view their profile
                </p>
              </div>
            )}
          </>
        )}

        {/* ════════════════════════════════════════════════════ */}
        {/* NEWS                                                */}
        {/* ════════════════════════════════════════════════════ */}
        {pageTab === "news" && (
          <>
            {newsLoading ? (
              <div className="flex flex-col items-center py-24 gap-3">
                <Spinner size={44} />
                <p className="text-xs text-pi-muted">Loading news…</p>
              </div>
            ) : !newsData?.articles.length ? (
              <div className="card p-8 text-center">
                <Newspaper size={28} className="text-pi-muted mx-auto mb-3" />
                <p className="font-display text-base font-bold text-pi-primary mb-1">No News</p>
                <p className="text-sm text-pi-muted">No articles available for {selectedLeague?.name} right now.</p>
              </div>
            ) : (
              <div className="space-y-3">
                {newsData.articles.map(a => (
                  <a
                    key={a.id}
                    href={a.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex gap-3 p-3 rounded-xl border border-pi-border/20 bg-white/[0.02] hover:bg-white/[0.05] hover:border-pi-indigo/30 transition-all group"
                  >
                    {a.image && (
                      <img
                        src={a.image} alt=""
                        className="w-20 h-14 object-cover rounded-lg shrink-0"
                        onError={e => { (e.target as HTMLImageElement).style.display = "none"; }}
                      />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-2">
                        <p className="font-semibold text-pi-primary text-sm leading-snug line-clamp-2 group-hover:text-pi-indigo-light transition-colors">
                          {a.headline}
                        </p>
                        <ExternalLink size={11} className="text-pi-muted/40 shrink-0 mt-0.5" />
                      </div>
                      {a.description && (
                        <p className="text-[11px] text-pi-secondary mt-1 line-clamp-2">{a.description}</p>
                      )}
                      <p className="text-[10px] text-pi-muted mt-1.5">{timeAgo(a.published)}</p>
                    </div>
                  </a>
                ))}
              </div>
            )}
          </>
        )}

        {/* ════════════════════════════════════════════════════ */}
        {/* TEAMS                                               */}
        {/* ════════════════════════════════════════════════════ */}
        {pageTab === "teams" && (
          <>
            {isLoading ? (
              <div className="flex flex-col items-center py-24 gap-3"><Spinner size={44} /></div>
            ) : allTeams.length === 0 ? (
              <div className="card p-8 text-center">
                <Users size={28} className="text-pi-muted mx-auto mb-3" />
                <p className="font-display text-base font-bold text-pi-primary mb-1">No Teams</p>
                <p className="text-sm text-pi-muted">Switch to Standings to load the team list.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {allTeams.map(row => row.team_id ? (
                  <Link
                    key={row.team_id}
                    to={`/team/${slug}/${row.team_id}`}
                    className="flex items-center gap-3 p-3 rounded-xl border border-pi-border/20 bg-white/[0.02] hover:bg-white/[0.05] hover:border-pi-indigo/30 transition-all group"
                  >
                    <div className="w-10 h-10 rounded-lg bg-pi-surface/60 border border-pi-border/20 flex items-center justify-center shrink-0">
                      <img
                        src={row.team_logo || `https://a.espncdn.com/i/teamlogos/soccer/500/${row.team_id}.png`}
                        alt={row.team_name}
                        className="w-8 h-8 object-contain"
                        onError={e => { (e.target as HTMLImageElement).style.display = "none"; }}
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-semibold text-pi-primary text-sm truncate group-hover:text-pi-indigo-light transition-colors">
                        {row.team_name}
                      </p>
                      <p className="text-[11px] text-pi-muted mt-0.5">
                        {row.played} played · {row.win}W {row.draw}D {row.lose}L
                      </p>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <div className="text-center">
                        <p className="text-xs font-bold text-pi-primary tabular-nums">{row.points}</p>
                        <p className="text-[9px] text-pi-muted uppercase tracking-wider">PTS</p>
                      </div>
                      <div className="text-center w-6">
                        <p className="text-xs font-bold text-pi-muted tabular-nums">#{row.rank}</p>
                      </div>
                      <ChevronRight size={14} className="text-pi-muted/40 group-hover:text-pi-indigo-light transition-colors" />
                    </div>
                  </Link>
                ) : (
                  <div key={`${row.team_name}-${row.rank}`} className="flex items-center gap-3 p-3 rounded-xl border border-pi-border/20 bg-white/[0.02]">
                    <div className="w-10 h-10 rounded-lg bg-pi-surface/60 border border-pi-border/20 flex items-center justify-center shrink-0">
                      {row.team_logo ? <img src={row.team_logo} alt={row.team_name} className="w-8 h-8 object-contain" /> : <Trophy size={14} className="text-pi-muted" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-semibold text-pi-primary text-sm truncate">{row.team_name}</p>
                      <p className="text-[11px] text-pi-muted mt-0.5">{row.played} played</p>
                    </div>
                    <div className="text-center shrink-0">
                      <p className="text-xs font-bold text-pi-primary tabular-nums">{row.points} pts</p>
                      <p className="text-[9px] text-pi-muted">#{row.rank}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* ════════════════════════════════════════════════════ */}
        {/* TOP PLAYERS                                         */}
        {/* ════════════════════════════════════════════════════ */}
        {pageTab === "players" && (
          <>
            {leadersLoading ? (
              <div className="flex flex-col items-center py-24 gap-3">
                <Spinner size={44} />
                <p className="text-xs text-pi-muted">Loading top players…</p>
              </div>
            ) : !leadersData?.categories.length ? (
              <div className="card p-8 text-center">
                <Star size={28} className="text-pi-muted mx-auto mb-3" />
                <p className="font-display text-base font-bold text-pi-primary mb-1">No Stats Available</p>
                <p className="text-sm text-pi-muted">Player statistics not available for {selectedLeague?.name} yet.</p>
              </div>
            ) : (
              <div className="space-y-5">
                {leadersData.categories.map(cat => (
                  <div key={cat.name} className="card overflow-hidden">
                    <div className="px-4 py-2.5 border-b border-pi-border/30 bg-pi-surface/40">
                      <p className="font-display font-bold text-pi-primary text-sm">{cat.name}</p>
                    </div>
                    {cat.leaders.map((player, i) => {
                      const rankColor = i === 0 ? "text-amber-400" : i === 1 ? "text-slate-300" : i === 2 ? "text-amber-600" : "text-pi-muted";
                      const inner = (
                        <>
                          <span className={`w-6 text-center shrink-0 font-bold tabular-nums text-sm ${rankColor}`}>
                            {player.rank}
                          </span>
                          <PlayerHeadshot id={player.player_id} src={player.headshot} name={player.name} />
                          <div className="flex-1 min-w-0">
                            <p className="font-semibold text-pi-primary text-sm truncate group-hover:text-pi-indigo-light transition-colors">
                              {player.name}
                            </p>
                            <div className="flex items-center gap-1.5 mt-0.5">
                              {player.team_logo && (
                                <img src={player.team_logo} alt={player.team_name} className="w-3.5 h-3.5 object-contain shrink-0"
                                  onError={e => { (e.target as HTMLImageElement).style.display = "none"; }} />
                              )}
                              <span className="text-[11px] text-pi-muted truncate">{player.team_name}</span>
                            </div>
                          </div>
                          <span className="text-xl font-extrabold text-pi-primary tabular-nums shrink-0">
                            {player.display}
                          </span>
                          {player.player_id && (
                            <ChevronRight size={14} className="text-pi-muted/40 group-hover:text-pi-indigo-light transition-colors shrink-0" />
                          )}
                        </>
                      );
                      const rowCls = "flex items-center gap-3 px-4 py-3 border-b border-pi-border/10 last:border-0 transition-colors group";
                      return player.player_id ? (
                        <Link key={player.player_id} to={`/player/soccer/${player.player_id}`} className={`${rowCls} hover:bg-white/[0.04] cursor-pointer`}>
                          {inner}
                        </Link>
                      ) : (
                        <div key={`${player.name}-${i}`} className={`${rowCls} opacity-70`}>
                          {inner}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            )}
          </>
        )}

      </div>
    </div>
  );
}
