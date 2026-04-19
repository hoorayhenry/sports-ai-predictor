import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Search, X, Trophy, Users, Calendar, Newspaper, TrendingUp, Zap } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { getCompetitionSlug } from "../utils/competitionSlug";

const SS = "https://api.sofascore.com/api/v1";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SearchTeam {
  id: number; external_id: string; name: string; short_name: string | null;
  country: string | null; logo_url: string | null; sport: string; sport_icon: string; elo: number;
  espn_slug: string | null;
}
interface SearchComp {
  id: number; external_id: string; name: string; country: string | null;
  sport: string; sport_icon: string; espn_slug: string | null;
}
interface SearchMatch {
  id: number; home_team: string; away_team: string; home_logo: string | null; away_logo: string | null;
  competition: string | null; match_date: string | null; status: string;
  home_score: number | null; away_score: number | null; sport: string; sport_icon: string;
}
interface SearchNews {
  id: number; title: string; summary: string; image_url: string | null;
  source_name: string; published_at: string | null; slug: string; category: string;
}
interface SearchResults {
  teams: SearchTeam[]; competitions: SearchComp[];
  matches: SearchMatch[]; news: SearchNews[]; total: number;
}

interface SsResult {
  type: "team" | "player";
  id: number;
  name: string;
  sport?: string;
  country?: string;
  teamName?: string; // for players
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function TeamLogo({ url, name, size = "w-7 h-7" }: { url?: string | null; name: string; size?: string }) {
  const [err, setErr] = useState(false);
  if (!url || err) {
    return (
      <div className={`${size} rounded-lg bg-white/5 border border-pi-border/20 flex items-center justify-center shrink-0`}>
        <Trophy size={10} className="text-pi-muted/40" />
      </div>
    );
  }
  return <img src={url} alt={name} className={`${size} object-contain rounded-lg shrink-0`} onError={() => setErr(true)} />;
}

function SsTeamLogo({ id, size = "w-7 h-7" }: { id: number; size?: string }) {
  const [err, setErr] = useState(false);
  if (err) return <div className={`${size} rounded-lg bg-white/5 border border-pi-border/20 shrink-0`} />;
  return <img src={`${SS}/team/${id}/image`} alt="" className={`${size} object-contain rounded-lg shrink-0`} onError={() => setErr(true)} />;
}

function SsPlayerPhoto({ id, size = "w-7 h-7" }: { id: number; size?: string }) {
  const [err, setErr] = useState(false);
  if (err) return (
    <div className={`${size} rounded-full bg-white/5 border border-pi-border/20 flex items-center justify-center shrink-0`}>
      <Users size={10} className="text-pi-muted/40" />
    </div>
  );
  return <img src={`${SS}/player/${id}/image`} alt="" className={`${size} object-cover rounded-full shrink-0`} onError={() => setErr(true)} />;
}

const fmtDate = (iso: string) => {
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

// ── Flat result list for keyboard nav ─────────────────────────────────────────

type FlatItem =
  | { kind: "team";   data: SearchTeam }
  | { kind: "comp";   data: SearchComp }
  | { kind: "match";  data: SearchMatch }
  | { kind: "news";   data: SearchNews }
  | { kind: "ss";     data: SsResult };

function flattenResults(r: SearchResults | undefined, ss: SsResult[]): FlatItem[] {
  if (!r) return [];
  return [
    ...r.teams.map(d => ({ kind: "team" as const, data: d })),
    ...ss.map(d => ({ kind: "ss" as const, data: d })),
    ...r.competitions.map(d => ({ kind: "comp" as const, data: d })),
    ...r.matches.map(d => ({ kind: "match" as const, data: d })),
    ...r.news.map(d => ({ kind: "news" as const, data: d })),
  ];
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props { isOpen: boolean; onClose: () => void; }

export default function SearchBar({ isOpen, onClose }: Props) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [cursor, setCursor] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Debounce
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(query.trim()), 280);
    return () => clearTimeout(t);
  }, [query]);

  // Reset cursor when results change
  useEffect(() => { setCursor(-1); }, [debouncedQ]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
      setQuery("");
      setDebouncedQ("");
      setCursor(-1);
    }
  }, [isOpen]);

  // Backend search
  const { data: results, isFetching } = useQuery<SearchResults>({
    queryKey: ["search", debouncedQ],
    queryFn: () => api.get(`/search?q=${encodeURIComponent(debouncedQ)}&limit=5`).then(r => r.data),
    enabled: debouncedQ.length >= 2,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  // Sofascore browser-direct search (teams + players)
  const { data: ssData } = useQuery<SsResult[]>({
    queryKey: ["ss-search", debouncedQ],
    queryFn: async () => {
      const r = await fetch(`${SS}/search/all?q=${encodeURIComponent(debouncedQ)}`);
      if (!r.ok) return [];
      const d = await r.json();
      const out: SsResult[] = [];
      // Teams
      for (const t of (d.teams ?? []).slice(0, 4)) {
        out.push({ type: "team", id: t.id, name: t.name, sport: t.sport?.name, country: t.country?.name });
      }
      // Players
      for (const p of (d.players ?? []).slice(0, 3)) {
        out.push({ type: "player", id: p.id, name: p.name, sport: p.sport?.name, teamName: p.team?.name });
      }
      return out;
    },
    enabled: debouncedQ.length >= 2,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 0,
  });

  const ssResults: SsResult[] = ssData ?? [];
  const flatItems = flattenResults(results, ssResults);
  const hasResults = flatItems.length > 0;

  // Navigate to result
  const goTo = useCallback((item: FlatItem) => {
    onClose();
    switch (item.kind) {
      case "team": {
        const t = item.data;
        // Prefer Sofascore team profile if name matches any SS result
        const normalise = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
        const ssMatch = ssResults.find(
          s => s.type === "team" && normalise(s.name) === normalise(t.name)
        );
        if (ssMatch) {
          navigate(`/team/ss/${ssMatch.id}`);
        } else if (t.espn_slug) {
          navigate(`/tables?slug=${t.espn_slug}`);
        } else {
          navigate(`/sports`);
        }
        break;
      }
      case "ss": {
        const s = item.data;
        if (s.type === "team") navigate(`/team/ss/${s.id}`);
        else navigate(`/player/ss/${s.id}`);
        break;
      }
      case "comp": {
        const c = item.data;
        const slug = c.espn_slug ?? getCompetitionSlug(c.name);
        if (slug) navigate(`/tables?slug=${slug}`);
        else navigate(`/sports`);
        break;
      }
      case "match": {
        navigate(`/match/${item.data.id}`);
        break;
      }
      case "news": {
        navigate(`/news`);
        break;
      }
    }
  }, [navigate, onClose, ssResults]);

  // Keyboard navigation
  useEffect(() => {
    if (!isOpen) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setCursor(c => Math.min(c + 1, flatItems.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setCursor(c => Math.max(c - 1, -1));
      } else if (e.key === "Enter") {
        const target = cursor >= 0 ? flatItems[cursor] : flatItems[0];
        if (target) goTo(target);
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [isOpen, cursor, flatItems, goTo, onClose]);

  // Scroll active item into view
  useEffect(() => {
    if (cursor < 0) return;
    const el = listRef.current?.querySelector(`[data-idx="${cursor}"]`) as HTMLElement | null;
    el?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[200] flex items-start justify-center pt-[10vh] px-4" onClick={onClose}>
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        aria-hidden="true"
      />

      <div
        className="relative w-full max-w-2xl rounded-2xl shadow-2xl border border-pi-border/40 overflow-hidden"
        style={{ background: "rgba(7,12,25,0.98)" }}
        onClick={e => e.stopPropagation()}
      >
        {/* Input row */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-pi-border/20">
          <Search size={17} className={`shrink-0 ${isFetching ? "text-pi-indigo-light animate-pulse" : "text-pi-muted"}`} />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search teams, players, matches, leagues…"
            className="flex-1 bg-transparent text-[15px] text-pi-primary placeholder:text-pi-muted/50 focus:outline-none"
            autoComplete="off"
            spellCheck={false}
          />
          {query && (
            <button onClick={() => { setQuery(""); inputRef.current?.focus(); }}
              className="text-pi-muted hover:text-pi-primary transition-colors shrink-0">
              <X size={15} />
            </button>
          )}
          <kbd className="hidden md:block text-[10px] text-pi-muted/50 border border-pi-border/30 px-1.5 py-0.5 rounded font-mono shrink-0">ESC</kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="overflow-y-auto max-h-[65vh]">
          {debouncedQ.length < 2 ? (
            /* Empty state — hints */
            <div className="px-4 py-6">
              <p className="text-[11px] font-bold uppercase tracking-wider text-pi-muted/40 mb-3">Suggestions</p>
              <div className="flex flex-wrap gap-2">
                {["Barcelona", "Manchester City", "NBA", "Champions League", "Premier League"].map(s => (
                  <button key={s} onClick={() => setQuery(s)}
                    className="text-[12px] text-pi-secondary bg-white/[0.04] border border-pi-border/20 hover:border-pi-indigo/40 hover:text-pi-primary transition-all px-3 py-1.5 rounded-full">
                    {s}
                  </button>
                ))}
              </div>
              <p className="mt-5 text-[11px] text-pi-muted/30 text-center">
                Press <kbd className="font-mono border border-pi-border/20 px-1 rounded">↑</kbd>{" "}
                <kbd className="font-mono border border-pi-border/20 px-1 rounded">↓</kbd>{" "}
                to navigate · <kbd className="font-mono border border-pi-border/20 px-1 rounded">↵</kbd> to open
              </p>
            </div>
          ) : !hasResults && !isFetching ? (
            <div className="py-12 text-center">
              <p className="text-pi-muted text-sm">No results for <span className="text-pi-primary font-semibold">"{debouncedQ}"</span></p>
              <p className="text-[12px] text-pi-muted/50 mt-1">Try a team name, league, or player</p>
            </div>
          ) : (
            <div className="py-2">
              {/* ── Local teams ── */}
              {(results?.teams ?? []).length > 0 && (
                <Section label="Teams" icon={<Trophy size={11} />}>
                  {results!.teams.map((t) => {
                    const idx = flatItems.findIndex(f => f.kind === "team" && f.data.id === t.id);
                    return (
                      <ResultRow key={`team-${t.id}`} data-idx={idx} active={cursor === idx}
                        onClick={() => goTo({ kind: "team", data: t })}
                        onMouseEnter={() => setCursor(idx)}>
                        <TeamLogo url={t.logo_url} name={t.name} />
                        <div className="flex-1 min-w-0">
                          <p className="text-[13px] font-semibold text-pi-primary truncate">{t.name}</p>
                          <p className="text-[11px] text-pi-muted truncate">
                            {t.sport_icon} {t.sport}{t.country ? ` · ${t.country}` : ""}
                          </p>
                        </div>
                        <span className="text-[11px] text-pi-muted/40 shrink-0 font-mono">ELO {t.elo}</span>
                      </ResultRow>
                    );
                  })}
                </Section>
              )}

              {/* ── Sofascore teams & players ── */}
              {ssResults.length > 0 && (
                <Section label="Global (Teams & Players)" icon={<Zap size={11} />}>
                  {ssResults.map((s) => {
                    const idx = flatItems.findIndex(f => f.kind === "ss" && f.data.id === s.id && f.data.type === s.type);
                    return (
                      <ResultRow key={`ss-${s.type}-${s.id}`} data-idx={idx} active={cursor === idx}
                        onClick={() => goTo({ kind: "ss", data: s })}
                        onMouseEnter={() => setCursor(idx)}>
                        {s.type === "team"
                          ? <SsTeamLogo id={s.id} />
                          : <SsPlayerPhoto id={s.id} />}
                        <div className="flex-1 min-w-0">
                          <p className="text-[13px] font-semibold text-pi-primary truncate">{s.name}</p>
                          <p className="text-[11px] text-pi-muted truncate">
                            {s.type === "team" ? "Team" : "Player"}
                            {s.sport ? ` · ${s.sport}` : ""}
                            {s.teamName ? ` · ${s.teamName}` : ""}
                            {s.country ? ` · ${s.country}` : ""}
                          </p>
                        </div>
                        <span className="text-[10px] text-pi-muted/30 shrink-0 uppercase tracking-wider">
                          {s.type === "team" ? "Team" : "Player"}
                        </span>
                      </ResultRow>
                    );
                  })}
                </Section>
              )}

              {/* ── Competitions ── */}
              {(results?.competitions ?? []).length > 0 && (
                <Section label="Leagues & Tournaments" icon={<Trophy size={11} />}>
                  {results!.competitions.map((c) => {
                    const idx = flatItems.findIndex(f => f.kind === "comp" && f.data.id === c.id);
                    return (
                      <ResultRow key={`comp-${c.id}`} data-idx={idx} active={cursor === idx}
                        onClick={() => goTo({ kind: "comp", data: c })}
                        onMouseEnter={() => setCursor(idx)}>
                        <div className="w-7 h-7 rounded-lg bg-pi-indigo/10 border border-pi-indigo/20 flex items-center justify-center shrink-0">
                          <Trophy size={12} className="text-pi-indigo-light" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-[13px] font-semibold text-pi-primary truncate">{c.name}</p>
                          <p className="text-[11px] text-pi-muted truncate">
                            {c.sport_icon} {c.sport}{c.country ? ` · ${c.country}` : ""}
                          </p>
                        </div>
                      </ResultRow>
                    );
                  })}
                </Section>
              )}

              {/* ── Matches ── */}
              {(results?.matches ?? []).length > 0 && (
                <Section label="Matches" icon={<Calendar size={11} />}>
                  {results!.matches.map((m) => {
                    const idx = flatItems.findIndex(f => f.kind === "match" && f.data.id === m.id);
                    return (
                      <ResultRow key={`match-${m.id}`} data-idx={idx} active={cursor === idx}
                        onClick={() => goTo({ kind: "match", data: m })}
                        onMouseEnter={() => setCursor(idx)}>
                        <div className="flex items-center gap-1.5 min-w-0 flex-1">
                          <TeamLogo url={m.home_logo} name={m.home_team} size="w-5 h-5" />
                          <span className="text-[13px] font-semibold text-pi-primary truncate max-w-[100px]">{m.home_team}</span>
                          <span className="text-[11px] text-pi-muted/50 shrink-0 mx-1">vs</span>
                          <TeamLogo url={m.away_logo} name={m.away_team} size="w-5 h-5" />
                          <span className="text-[13px] font-semibold text-pi-primary truncate max-w-[100px]">{m.away_team}</span>
                        </div>
                        <div className="shrink-0 text-right">
                          {m.status === "finished" ? (
                            <span className="text-[12px] font-bold text-pi-primary">{m.home_score}–{m.away_score}</span>
                          ) : m.status === "live" ? (
                            <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded-full border border-emerald-500/20">LIVE</span>
                          ) : m.match_date ? (
                            <span className="text-[11px] text-pi-muted">{fmtDate(m.match_date)}</span>
                          ) : null}
                        </div>
                      </ResultRow>
                    );
                  })}
                </Section>
              )}

              {/* ── News ── */}
              {(results?.news ?? []).length > 0 && (
                <Section label="News" icon={<Newspaper size={11} />}>
                  {results!.news.map((n) => {
                    const idx = flatItems.findIndex(f => f.kind === "news" && f.data.id === n.id);
                    return (
                      <ResultRow key={`news-${n.id}`} data-idx={idx} active={cursor === idx}
                        onClick={() => goTo({ kind: "news", data: n })}
                        onMouseEnter={() => setCursor(idx)}>
                        {n.image_url ? (
                          <img src={n.image_url} alt="" className="w-10 h-7 object-cover rounded shrink-0" />
                        ) : (
                          <div className="w-10 h-7 rounded bg-white/5 border border-pi-border/20 flex items-center justify-center shrink-0">
                            <Newspaper size={10} className="text-pi-muted/30" />
                          </div>
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="text-[12px] font-semibold text-pi-primary line-clamp-1">{n.title}</p>
                          <p className="text-[11px] text-pi-muted truncate">{n.source_name}</p>
                        </div>
                      </ResultRow>
                    );
                  })}
                </Section>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        {hasResults && (
          <div className="px-4 py-2 border-t border-pi-border/10 flex items-center gap-3 text-[11px] text-pi-muted/40">
            <TrendingUp size={10} />
            <span>{flatItems.length} result{flatItems.length !== 1 ? "s" : ""}</span>
            <span className="ml-auto">↑↓ navigate · ↵ open</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Section({ label, icon, children }: { label: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 px-4 pt-3 pb-1.5">
        <span className="text-pi-muted/40">{icon}</span>
        <p className="text-[10px] font-bold uppercase tracking-widest text-pi-muted/40">{label}</p>
      </div>
      {children}
    </div>
  );
}

function ResultRow({
  children, active, onClick, onMouseEnter, "data-idx": dataIdx,
}: {
  children: React.ReactNode; active: boolean; onClick: () => void;
  onMouseEnter: () => void; "data-idx": number;
}) {
  return (
    <button
      data-idx={dataIdx}
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      className={`w-full flex items-center gap-3 px-4 py-2.5 transition-colors text-left ${
        active ? "bg-pi-indigo/15 border-l-2 border-pi-indigo" : "hover:bg-white/[0.03] border-l-2 border-transparent"
      }`}
    >
      {children}
    </button>
  );
}
