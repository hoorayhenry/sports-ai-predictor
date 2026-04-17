import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, MapPin, Users, Newspaper, Trophy,
  User, Calendar, TrendingUp, ChevronRight,
} from "lucide-react";
import Spinner from "../components/Spinner";
import { api } from "../api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

interface TeamData {
  id: string;
  name: string;
  short_name: string;
  nickname: string;
  logo: string;
  logo_dark: string;
  primary_color: string;
  alt_color: string;
  founded?: number;
  description: string;
  location: string;
  venue: { name: string; city: string; country: string; capacity?: number };
  record: string;
  coach: string;
  league_slug: string;
}

interface MatchSide {
  id: string;
  name: string;
  short: string;
  logo: string;
  score: string;
  winner: boolean;
  home_away: string;
}

interface Result {
  date: string;
  competitors: MatchSide[];
  outcome: "W" | "D" | "L" | "";
  venue: string;
  competition?: string;
}

interface NextFixture {
  name: string;
  date: string;
  venue: string;
  competition: string;
  competitors: { id: string; name: string; logo: string; home_away: string }[];
}

interface SeasonRecord {
  summary: string;
  played: number;
  wins: number;
  draws: number;
  losses: number;
  goals_for: number;
  goals_against: number;
  points: number;
  home_wins: number;
  away_wins: number;
  standing: string;
}

interface ScheduleData {
  results: Result[];
  next_fix: NextFixture | null;
  record: SeasonRecord;
  cached?: boolean;
}

interface Player {
  id: string;
  name: string;
  shirt_number?: string | number;
  position: string;
  position_abbr: string;
  nationality: string;
  age?: number;
  headshot: string;
  status: string;
}

interface SquadData { players: Player[] }

interface NewsArticle {
  id: number; title: string; summary: string; category: string;
  image_url: string | null; published_at: string | null; created_at: string;
}

type Tab = "overview" | "results" | "squad" | "news";

// ── Helpers ───────────────────────────────────────────────────────────────────

const POS_ORDER: Record<string, number> = { G: 0, GK: 0, D: 1, M: 2, MF: 2, F: 3, FW: 3 };
const POS_LABEL: Record<string, string> = {
  G: "Goalkeepers", GK: "Goalkeepers",
  D: "Defenders",
  M: "Midfielders", MF: "Midfielders",
  F: "Forwards",    FW: "Forwards",
};

function groupByPosition(players: Player[]): [string, Player[]][] {
  const groups: Record<string, Player[]> = {};
  for (const p of players) {
    const key = p.position_abbr || "Unknown";
    if (!groups[key]) groups[key] = [];
    groups[key].push(p);
  }
  return Object.entries(groups).sort(
    ([a], [b]) => (POS_ORDER[a] ?? 9) - (POS_ORDER[b] ?? 9)
  );
}

function fmtDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}


function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3_600_000);
  if (h < 1) return "just now";
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

const OUTCOME_COLOR = {
  W: "bg-emerald-500",
  D: "bg-amber-400",
  L: "bg-rose-500",
  "": "bg-pi-surface",
};

// ── Team logo with ESPN CDN fallback ──────────────────────────────────────────
function TeamLogo({
  teamId, logoUrl, name, size = "w-8 h-8",
}: { teamId?: string; logoUrl?: string; name: string; size?: string }) {
  const [failed, setFailed] = useState(false);
  const src = (!failed && logoUrl) ? logoUrl
    : teamId ? `https://a.espncdn.com/i/teamlogos/soccer/500/${teamId}.png`
    : "";
  return src ? (
    <img
      src={src}
      alt={name}
      className={`${size} object-contain`}
      onError={() => { if (!failed) setFailed(true); }}
    />
  ) : (
    <div className={`${size} rounded-full bg-pi-surface border border-pi-border/30 flex items-center justify-center`}>
      <Trophy size={12} className="text-pi-muted" />
    </div>
  );
}

// ── Player headshot — ESPN CDN + silhouette fallback ──────────────────────────
function PlayerHeadshot({ player, size = "w-12 h-12" }: { player: Player; size?: string }) {
  const [failed, setFailed] = useState(false);
  const posColor: Record<string, string> = { G: "#f59e0b", GK: "#f59e0b", D: "#3b82f6", M: "#10b981", F: "#f43f5e" };
  const color = posColor[player.position_abbr] || "#6366f1";

  if (player.headshot && !failed) {
    return (
      <div className={`${size} rounded-full overflow-hidden shrink-0 border-2`} style={{ borderColor: `${color}55` }}>
        <img
          src={player.headshot}
          alt={player.name}
          className="w-full h-full object-cover object-top"
          onError={() => setFailed(true)}
        />
      </div>
    );
  }

  // Fallback: shirt number on colored background
  return (
    <div
      className={`${size} rounded-full shrink-0 flex items-center justify-center font-bold text-white text-sm border-2`}
      style={{ background: `${color}33`, borderColor: `${color}55`, color }}
    >
      {player.shirt_number || <User size={14} />}
    </div>
  );
}

// ── Upcoming fixture card ─────────────────────────────────────────────────────
function FixtureCard({ fixture }: { fixture: NextFixture }) {
  const home = fixture.competitors.find(c => c.home_away === "home");
  const away = fixture.competitors.find(c => c.home_away === "away");

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-2.5 border-b border-pi-border/30 flex items-center justify-between">
        <span className="section-label text-pi-muted">Upcoming Fixture</span>
        <span className="text-xs text-pi-muted">{fixture.competition}</span>
      </div>
      <div className="p-5">
        <div className="flex items-center justify-between gap-4">
          {/* Home */}
          <div className="flex-1 flex flex-col items-center gap-2">
            <TeamLogo teamId={home?.id} logoUrl={home?.logo} name={home?.name || ""} size="w-14 h-14" />
            <p className="font-bold text-pi-primary text-sm text-center">{home?.name}</p>
            <span className="text-[10px] text-pi-muted bg-pi-surface px-2 py-0.5 rounded-full">HOME</span>
          </div>

          {/* Middle: date + time */}
          <div className="flex flex-col items-center gap-1 shrink-0">
            <div className="text-center">
              <p className="text-lg font-bold text-pi-primary">{fmtDate(fixture.date)}</p>
              <p className="text-sm text-pi-muted">
                {fixture.date ? new Date(fixture.date + "Z").toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : ""}
              </p>
            </div>
            <span className="text-[10px] text-emerald-400/80 font-semibold bg-emerald-500/10 px-2.5 py-0.5 rounded-full border border-emerald-500/20">
              UPCOMING
            </span>
          </div>

          {/* Away */}
          <div className="flex-1 flex flex-col items-center gap-2">
            <TeamLogo teamId={away?.id} logoUrl={away?.logo} name={away?.name || ""} size="w-14 h-14" />
            <p className="font-bold text-pi-primary text-sm text-center">{away?.name}</p>
            <span className="text-[10px] text-pi-muted bg-pi-surface px-2 py-0.5 rounded-full">AWAY</span>
          </div>
        </div>
        {fixture.venue && (
          <p className="flex items-center justify-center gap-1.5 text-xs text-pi-muted mt-3">
            <MapPin size={11} />
            {fixture.venue}
          </p>
        )}
      </div>
    </div>
  );
}

// ── Result row ────────────────────────────────────────────────────────────────
function ResultRow({ result, showCompetition = false }: { result: Result; teamId: string; showCompetition?: boolean }) {
  const home = result.competitors.find(c => c.home_away === "home");
  const away = result.competitors.find(c => c.home_away === "away");
  if (!home || !away) return null;

  return (
    <div className="flex flex-col border-b border-pi-border/10 last:border-0 hover:bg-white/[0.02] transition-colors">
      {showCompetition && result.competition && (
        <div className="px-4 pt-2 pb-0">
          <span className="text-[10px] font-semibold text-pi-indigo-light/70 bg-pi-indigo/10 border border-pi-indigo/20 px-1.5 py-0.5 rounded">
            {result.competition}
          </span>
        </div>
      )}
      <div className="flex items-center gap-3 px-4 py-2.5">
        {/* Date */}
        <span className="text-xs text-pi-muted w-14 shrink-0">{fmtDate(result.date)}</span>

        {/* FT badge */}
        <span className="text-[10px] font-bold text-pi-muted border border-pi-border/40 px-1.5 py-0.5 rounded shrink-0">FT</span>

        {/* Outcome dot */}
        {result.outcome && (
          <span className={`w-5 h-5 rounded-full shrink-0 flex items-center justify-center text-[9px] font-bold text-white ${OUTCOME_COLOR[result.outcome]}`}>
            {result.outcome}
          </span>
        )}

        {/* Match */}
        <div className="flex items-center gap-2 flex-1 min-w-0">
          {/* Home team */}
          <div className="flex items-center gap-1.5 flex-1 justify-end min-w-0">
            <span className={`text-[13px] font-semibold truncate ${home.winner ? "text-pi-primary" : "text-pi-secondary"}`}>
              {home.short || home.name}
            </span>
            <TeamLogo teamId={home.id} logoUrl={home.logo} name={home.name} size="w-5 h-5" />
          </div>

          {/* Score */}
          <div className="flex items-center gap-1 shrink-0">
            <span className={`text-sm font-bold w-5 text-center tabular-nums ${home.winner ? "text-pi-primary" : "text-pi-muted"}`}>
              {home.score}
            </span>
            <span className="text-pi-muted/40 text-xs">-</span>
            <span className={`text-sm font-bold w-5 text-center tabular-nums ${away.winner ? "text-pi-primary" : "text-pi-muted"}`}>
              {away.score}
            </span>
          </div>

          {/* Away team */}
          <div className="flex items-center gap-1.5 flex-1 min-w-0">
            <TeamLogo teamId={away.id} logoUrl={away.logo} name={away.name} size="w-5 h-5" />
            <span className={`text-[13px] font-semibold truncate ${away.winner ? "text-pi-primary" : "text-pi-secondary"}`}>
              {away.short || away.name}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Season record bar ─────────────────────────────────────────────────────────
function RecordBar({ record }: { record: SeasonRecord }) {
  const total = record.played || 1;
  const wPct  = (record.wins   / total) * 100;
  const dPct  = (record.draws  / total) * 100;
  const lPct  = (record.losses / total) * 100;

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="section-label text-pi-muted">Season Record</span>
        <span className="text-xs font-bold text-pi-secondary">{record.standing}</span>
      </div>

      {/* W/D/L bar */}
      <div className="flex h-2 rounded-full overflow-hidden gap-0.5">
        <div className="bg-emerald-500 rounded-l-full transition-all" style={{ width: `${wPct}%` }} />
        <div className="bg-amber-400 transition-all"                   style={{ width: `${dPct}%` }} />
        <div className="bg-rose-500 rounded-r-full transition-all"     style={{ width: `${lPct}%` }} />
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-6 gap-2 text-center">
        {[
          { label: "W", value: record.wins,          color: "text-emerald-400" },
          { label: "D", value: record.draws,         color: "text-amber-400" },
          { label: "L", value: record.losses,        color: "text-rose-400" },
          { label: "GF", value: record.goals_for,    color: "text-pi-primary" },
          { label: "GA", value: record.goals_against, color: "text-pi-secondary" },
          { label: "PTS", value: record.points,      color: "text-pi-indigo-light" },
        ].map(({ label, value, color }) => (
          <div key={label}>
            <p className={`text-lg font-bold tabular-nums ${color}`}>{value}</p>
            <p className="text-[10px] text-pi-muted uppercase tracking-wider">{label}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Player card (squad grid) ──────────────────────────────────────────────────
function PlayerCard({ player }: { player: Player }) {
  return (
    <Link
      to={`/player/soccer/${player.id}`}
      className="flex items-center gap-3 p-3 rounded-xl border border-pi-border/20 bg-white/[0.02] hover:bg-white/[0.05] hover:border-pi-indigo/30 transition-all group"
    >
      <PlayerHeadshot player={player} />
      <div className="flex-1 min-w-0">
        <p className="font-semibold text-pi-primary text-sm truncate group-hover:text-pi-indigo-light transition-colors">
          {player.name}
        </p>
        <p className="text-[11px] text-pi-muted">
          {player.nationality || player.position || "—"}
          {player.age ? ` · ${player.age} yrs` : ""}
        </p>
      </div>
      {player.shirt_number && (
        <span className="text-base font-bold text-pi-indigo-light/50 tabular-nums shrink-0 w-7 text-right">
          {player.shirt_number}
        </span>
      )}
    </Link>
  );
}

// ── News card ─────────────────────────────────────────────────────────────────
function NewsCard({ article }: { article: NewsArticle }) {
  return (
    <Link
      to="/news"
      className="flex gap-3 p-3 rounded-xl border border-pi-border/20 bg-white/[0.025] hover:bg-white/[0.05] hover:border-pi-indigo/30 transition-all group"
    >
      {article.image_url && (
        <img
          src={article.image_url} alt=""
          className="w-20 h-14 object-cover rounded-lg shrink-0"
          onError={e => { (e.target as HTMLImageElement).style.display = "none"; }}
        />
      )}
      <div className="flex-1 min-w-0">
        <p className="font-semibold text-pi-primary text-sm leading-snug line-clamp-2 group-hover:text-pi-indigo-light transition-colors">
          {article.title}
        </p>
        <p className="text-[11px] text-pi-muted mt-1">
          {article.category} · {timeAgo(article.created_at)}
        </p>
      </div>
    </Link>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function TeamDetailPage() {
  const { leagueSlug, teamId } = useParams<{ leagueSlug: string; teamId: string }>();
  const navigate = useNavigate();
  const [tab, setTab]           = useState<Tab>("overview");
  const [compFilter, setCompFilter] = useState<string>("all");

  const { data: team, isLoading: teamLoading, isError: teamError } = useQuery<TeamData>({
    queryKey: ["team", leagueSlug, teamId],
    queryFn:  () => api.get(`/teams/${leagueSlug}/${teamId}`).then(r => r.data),
    enabled:  !!leagueSlug && !!teamId,
    staleTime: 60_000,
    retry: 1,
  });

  const { data: schedData, isLoading: schedLoading } = useQuery<ScheduleData>({
    queryKey: ["schedule-full", leagueSlug, teamId],
    queryFn:  () => api.get(`/teams/${leagueSlug}/${teamId}/schedule/full`).then(r => r.data),
    enabled:  !!leagueSlug && !!teamId && (tab === "overview" || tab === "results"),
    staleTime: 300_000,
    retry: 1,
  });

  const { data: squadData, isLoading: squadLoading } = useQuery<SquadData>({
    queryKey: ["squad", leagueSlug, teamId],
    queryFn:  () => api.get(`/teams/${leagueSlug}/${teamId}/squad`).then(r => r.data),
    enabled:  !!leagueSlug && !!teamId && tab === "squad",
    staleTime: 60_000,
    retry: 1,
  });

  const { data: newsData, isLoading: newsLoading } = useQuery<{ articles: NewsArticle[] }>({
    queryKey: ["team-news", teamId, team?.name],
    queryFn:  () =>
      api.get(`/teams/${leagueSlug}/${teamId}/news?team_name=${encodeURIComponent(team!.name)}`).then(r => r.data),
    enabled:  !!team?.name && tab === "news",
    staleTime: 120_000,
    retry: 1,
  });

  // ── Loading / error ───────────────────────────────────────────────────────
  if (teamLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center"><Spinner size={44} /></div>
    );
  }

  if (teamError || !team) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 px-6">
        <Trophy size={40} className="text-pi-muted" />
        <p className="font-display text-xl font-bold text-pi-primary">Team Not Found</p>
        <p className="text-sm text-pi-muted text-center max-w-xs">
          Could not load team data. The league slug or team ID may be incorrect.
        </p>
        <button onClick={() => navigate(-1)} className="btn-secondary">Go back</button>
      </div>
    );
  }

  const playerGroups = tab === "squad" ? groupByPosition(squadData?.players ?? []) : [];
  const record  = schedData?.record;
  const nextFix = schedData?.next_fix;
  const results = schedData?.results ?? [];

  // Competition filter
  const uniqueComps = Array.from(new Set(results.map(r => r.competition).filter(Boolean))) as string[];
  const filteredResults = compFilter === "all"
    ? results
    : results.filter(r => r.competition === compFilter);

  // ESPN CDN team logo (always reliable)
  const teamLogoUrl = `https://a.espncdn.com/i/teamlogos/soccer/500/${team.id}.png`;

  const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "overview", label: "Overview",  icon: <TrendingUp size={13} /> },
    { key: "results",  label: "Results",   icon: <Calendar size={13} /> },
    { key: "squad",    label: "Squad",     icon: <Users size={13} /> },
    { key: "news",     label: "News",      icon: <Newspaper size={13} /> },
  ];

  return (
    <div className="min-h-screen pb-24 md:pb-8">

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <div
        className="relative overflow-hidden md:rounded-2xl md:mx-4 md:mt-4"
        style={{
          background: `linear-gradient(135deg, ${team.primary_color}55 0%, #0d1020 60%)`,
          borderBottom: `2px solid ${team.primary_color}44`,
        }}
      >
        <div className="absolute inset-0 bg-[#070c19]/65" />

        {/* Back */}
        <button
          onClick={() => navigate(-1)}
          className="absolute top-4 left-4 z-10 flex items-center gap-1.5 text-xs text-white/70 hover:text-white transition-colors bg-black/30 backdrop-blur-sm px-3 py-1.5 rounded-full border border-white/10"
        >
          <ArrowLeft size={13} /> Back
        </button>

        <div className="relative z-10 px-5 pt-14 pb-0 flex items-center gap-5">
          {/* Large team logo */}
          <div
            className="w-24 h-24 rounded-2xl flex items-center justify-center shrink-0 shadow-2xl"
            style={{ background: `${team.primary_color}22`, border: `2px solid ${team.primary_color}44` }}
          >
            <img
              src={teamLogoUrl}
              alt={team.name}
              className="w-16 h-16 object-contain"
              onError={e => { (e.target as HTMLImageElement).src = team.logo; }}
            />
          </div>

          {/* Team name + info */}
          <div className="flex-1 min-w-0 pb-4">
            {team.location && (
              <p className="text-[11px] font-semibold text-white/50 uppercase tracking-wider mb-0.5">
                {team.location}
              </p>
            )}
            <h1 className="text-3xl md:text-4xl font-extrabold text-white font-display leading-none drop-shadow-lg mb-1.5">
              {team.name}
            </h1>
            <div className="flex flex-wrap gap-2 items-center">
              {record?.standing && (
                <span className="text-xs font-semibold text-white/70 bg-white/10 px-2.5 py-1 rounded-full border border-white/10">
                  {record.standing}
                </span>
              )}
              {record?.summary && (
                <span className="text-xs text-white/40 font-mono">{record.summary}</span>
              )}
            </div>
          </div>
        </div>

        {/* Tab bar */}
        <div className="relative z-10 px-2 flex gap-0 border-t border-white/10 mt-3 overflow-x-auto">
          {TABS.map(({ key, label, icon }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex items-center gap-1.5 px-4 py-3 text-xs font-semibold whitespace-nowrap transition-all border-b-2 ${
                tab === key
                  ? "border-white text-white"
                  : "border-transparent text-white/40 hover:text-white/70"
              }`}
            >
              {icon}{label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Tab content ──────────────────────────────────────────────────────── */}
      <div className="px-4 pt-5 max-w-2xl mx-auto">

        {/* OVERVIEW ──────────────────────────────────────────────────────────── */}
        {tab === "overview" && (
          <div className="space-y-4">
            {schedLoading ? (
              <div className="flex justify-center py-12"><Spinner size={36} /></div>
            ) : (
              <>
                {/* Upcoming fixture */}
                {nextFix && <FixtureCard fixture={nextFix} />}

                {/* Recent results (last 5) */}
                {results.length > 0 && (
                  <div className="card overflow-hidden">
                    <div className="px-4 py-2.5 border-b border-pi-border/30 flex items-center justify-between">
                      <span className="section-label text-pi-muted">Recent Results</span>
                      <button
                        onClick={() => setTab("results")}
                        className="text-[11px] text-pi-indigo-light flex items-center gap-1 hover:underline"
                      >
                        All results <ChevronRight size={11} />
                      </button>
                    </div>
                    {results.slice(0, 5).map((r, i) => (
                      <ResultRow key={i} result={r} teamId={team.id} showCompetition />
                    ))}
                  </div>
                )}

                {/* Season record */}
                {record && record.played > 0 && <RecordBar record={record} />}

                {/* Venue + Coach */}
                <div className="grid grid-cols-2 gap-3">
                  {team.venue?.name && (
                    <div className="card p-4">
                      <div className="flex items-center gap-2 mb-1.5">
                        <MapPin size={13} className="text-pi-indigo-light" />
                        <span className="section-label text-pi-muted">Stadium</span>
                      </div>
                      <p className="font-semibold text-pi-primary text-sm">{team.venue.name}</p>
                      {team.venue.city && (
                        <p className="text-xs text-pi-muted mt-0.5">{team.venue.city}</p>
                      )}
                      {team.venue.capacity && (
                        <p className="text-xs text-pi-muted">Cap. {team.venue.capacity.toLocaleString()}</p>
                      )}
                    </div>
                  )}
                  {team.coach && (
                    <div className="card p-4">
                      <div className="flex items-center gap-2 mb-1.5">
                        <User size={13} className="text-pi-indigo-light" />
                        <span className="section-label text-pi-muted">Head Coach</span>
                      </div>
                      <p className="font-semibold text-pi-primary text-sm">{team.coach}</p>
                    </div>
                  )}
                </div>

                {team.description && (
                  <div className="card p-4">
                    <p className="text-sm text-pi-secondary leading-relaxed">{team.description}</p>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* RESULTS ──────────────────────────────────────────────────────────── */}
        {tab === "results" && (
          <div className="space-y-3">
            {schedLoading ? (
              <div className="flex flex-col items-center py-20 gap-3">
                <Spinner size={36} />
                <p className="text-xs text-pi-muted">Loading results…</p>
              </div>
            ) : results.length === 0 ? (
              <div className="card p-8 text-center">
                <Calendar size={28} className="text-pi-muted mx-auto mb-3" />
                <p className="font-display text-base font-bold text-pi-primary mb-1">No Results Yet</p>
                <p className="text-sm text-pi-muted">No completed matches found for this team.</p>
              </div>
            ) : (
              <>
                {/* Competition filter */}
                {uniqueComps.length > 1 && (
                  <div className="flex items-center gap-2">
                    <select
                      value={compFilter}
                      onChange={e => setCompFilter(e.target.value)}
                      className="bg-pi-surface border border-pi-border/60 text-pi-primary text-xs font-semibold rounded-lg px-3 py-2 cursor-pointer focus:outline-none focus:border-pi-indigo/50 transition-colors flex-1"
                    >
                      <option value="all">All Competitions ({results.length})</option>
                      {uniqueComps.map(c => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="card overflow-hidden">
                  <div className="px-4 py-2.5 border-b border-pi-border/30 flex items-center justify-between">
                    <span className="section-label text-pi-muted">
                      {filteredResults.length} Match{filteredResults.length !== 1 ? "es" : ""}
                      {compFilter !== "all" ? ` · ${compFilter}` : " · All Competitions"}
                    </span>
                    {compFilter !== "all" && (
                      <button
                        onClick={() => setCompFilter("all")}
                        className="text-[10px] text-pi-muted hover:text-pi-indigo-light transition-colors"
                      >
                        Clear filter
                      </button>
                    )}
                  </div>
                  {filteredResults.length === 0 ? (
                    <div className="p-8 text-center">
                      <p className="text-sm text-pi-muted">No matches for this competition.</p>
                    </div>
                  ) : (
                    filteredResults.map((r, i) => (
                      <ResultRow key={i} result={r} teamId={team.id} showCompetition={compFilter === "all"} />
                    ))
                  )}
                </div>
              </>
            )}
          </div>
        )}

        {/* SQUAD ──────────────────────────────────────────────────────────────── */}
        {tab === "squad" && (
          <div>
            {squadLoading ? (
              <div className="flex flex-col items-center py-20 gap-3">
                <Spinner size={36} />
                <p className="text-xs text-pi-muted">Loading squad…</p>
              </div>
            ) : playerGroups.length === 0 ? (
              <div className="card p-8 text-center">
                <Users size={28} className="text-pi-muted mx-auto mb-3" />
                <p className="font-display text-base font-bold text-pi-primary mb-1">Squad Unavailable</p>
                <p className="text-sm text-pi-muted">ESPN doesn't have squad data for this team right now.</p>
              </div>
            ) : (
              <div className="space-y-5">
                {playerGroups.map(([posAbbr, players]) => (
                  <div key={posAbbr}>
                    <h3 className="section-label text-pi-muted mb-2 px-1">
                      {POS_LABEL[posAbbr] || players[0]?.position || posAbbr} ({players.length})
                    </h3>
                    <div className="space-y-2">
                      {players
                        .sort((a, b) => Number(a.shirt_number || 99) - Number(b.shirt_number || 99))
                        .map(p => <PlayerCard key={p.id} player={p} />)}
                    </div>
                  </div>
                ))}
                <p className="text-[11px] text-pi-muted/40 text-center pb-2">
                  Player photos from ESPN CDN · shown where available
                </p>
              </div>
            )}
          </div>
        )}

        {/* NEWS ──────────────────────────────────────────────────────────────── */}
        {tab === "news" && (
          <div>
            {newsLoading ? (
              <div className="flex flex-col items-center py-20 gap-3">
                <Spinner size={36} />
              </div>
            ) : !newsData?.articles.length ? (
              <div className="card p-8 text-center">
                <Newspaper size={28} className="text-pi-muted mx-auto mb-3" />
                <p className="font-display text-base font-bold text-pi-primary mb-1">No Articles Yet</p>
                <p className="text-sm text-pi-muted">
                  No published articles mention {team.name} yet.
                </p>
                <Link to="/news" className="mt-4 inline-block btn-secondary text-xs">Browse all news</Link>
              </div>
            ) : (
              <div className="space-y-3">
                {newsData.articles.map(a => <NewsCard key={a.id} article={a} />)}
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
}
