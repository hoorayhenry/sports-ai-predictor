import { useEffect, useRef, useState, useCallback } from "react";
import { RefreshCw, Wifi, WifiOff } from "lucide-react";
import Spinner from "../components/Spinner";
import type { Match } from "../api/types";

const SSE_URL = `${import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1"}/matches/live/stream`;

type ConnectionState = "connecting" | "connected" | "reconnecting" | "error";

interface LiveData {
  live_count: number;
  matches: Match[];
  error?: string;
}

function matchMinute(m: Match): string {
  if (m.live_minute != null) return `${m.live_minute}'`;
  if (m.status === "HT") return "HT";
  if (m.status === "FT") return "FT";
  return m.status ?? "–";
}

function LiveRow({ match, prev }: { match: Match; prev?: Match }) {
  const isLive = (m: Match) => m.live_minute != null;
  const scoreChanged =
    prev &&
    (prev.home_score !== match.home_score || prev.away_score !== match.away_score);

  return (
    <div
      className={`grid grid-cols-[1fr_auto_3rem_auto_1fr] gap-1 items-center px-4 py-3 border-b border-pi-border/15 transition-colors ${
        isLive(match) ? "hover:bg-pi-emerald/4" : "hover:bg-white/2"
      } ${scoreChanged ? "animate-fade-up" : ""}`}
    >
      {/* Home team */}
      <div className="flex items-center justify-end gap-2 min-w-0">
        <span className="font-medium text-sm text-pi-primary truncate text-right leading-tight">
          {match.home_team}
        </span>
      </div>

      {/* Home score */}
      <span className={`font-display text-xl font-bold w-7 text-center tabular-nums leading-none ${
        isLive(match) ? "text-white" : "text-pi-secondary"
      }`}>
        {match.home_score ?? "–"}
      </span>

      {/* Time / Status */}
      <div className="flex flex-col items-center gap-0.5">
        <span className={`text-[11px] font-semibold font-display tracking-widest ${
          isLive(match) ? "text-pi-emerald" :
          match.status === "HT" ? "text-pi-amber" : "text-pi-muted"
        }`}>
          {matchMinute(match)}
        </span>
        {isLive(match) && (
          <span className="w-1.5 h-1.5 rounded-full bg-pi-emerald animate-pulse" />
        )}
      </div>

      {/* Away score */}
      <span className={`font-display text-xl font-bold w-7 text-center tabular-nums leading-none ${
        isLive(match) ? "text-white" : "text-pi-secondary"
      }`}>
        {match.away_score ?? "–"}
      </span>

      {/* Away team */}
      <div className="flex items-center gap-2 min-w-0">
        <span className="font-medium text-sm text-pi-primary truncate leading-tight">
          {match.away_team}
        </span>
      </div>
    </div>
  );
}

function CompetitionBlock({
  competition, country, sport_icon, matches, prevMatches,
}: {
  competition: string;
  country: string;
  sport_icon: string;
  matches: Match[];
  prevMatches: Match[];
}) {
  const liveCount = matches.filter((m) => m.live_minute != null).length;

  return (
    <div className="card overflow-hidden mb-3">
      <div className="flex items-center gap-3 px-4 py-2.5 bg-pi-surface/60 border-b border-pi-border/40">
        <span className="text-base leading-none">{sport_icon}</span>
        <div className="flex-1 min-w-0">
          {country && (
            <p className="text-[10px] font-semibold text-pi-muted uppercase tracking-wider leading-none mb-0.5">
              {country}
            </p>
          )}
          <p className="text-sm font-semibold text-pi-primary font-display tracking-wide leading-tight">
            {competition}
          </p>
        </div>
        {liveCount > 0 && (
          <span className="flex items-center gap-1.5 text-[10px] font-bold text-pi-emerald uppercase tracking-wider">
            <span className="w-1.5 h-1.5 rounded-full bg-pi-emerald animate-pulse" />
            {liveCount} Live
          </span>
        )}
      </div>

      {matches.map((m) => (
        <LiveRow
          key={m.id}
          match={m}
          prev={prevMatches.find((p) => p.id === m.id)}
        />
      ))}
    </div>
  );
}

export default function LivePage() {
  const [data, setData] = useState<LiveData | null>(null);
  const [prevData, setPrevData] = useState<LiveData | null>(null);
  const [connState, setConnState] = useState<ConnectionState>("connecting");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [secondsSince, setSecondsSince] = useState(0);
  const esRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
    }
    setConnState("connecting");
    const es = new EventSource(SSE_URL);
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const payload: LiveData = JSON.parse(e.data);
        if (!payload.error) {
          setPrevData((d) => d);
          setData((prev) => { setPrevData(prev); return payload; });
          setLastUpdated(new Date());
          setSecondsSince(0);
          setConnState("connected");
        }
      } catch { /* ignore parse errors */ }
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
      setConnState("reconnecting");
      retryRef.current = setTimeout(() => connect(), 5000);
    };
  }, []);

  // Connect on mount, clean up on unmount
  useEffect(() => {
    connect();
    return () => {
      esRef.current?.close();
      if (retryRef.current) clearTimeout(retryRef.current);
    };
  }, [connect]);

  // Tick seconds-since counter every second
  useEffect(() => {
    const timer = setInterval(() => {
      setSecondsSince((s) => s + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const matches = data?.matches ?? [];
  const liveCount = data?.live_count ?? 0;

  // Group by competition
  const grouped = new Map<string, { competition: string; country: string; sport_icon: string; matches: Match[] }>();
  for (const m of matches) {
    const key = `${m.sport_icon}::${m.competition}`;
    if (!grouped.has(key)) {
      grouped.set(key, { competition: m.competition, country: m.country ?? "", sport_icon: m.sport_icon, matches: [] });
    }
    grouped.get(key)!.matches.push(m);
  }
  // Live competitions first
  const sorted = [...grouped.values()].sort((a, b) => {
    const aLive = a.matches.some((m) => m.live_minute != null) ? -1 : 1;
    const bLive = b.matches.some((m) => m.live_minute != null) ? -1 : 1;
    return aLive - bLive;
  });

  const prevMatches = prevData?.matches ?? [];

  return (
    <div className="min-h-screen pb-24 md:pb-8">
      {/* Hero */}
      <div className="relative overflow-hidden rounded-b-2xl md:rounded-2xl md:mx-4 md:mt-4 mb-5">
        <img
          src="https://images.unsplash.com/photo-1551958219-acbc608c6377?w=1400&q=80&auto=format&fit=crop"
          alt=""
          className="absolute inset-0 w-full h-full object-cover object-center brightness-75 saturate-125 select-none pointer-events-none"
          aria-hidden="true"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/10 via-black/25 to-[#070c19]/92" />
        <div className="absolute inset-0 bg-gradient-to-r from-[#070c19]/80 via-transparent to-transparent" />

        <div className="relative px-5 pt-7 pb-6 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="flex items-center gap-1.5 section-label text-pi-emerald/80">
                <span className="w-1.5 h-1.5 rounded-full bg-pi-emerald animate-pulse inline-block" />
                In Progress
              </span>
            </div>
            <h1 className="text-3xl md:text-4xl font-extrabold text-white font-display leading-none mb-1 drop-shadow-lg">
              Live Scores
            </h1>
            <p className="text-pi-secondary text-sm leading-relaxed">
              {liveCount > 0
                ? `${liveCount} matches in progress right now`
                : connState === "connecting" || connState === "reconnecting"
                ? "Connecting to live feed..."
                : "No live matches at the moment"}
            </p>
          </div>

          {/* Connection status */}
          <div className="flex flex-col items-end gap-1.5 mt-1">
            <div className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-full border text-[11px] font-semibold ${
              connState === "connected"
                ? "bg-pi-emerald/10 border-pi-emerald/30 text-pi-emerald"
                : connState === "connecting" || connState === "reconnecting"
                ? "bg-pi-amber/10 border-amber-500/30 text-pi-amber"
                : "bg-rose-500/10 border-rose-500/30 text-rose-400"
            }`}>
              {connState === "connected"
                ? <><Wifi size={11} /> Live</>
                : connState === "reconnecting"
                ? <><RefreshCw size={11} className="animate-spin" /> Reconnecting</>
                : <><WifiOff size={11} /> Offline</>}
            </div>
            {connState === "connected" && lastUpdated && (
              <span className="text-[10px] text-pi-muted/60">
                Updated {secondsSince < 5 ? "just now" : `${secondsSince}s ago`}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="px-4">
        {connState === "connecting" && !data ? (
          <div className="flex flex-col items-center py-20 gap-3">
            <Spinner size={36} />
            <p className="text-sm text-pi-muted">Connecting to live feed…</p>
          </div>
        ) : matches.length === 0 ? (
          <div className="card p-8 text-center">
            <div className="w-14 h-14 rounded-2xl bg-pi-surface border border-pi-border flex items-center justify-center mx-auto mb-4">
              <Wifi size={22} className="text-pi-muted" />
            </div>
            <p className="font-display text-lg text-pi-primary font-semibold mb-1 tracking-wide">
              No Live Matches
            </p>
            <p className="text-sm text-pi-muted max-w-xs mx-auto leading-relaxed">
              The feed is connected and watching — scores will appear here the moment a match kicks off.
            </p>
            <p className="text-[11px] text-pi-muted/50 mt-3">
              Auto-updates every 20 seconds via live stream
            </p>
          </div>
        ) : (
          <>
            {/* Summary bar */}
            <div className="flex items-center gap-3 mb-4 px-1">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-pi-emerald animate-pulse" />
                <span className="text-xs font-semibold text-pi-emerald uppercase tracking-wider">
                  {liveCount} Live
                </span>
              </div>
              <div className="h-3 w-px bg-pi-border" />
              <span className="text-xs text-pi-muted">
                {matches.length} matches · {sorted.length} competitions
              </span>
              <span className="ml-auto text-[10px] text-pi-muted/50 flex items-center gap-1">
                <span className="w-1 h-1 rounded-full bg-pi-emerald/50 animate-pulse" />
                Real-time stream · updates every 20s
              </span>
            </div>

            {sorted.map((g) => (
              <CompetitionBlock
                key={`${g.sport_icon}::${g.competition}`}
                competition={g.competition}
                country={g.country}
                sport_icon={g.sport_icon}
                matches={g.matches}
                prevMatches={prevMatches}
              />
            ))}
          </>
        )}
      </div>
    </div>
  );
}
