import { useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, Users, Calendar, Trophy, ChevronRight, MapPin, Globe,
} from "lucide-react";
import Spinner from "../components/Spinner";

const SS = "https://api.sofascore.com/api/v1";
const _noRefetch = { refetchOnWindowFocus: false, refetchOnReconnect: false } as const;

// ── Types ─────────────────────────────────────────────────────────────────────

interface SsTeamDetail {
  id: number;
  name: string;
  shortName: string;
  nameCode: string;
  country?: { name: string; alpha2: string };
  foundationDateTimestamp?: number;
  venue?: { name: string; city?: { name: string } };
  manager?: { name: string };
  primaryUniqueTournament?: { id: number; name: string };
}

interface SsPlayer {
  id: number;
  name: string;
  position: string;
  jerseyNumber?: string;
  nationality?: string;
  dateOfBirthTimestamp?: number;
  height?: number;
}

interface SsEvent {
  id: number;
  startTimestamp: number;
  status: { type: string };
  homeTeam: { id: number; name: string; shortName?: string };
  awayTeam: { id: number; name: string; shortName?: string };
  homeScore?: { current?: number };
  awayScore?: { current?: number };
  tournament?: { name: string; id: number };
  time?: { played?: number };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function SsTeamLogo({ id, size = "w-8 h-8" }: { id: number; size?: string }) {
  const [err, setErr] = useState(false);
  if (err) return <div className={`${size} rounded-full bg-pi-surface border border-pi-border/30 shrink-0`} />;
  return (
    <img
      src={`${SS}/team/${id}/image`}
      alt=""
      className={`${size} object-contain shrink-0`}
      onError={() => setErr(true)}
    />
  );
}

function SsPlayerPhoto({ id, size = "w-10 h-10" }: { id: number; size?: string }) {
  const [err, setErr] = useState(false);
  if (err) return (
    <div className={`${size} rounded-full bg-pi-surface border border-pi-border/30 shrink-0 flex items-center justify-center`}>
      <Users size={14} className="text-pi-muted" />
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

const fmtDate = (ts: number) =>
  new Date(ts * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

const fmtTime = (ts: number) =>
  new Date(ts * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

const fmtDateLabel = (ts: number) =>
  new Date(ts * 1000).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });

function normEvent(ev: SsEvent, teamId: number) {
  const sc = ev.status?.type ?? "notstarted";
  const status: "live" | "finished" | "scheduled" =
    sc === "inprogress" ? "live" : sc === "finished" ? "finished" : "scheduled";
  const isHome = ev.homeTeam?.id === teamId;
  const opp = isHome ? ev.awayTeam : ev.homeTeam;
  const myScore = status !== "scheduled"
    ? (isHome ? ev.homeScore?.current : ev.awayScore?.current) ?? null
    : null;
  const oppScore = status !== "scheduled"
    ? (isHome ? ev.awayScore?.current : ev.homeScore?.current) ?? null
    : null;
  let outcome: "W" | "D" | "L" | null = null;
  if (status === "finished" && myScore !== null && oppScore !== null) {
    outcome = myScore > oppScore ? "W" : myScore === oppScore ? "D" : "L";
  }
  return { ev, status, isHome, opp, myScore, oppScore, outcome };
}

function EventRow({ ev, teamId }: { ev: SsEvent; teamId: number }) {
  const { status, isHome, opp, myScore, oppScore, outcome } = normEvent(ev, teamId);
  const outcomeColor = outcome === "W" ? "text-emerald-400" : outcome === "L" ? "text-rose-400" : "text-amber-400";

  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-pi-border/10 last:border-0 hover:bg-white/[0.02] transition-colors">
      {/* Date / Status */}
      <div className="shrink-0 w-14 text-center">
        {status === "live" ? (
          <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/15 border border-emerald-500/30 px-1.5 py-0.5 rounded-full">
            LIVE {ev.time?.played ? `${ev.time.played}'` : ""}
          </span>
        ) : status === "finished" ? (
          <span className="text-[10px] text-pi-muted">FT</span>
        ) : (
          <div>
            <p className="text-[11px] font-semibold text-pi-primary">{fmtTime(ev.startTimestamp)}</p>
            <p className="text-[10px] text-pi-muted">{fmtDateLabel(ev.startTimestamp)}</p>
          </div>
        )}
      </div>

      {/* H/A badge */}
      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 ${isHome ? "bg-pi-indigo/20 text-pi-indigo-light" : "bg-white/5 text-pi-muted"}`}>
        {isHome ? "H" : "A"}
      </span>

      {/* Opponent */}
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <SsTeamLogo id={opp.id} size="w-5 h-5" />
        <span className="text-[13px] font-medium text-pi-primary truncate">
          {opp.shortName ?? opp.name}
        </span>
      </div>

      {/* Score / Outcome */}
      {status === "finished" && myScore !== null && oppScore !== null ? (
        <div className="flex items-center gap-1.5 shrink-0">
          <span className={`text-sm font-bold tabular-nums ${outcomeColor}`}>
            {myScore}–{oppScore}
          </span>
          {outcome && (
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
              outcome === "W" ? "bg-emerald-500/15 text-emerald-400" :
              outcome === "L" ? "bg-rose-500/15 text-rose-400" :
              "bg-amber-500/15 text-amber-400"
            }`}>{outcome}</span>
          )}
        </div>
      ) : status === "live" && myScore !== null ? (
        <span className="text-sm font-bold text-emerald-400 tabular-nums shrink-0">{myScore}–{oppScore}</span>
      ) : null}

      {/* Tournament name */}
      {ev.tournament?.name && (
        <span className="hidden md:block text-[11px] text-pi-muted/60 shrink-0 max-w-[120px] truncate">
          {ev.tournament.name}
        </span>
      )}
    </div>
  );
}

function FormDot({ outcome }: { outcome: "W" | "D" | "L" | null }) {
  const cls = outcome === "W" ? "bg-emerald-500" : outcome === "L" ? "bg-rose-500" : outcome === "D" ? "bg-amber-500" : "bg-pi-border/30";
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${cls}`} title={outcome ?? "?"} />;
}

// ── Main page ─────────────────────────────────────────────────────────────────

type Tab = "overview" | "squad" | "matches";

export default function SsTeamPage() {
  const { teamId } = useParams<{ teamId: string }>();
  const navigate = useNavigate();
  const id = Number(teamId);
  const [tab, setTab] = useState<Tab>("overview");

  // Team detail
  const { data: teamData, isLoading: teamLoading } = useQuery<SsTeamDetail>({
    queryKey: ["ss-team-detail", id],
    queryFn: async () => {
      const r = await fetch(`${SS}/team/${id}`);
      if (!r.ok) throw new Error(`Sofascore team ${r.status}`);
      const d = await r.json();
      return d.team as SsTeamDetail;
    },
    staleTime: 24 * 60 * 60 * 1000,
    ...(_noRefetch),
  });

  // Squad
  const { data: squadData, isLoading: squadLoading } = useQuery<{ players: SsPlayer[] }>({
    queryKey: ["ss-team-players", id],
    queryFn: async () => {
      const r = await fetch(`${SS}/team/${id}/players`);
      if (!r.ok) throw new Error(`Sofascore players ${r.status}`);
      const d = await r.json();
      const players: SsPlayer[] = (d.players ?? []).map((p: any) => ({
        id: p.player?.id ?? 0,
        name: p.player?.name ?? "",
        position: p.player?.position ?? "Unknown",
        jerseyNumber: p.player?.jerseyNumber,
        nationality: p.player?.nationality?.name,
        dateOfBirthTimestamp: p.player?.dateOfBirthTimestamp,
        height: p.player?.height,
      })).filter((p: SsPlayer) => p.id > 0);
      return { players };
    },
    enabled: tab === "squad" || tab === "overview",
    staleTime: 24 * 60 * 60 * 1000,
    ...(_noRefetch),
  });

  // Past events
  const { data: pastEvents, isLoading: pastLoading } = useQuery<SsEvent[]>({
    queryKey: ["ss-team-events-last", id],
    queryFn: async () => {
      const evs: SsEvent[] = [];
      for (let pg = 0; pg < 3; pg++) {
        try {
          const r = await fetch(`${SS}/team/${id}/events/last/${pg}`);
          if (!r.ok) break;
          const d = await r.json();
          evs.push(...(d.events ?? []));
        } catch { break; }
      }
      return evs.sort((a, b) => b.startTimestamp - a.startTimestamp);
    },
    enabled: tab === "overview" || tab === "matches",
    staleTime: 10 * 60 * 1000,
    ...(_noRefetch),
  });

  // Next fixtures
  const { data: nextEvents, isLoading: nextLoading } = useQuery<SsEvent[]>({
    queryKey: ["ss-team-events-next", id],
    queryFn: async () => {
      const evs: SsEvent[] = [];
      for (let pg = 0; pg < 2; pg++) {
        try {
          const r = await fetch(`${SS}/team/${id}/events/next/${pg}`);
          if (!r.ok) break;
          const d = await r.json();
          evs.push(...(d.events ?? []));
        } catch { break; }
      }
      return evs.sort((a, b) => a.startTimestamp - b.startTimestamp);
    },
    enabled: tab === "overview" || tab === "matches",
    staleTime: 10 * 60 * 1000,
    ...(_noRefetch),
  });

  if (teamLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Spinner size={40} />
      </div>
    );
  }

  if (!teamData) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <p className="text-pi-muted">Team not found.</p>
        <button onClick={() => navigate(-1)} className="text-pi-indigo-light text-sm hover:underline flex items-center gap-1">
          <ArrowLeft size={14} /> Back
        </button>
      </div>
    );
  }

  // Last 5 form
  const last5 = (pastEvents ?? []).slice(0, 5).map(ev => normEvent(ev, id).outcome);

  const positionOrder: Record<string, number> = { G: 0, D: 1, M: 2, F: 3 };
  const sortedSquad = [...(squadData?.players ?? [])].sort(
    (a, b) => (positionOrder[a.position] ?? 9) - (positionOrder[b.position] ?? 9)
  );

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "overview", label: "Overview",  icon: <Trophy size={12} /> },
    { key: "squad",    label: "Squad",     icon: <Users size={12} /> },
    { key: "matches",  label: "Matches",   icon: <Calendar size={12} /> },
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
          <SsTeamLogo id={id} size="w-16 h-16" />
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl font-extrabold text-white">{teamData.name}</h1>
            <div className="flex flex-wrap items-center gap-3 mt-1.5">
              {teamData.country && (
                <span className="flex items-center gap-1 text-[12px] text-pi-muted">
                  <Globe size={11} /> {teamData.country.name}
                </span>
              )}
              {teamData.venue?.name && (
                <span className="flex items-center gap-1 text-[12px] text-pi-muted">
                  <MapPin size={11} /> {teamData.venue.name}
                  {teamData.venue.city?.name ? `, ${teamData.venue.city.name}` : ""}
                </span>
              )}
              {teamData.foundationDateTimestamp && (
                <span className="text-[12px] text-pi-muted">
                  Est. {new Date(teamData.foundationDateTimestamp * 1000).getFullYear()}
                </span>
              )}
            </div>
            {teamData.manager && (
              <p className="text-[12px] text-pi-muted mt-1">Manager: <span className="text-pi-secondary">{teamData.manager.name}</span></p>
            )}

            {/* Form strip */}
            {last5.length > 0 && (
              <div className="flex items-center gap-1.5 mt-3">
                <span className="text-[10px] text-pi-muted/60 uppercase tracking-wider">Form</span>
                <div className="flex gap-1">
                  {last5.reverse().map((o, i) => <FormDot key={i} outcome={o} />)}
                </div>
              </div>
            )}
          </div>
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

        {/* ── Overview ── */}
        {tab === "overview" && (
          <div className="space-y-4">
            {/* Next fixture */}
            {nextLoading ? (
              <div className="card py-8 flex justify-center"><Spinner /></div>
            ) : (nextEvents ?? []).length > 0 ? (
              <div>
                <h3 className="text-[11px] font-bold uppercase tracking-wider text-pi-muted/60 mb-2">Next Fixture</h3>
                <div className="card p-4">
                  {(() => {
                    const next = nextEvents![0];
                    const isHome = next.homeTeam?.id === id;
                    const opp = isHome ? next.awayTeam : next.homeTeam;
                    return (
                      <div className="flex items-center gap-3">
                        <SsTeamLogo id={opp.id} size="w-10 h-10" />
                        <div className="flex-1 min-w-0">
                          <p className="font-semibold text-pi-primary">{isHome ? "vs" : "@"} {opp.name}</p>
                          <p className="text-[12px] text-pi-muted mt-0.5">
                            {fmtDate(next.startTimestamp)} · {fmtTime(next.startTimestamp)}
                          </p>
                          {next.tournament?.name && <p className="text-[11px] text-pi-muted/60 mt-0.5">{next.tournament.name}</p>}
                        </div>
                        <Link to={`/team/ss/${opp.id}`} className="text-pi-muted hover:text-pi-primary transition-colors">
                          <ChevronRight size={16} />
                        </Link>
                      </div>
                    );
                  })()}
                </div>
              </div>
            ) : null}

            {/* Recent results */}
            {pastLoading ? (
              <div className="card py-8 flex justify-center"><Spinner /></div>
            ) : (pastEvents ?? []).length > 0 ? (
              <div>
                <h3 className="text-[11px] font-bold uppercase tracking-wider text-pi-muted/60 mb-2">Recent Results</h3>
                <div className="card divide-y divide-pi-border/10">
                  {(pastEvents ?? []).slice(0, 5).map(ev => (
                    <EventRow key={ev.id} ev={ev} teamId={id} />
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-center text-pi-muted text-sm py-8">No recent results.</p>
            )}

            {/* Key players preview */}
            {(squadData?.players ?? []).length > 0 && (
              <div>
                <h3 className="text-[11px] font-bold uppercase tracking-wider text-pi-muted/60 mb-2">Squad Highlights</h3>
                <div className="card divide-y divide-pi-border/10">
                  {sortedSquad.slice(0, 6).map(p => (
                    <Link key={p.id} to={`/player/ss/${p.id}`}
                      className="flex items-center gap-3 px-4 py-3 hover:bg-white/[0.04] transition-colors group">
                      <SsPlayerPhoto id={p.id} size="w-9 h-9" />
                      <div className="flex-1 min-w-0">
                        <p className="text-[13px] font-semibold text-pi-primary truncate group-hover:text-pi-indigo-light transition-colors">{p.name}</p>
                        <p className="text-[11px] text-pi-muted">{p.position} {p.jerseyNumber ? `· #${p.jerseyNumber}` : ""}</p>
                      </div>
                      <ChevronRight size={13} className="text-pi-muted/0 group-hover:text-pi-muted/50 transition-colors shrink-0" />
                    </Link>
                  ))}
                </div>
                {sortedSquad.length > 6 && (
                  <button onClick={() => setTab("squad")} className="w-full mt-2 text-[12px] text-pi-indigo-light hover:underline py-2">
                    View full squad ({sortedSquad.length} players) →
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── Squad ── */}
        {tab === "squad" && (
          <div>
            {squadLoading ? (
              <div className="py-16 flex justify-center"><Spinner size={40} /></div>
            ) : sortedSquad.length === 0 ? (
              <p className="text-center text-pi-muted text-sm py-12">No squad data available.</p>
            ) : (
              <div className="card divide-y divide-pi-border/10">
                {sortedSquad.map(p => (
                  <Link key={p.id} to={`/player/ss/${p.id}`}
                    className="flex items-center gap-3 px-4 py-3 hover:bg-white/[0.04] transition-colors group">
                    <SsPlayerPhoto id={p.id} size="w-10 h-10" />
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] font-semibold text-pi-primary truncate group-hover:text-pi-indigo-light transition-colors">{p.name}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[10px] font-bold bg-pi-indigo/20 text-pi-indigo-light px-1.5 py-0.5 rounded">{p.position}</span>
                        {p.jerseyNumber && <span className="text-[11px] text-pi-muted">#{p.jerseyNumber}</span>}
                        {p.nationality && <span className="text-[11px] text-pi-muted">{p.nationality}</span>}
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      {p.height && <p className="text-[11px] text-pi-muted">{p.height} cm</p>}
                      {p.dateOfBirthTimestamp && (
                        <p className="text-[11px] text-pi-muted/60">{fmtDate(p.dateOfBirthTimestamp)}</p>
                      )}
                    </div>
                    <ChevronRight size={13} className="text-pi-muted/0 group-hover:text-pi-muted/50 transition-colors shrink-0 ml-2" />
                  </Link>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Matches ── */}
        {tab === "matches" && (
          <div className="space-y-4">
            {(pastLoading || nextLoading) ? (
              <div className="py-16 flex justify-center"><Spinner size={40} /></div>
            ) : (
              <>
                {(nextEvents ?? []).length > 0 && (
                  <div>
                    <h3 className="text-[11px] font-bold uppercase tracking-wider text-pi-muted/60 mb-2">Upcoming</h3>
                    <div className="card divide-y divide-pi-border/10">
                      {(nextEvents ?? []).map(ev => <EventRow key={ev.id} ev={ev} teamId={id} />)}
                    </div>
                  </div>
                )}
                {(pastEvents ?? []).length > 0 && (
                  <div>
                    <h3 className="text-[11px] font-bold uppercase tracking-wider text-pi-muted/60 mb-2">Past Results</h3>
                    <div className="card divide-y divide-pi-border/10">
                      {(pastEvents ?? []).map(ev => <EventRow key={ev.id} ev={ev} teamId={id} />)}
                    </div>
                  </div>
                )}
                {(pastEvents ?? []).length === 0 && (nextEvents ?? []).length === 0 && (
                  <p className="text-center text-pi-muted text-sm py-12">No matches found.</p>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
