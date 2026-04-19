import { useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, User, Calendar, ChevronRight, TrendingUp,
} from "lucide-react";
import Spinner from "../components/Spinner";

const SS = "https://api.sofascore.com/api/v1";
const _noRefetch = { refetchOnWindowFocus: false, refetchOnReconnect: false } as const;

// ── Types ─────────────────────────────────────────────────────────────────────

interface SsPlayerDetail {
  id: number;
  name: string;
  firstName?: string;
  lastName?: string;
  position: string;
  jerseyNumber?: string;
  height?: number;
  weight?: number;
  dateOfBirthTimestamp?: number;
  nationality?: { name: string; alpha2: string };
  preferredFoot?: string;
  shirtNumber?: number;
  team?: { id: number; name: string; shortName?: string };
  country?: { name: string; alpha2: string };
}

interface SsSeason {
  id: number;
  year: string;
  name: string;
}

interface SsStatGroup {
  groupName: string;
  statisticsItems: { name: string; key: string; value: number; per90?: number }[];
}


interface SsEvent {
  id: number;
  startTimestamp: number;
  status: { type: string };
  homeTeam: { id: number; name: string; shortName?: string };
  awayTeam: { id: number; name: string; shortName?: string };
  homeScore?: { current?: number };
  awayScore?: { current?: number };
  tournament?: { name: string };
  time?: { played?: number };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function SsPlayerPhoto({ id, size = "w-20 h-20" }: { id: number; size?: string }) {
  const [err, setErr] = useState(false);
  if (err) return (
    <div className={`${size} rounded-full bg-pi-surface border border-pi-border/30 shrink-0 flex items-center justify-center`}>
      <User size={28} className="text-pi-muted" />
    </div>
  );
  return (
    <img
      src={`${SS}/player/${id}/image`}
      alt=""
      className={`${size} rounded-full object-cover object-top shrink-0`}
      onError={() => setErr(true)}
    />
  );
}

function SsTeamLogo({ id, size = "w-5 h-5" }: { id: number; size?: string }) {
  const [err, setErr] = useState(false);
  if (err) return <div className={`${size} rounded bg-pi-surface border border-pi-border/30 shrink-0`} />;
  return (
    <img
      src={`${SS}/team/${id}/image`}
      alt=""
      className={`${size} object-contain shrink-0`}
      onError={() => setErr(true)}
    />
  );
}

const fmtDate = (ts: number) =>
  new Date(ts * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

const calcAge = (ts: number) =>
  Math.floor((Date.now() - ts * 1000) / (365.25 * 24 * 3600 * 1000));

function BioRow({ label, value }: { label: string; value: React.ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex justify-between items-center py-2.5 border-b border-pi-border/10 last:border-0">
      <span className="text-[12px] text-pi-muted">{label}</span>
      <span className="text-[13px] font-semibold text-pi-primary">{value}</span>
    </div>
  );
}

function StatBadge({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-pi-surface border border-pi-border/20 rounded-xl px-3 py-2 text-center">
      <p className="text-lg font-extrabold text-pi-primary">{value}</p>
      <p className="text-[10px] text-pi-muted uppercase tracking-wide mt-0.5">{label}</p>
    </div>
  );
}

function EventRow({ ev }: { ev: SsEvent }) {
  const sc = ev.status?.type ?? "notstarted";
  const status: "live" | "finished" | "scheduled" =
    sc === "inprogress" ? "live" : sc === "finished" ? "finished" : "scheduled";
  const fmtTime = (ts: number) => new Date(ts * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const fmtLabel = (ts: number) => new Date(ts * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-pi-border/10 last:border-0 hover:bg-white/[0.02] transition-colors">
      {/* Date */}
      <div className="shrink-0 w-14 text-center">
        {status === "live" ? (
          <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/15 border border-emerald-500/30 px-1.5 py-0.5 rounded-full">
            {ev.time?.played ? `${ev.time.played}'` : "LIVE"}
          </span>
        ) : status === "finished" ? (
          <span className="text-[10px] text-pi-muted">FT</span>
        ) : (
          <div>
            <p className="text-[11px] font-semibold text-pi-primary">{fmtTime(ev.startTimestamp)}</p>
            <p className="text-[10px] text-pi-muted">{fmtLabel(ev.startTimestamp)}</p>
          </div>
        )}
      </div>

      {/* Teams */}
      <div className="flex-1 min-w-0 space-y-0.5">
        <div className="flex items-center gap-1.5">
          <SsTeamLogo id={ev.homeTeam.id} />
          <span className="text-[12px] text-pi-primary truncate">{ev.homeTeam.shortName ?? ev.homeTeam.name}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <SsTeamLogo id={ev.awayTeam.id} />
          <span className="text-[12px] text-pi-secondary truncate">{ev.awayTeam.shortName ?? ev.awayTeam.name}</span>
        </div>
      </div>

      {/* Score */}
      {status !== "scheduled" && ev.homeScore?.current !== undefined && (
        <span className="text-sm font-bold text-pi-primary tabular-nums shrink-0">
          {ev.homeScore.current} – {ev.awayScore?.current ?? "?"}
        </span>
      )}

      {ev.tournament?.name && (
        <span className="hidden md:block text-[11px] text-pi-muted/60 shrink-0 max-w-[110px] truncate">
          {ev.tournament.name}
        </span>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type Tab = "bio" | "stats" | "matches";

export default function SsPlayerPage() {
  const { playerId } = useParams<{ playerId: string }>();
  const navigate = useNavigate();
  const id = Number(playerId);
  const [tab, setTab] = useState<Tab>("bio");
  const [selectedSeasonIdx, setSelectedSeasonIdx] = useState(0);

  // Player detail
  const { data: playerData, isLoading: playerLoading } = useQuery<SsPlayerDetail>({
    queryKey: ["ss-player-detail", id],
    queryFn: async () => {
      const r = await fetch(`${SS}/player/${id}`);
      if (!r.ok) throw new Error(`Sofascore player ${r.status}`);
      const d = await r.json();
      return d.player as SsPlayerDetail;
    },
    staleTime: 24 * 60 * 60 * 1000,
    ...(_noRefetch),
  });

  // Season stats list
  const { data: seasonsData } = useQuery<{ seasons: { season: SsSeason; team?: { id: number; name: string } }[] }>({
    queryKey: ["ss-player-seasons", id],
    queryFn: async () => {
      const r = await fetch(`${SS}/player/${id}/statistics/seasons`);
      if (!r.ok) throw new Error(`Sofascore player seasons ${r.status}`);
      const d = await r.json();
      return { seasons: d.seasons ?? [] };
    },
    enabled: tab === "stats",
    staleTime: 24 * 60 * 60 * 1000,
    ...(_noRefetch),
  });

  const seasonList = seasonsData?.seasons ?? [];
  const activeSeason = seasonList[selectedSeasonIdx];

  // Season stats for selected season
  const { data: statsData, isLoading: statsLoading } = useQuery<{ groups: SsStatGroup[] }>({
    queryKey: ["ss-player-stats", id, activeSeason?.season?.id],
    queryFn: async () => {
      const sid = activeSeason!.season.id;
      // Try the overall stats endpoint
      const r = await fetch(`${SS}/player/${id}/statistics/season/${sid}/overall`);
      if (r.ok) {
        const d = await r.json();
        return { groups: d.statistics?.groups ?? [] };
      }
      // Fallback: just return empty
      return { groups: [] };
    },
    enabled: tab === "stats" && !!activeSeason,
    staleTime: 24 * 60 * 60 * 1000,
    ...(_noRefetch),
  });

  // Recent matches
  const { data: pastEvents, isLoading: matchesLoading } = useQuery<SsEvent[]>({
    queryKey: ["ss-player-events", id],
    queryFn: async () => {
      const evs: SsEvent[] = [];
      for (let pg = 0; pg < 3; pg++) {
        try {
          const r = await fetch(`${SS}/player/${id}/events/last/${pg}`);
          if (!r.ok) break;
          const d = await r.json();
          evs.push(...(d.events ?? []));
        } catch { break; }
      }
      return evs.sort((a, b) => b.startTimestamp - a.startTimestamp);
    },
    enabled: tab === "matches",
    staleTime: 10 * 60 * 1000,
    ...(_noRefetch),
  });

  if (playerLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Spinner size={40} />
      </div>
    );
  }

  if (!playerData) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <p className="text-pi-muted">Player not found.</p>
        <button onClick={() => navigate(-1)} className="text-pi-indigo-light text-sm hover:underline flex items-center gap-1">
          <ArrowLeft size={14} /> Back
        </button>
      </div>
    );
  }

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "bio",     label: "Bio",     icon: <User size={12} /> },
    { key: "stats",   label: "Stats",   icon: <TrendingUp size={12} /> },
    { key: "matches", label: "Matches", icon: <Calendar size={12} /> },
  ];

  return (
    <div className="min-h-screen pb-24 md:pb-8">
      {/* Back */}
      <div className="px-4 pt-4">
        <button onClick={() => navigate(-1)} className="inline-flex items-center gap-1.5 text-[13px] text-pi-muted hover:text-pi-primary transition-colors">
          <ArrowLeft size={14} /> Back
        </button>
      </div>

      {/* Hero */}
      <div className="px-4 pt-4 pb-6">
        <div className="card p-5 flex items-center gap-4">
          <SsPlayerPhoto id={id} size="w-20 h-20" />
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl font-extrabold text-white leading-tight">{playerData.name}</h1>

            <div className="flex flex-wrap items-center gap-2 mt-2">
              <span className="text-[11px] font-bold bg-pi-indigo/20 text-pi-indigo-light px-2 py-0.5 rounded">
                {playerData.position}
              </span>
              {playerData.jerseyNumber && (
                <span className="text-[11px] font-bold bg-white/5 text-pi-muted px-2 py-0.5 rounded">
                  #{playerData.jerseyNumber}
                </span>
              )}
              {playerData.nationality && (
                <span className="text-[12px] text-pi-muted">{playerData.nationality.name}</span>
              )}
            </div>

            {/* Current team */}
            {playerData.team && (
              <Link to={`/team/ss/${playerData.team.id}`}
                className="flex items-center gap-1.5 mt-2 hover:text-pi-indigo-light transition-colors group">
                <SsTeamLogo id={playerData.team.id} size="w-5 h-5" />
                <span className="text-[13px] font-semibold text-pi-secondary group-hover:text-pi-indigo-light transition-colors">
                  {playerData.team.name}
                </span>
                <ChevronRight size={12} className="text-pi-muted/50" />
              </Link>
            )}
          </div>
        </div>

        {/* Quick bio badges */}
        <div className="grid grid-cols-3 gap-3 mt-3">
          {playerData.dateOfBirthTimestamp && (
            <StatBadge label="Age" value={calcAge(playerData.dateOfBirthTimestamp)} />
          )}
          {playerData.height && (
            <StatBadge label="Height" value={`${playerData.height} cm`} />
          )}
          {playerData.preferredFoot && (
            <StatBadge label="Foot" value={playerData.preferredFoot} />
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="px-4">
        <div className="flex gap-1 border-b border-pi-border/20 mb-4">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all -mb-px ${
                tab === t.key
                  ? "border-pi-indigo text-pi-primary"
                  : "border-transparent text-pi-muted hover:text-pi-secondary"
              }`}
            >
              {t.icon}{t.label}
            </button>
          ))}
        </div>

        {/* ── Bio ── */}
        {tab === "bio" && (
          <div className="card px-4">
            {playerData.dateOfBirthTimestamp && (
              <BioRow label="Date of Birth" value={`${fmtDate(playerData.dateOfBirthTimestamp)} (age ${calcAge(playerData.dateOfBirthTimestamp)})`} />
            )}
            <BioRow label="Nationality" value={playerData.nationality?.name} />
            <BioRow label="Position" value={playerData.position} />
            {playerData.jerseyNumber && <BioRow label="Jersey" value={`#${playerData.jerseyNumber}`} />}
            {playerData.height && <BioRow label="Height" value={`${playerData.height} cm`} />}
            {playerData.weight && <BioRow label="Weight" value={`${playerData.weight} kg`} />}
            {playerData.preferredFoot && <BioRow label="Preferred Foot" value={playerData.preferredFoot} />}
            {playerData.team && (
              <div className="flex justify-between items-center py-2.5 border-b border-pi-border/10 last:border-0">
                <span className="text-[12px] text-pi-muted">Current Club</span>
                <Link to={`/team/ss/${playerData.team.id}`}
                  className="flex items-center gap-1.5 hover:text-pi-indigo-light transition-colors">
                  <SsTeamLogo id={playerData.team.id} />
                  <span className="text-[13px] font-semibold text-pi-primary">{playerData.team.name}</span>
                  <ChevronRight size={12} className="text-pi-muted/50" />
                </Link>
              </div>
            )}
          </div>
        )}

        {/* ── Stats ── */}
        {tab === "stats" && (
          <div>
            {seasonList.length > 0 && (
              <div className="mb-4">
                <select
                  value={selectedSeasonIdx}
                  onChange={e => setSelectedSeasonIdx(Number(e.target.value))}
                  className="bg-pi-surface border border-pi-border/60 text-pi-primary text-xs font-semibold rounded-lg px-3 py-2 cursor-pointer focus:outline-none"
                >
                  {seasonList.map((s, i) => (
                    <option key={s.season.id} value={i}>
                      {s.season.year} {s.team ? `· ${s.team.name}` : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {statsLoading ? (
              <div className="py-16 flex justify-center"><Spinner size={40} /></div>
            ) : (statsData?.groups ?? []).length === 0 ? (
              <div className="card py-12 text-center">
                <TrendingUp size={32} className="text-pi-muted/30 mx-auto mb-3" />
                <p className="text-pi-muted text-sm">No stats available for this season.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {(statsData?.groups ?? []).map(group => (
                  <div key={group.groupName}>
                    <h3 className="text-[11px] font-bold uppercase tracking-wider text-pi-muted/60 mb-2">{group.groupName}</h3>
                    <div className="card px-4">
                      {group.statisticsItems.map(item => (
                        <div key={item.key} className="flex justify-between items-center py-2.5 border-b border-pi-border/10 last:border-0">
                          <span className="text-[12px] text-pi-muted">{item.name}</span>
                          <span className="text-[13px] font-bold text-pi-primary">{item.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Matches ── */}
        {tab === "matches" && (
          <div>
            {matchesLoading ? (
              <div className="py-16 flex justify-center"><Spinner size={40} /></div>
            ) : (pastEvents ?? []).length === 0 ? (
              <p className="text-center text-pi-muted text-sm py-12">No recent matches found.</p>
            ) : (
              <div className="card divide-y divide-pi-border/10">
                {(pastEvents ?? []).map(ev => (
                  <EventRow key={ev.id} ev={ev} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
