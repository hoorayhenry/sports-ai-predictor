import React, { useState, useEffect, useRef, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Trophy, Calendar, Newspaper, Users, Star, Zap,
  ChevronDown, ChevronRight, ExternalLink, Check,
} from "lucide-react";
import { Link } from "react-router-dom";
import Spinner from "../components/Spinner";
import { api } from "../api/client";

// ── Config types ──────────────────────────────────────────────────────────────

interface EspnLeague  { source: "espn";       slug: string; name: string; flag?: string; logo?: string; }
interface SsLeague    { source: "sofascore";  id: number;   name: string; flag?: string; logo?: string; }
type League = EspnLeague | SsLeague;

interface LeagueGroup { name: string; indices: number[]; }

interface SportConfig {
  key: string; name: string; icon: string; hasDraw: boolean;
  statLabels: { played: string; w: string; d?: string; l: string; for?: string; against?: string; diff?: string; pts: string; extra?: string };
  leagues: League[];
  groups?: LeagueGroup[]; // for football mega-menu layout
}

// ── Sport + League config ─────────────────────────────────────────────────────

const SPORTS: SportConfig[] = [
  {
    key: "football", name: "Football", icon: "⚽", hasDraw: true,
    statLabels: { played: "P", w: "W", d: "D", l: "L", for: "GF", against: "GA", diff: "GD", pts: "Pts" },
    groups: [
      { name: "Top Europe",        indices: [0, 1, 2, 3, 4] },
      { name: "More Europe",       indices: [5, 6, 7, 8, 9] },
      { name: "Americas",          indices: [10, 11, 12, 13, 14] },
      { name: "Cups & Intl",       indices: [15, 16, 17, 18, 19, 20] },
    ],
    leagues: [
      { source: "espn", slug: "eng.1",            name: "Premier League",    flag: "🏴󠁧󠁢󠁥󠁮󠁧󠁿" },
      { source: "espn", slug: "esp.1",            name: "La Liga",           flag: "🇪🇸" },
      { source: "espn", slug: "ger.1",            name: "Bundesliga",        flag: "🇩🇪" },
      { source: "espn", slug: "ita.1",            name: "Serie A",           flag: "🇮🇹" },
      { source: "espn", slug: "fra.1",            name: "Ligue 1",           flag: "🇫🇷" },
      { source: "espn", slug: "por.1",            name: "Primeira Liga",     flag: "🇵🇹" },
      { source: "espn", slug: "ned.1",            name: "Eredivisie",        flag: "🇳🇱" },
      { source: "espn", slug: "tur.1",            name: "Süper Lig",         flag: "🇹🇷" },
      { source: "espn", slug: "sco.1",            name: "Scottish Prem.",    flag: "🏴󠁧󠁢󠁳󠁣󠁴󠁿" },
      { source: "espn", slug: "bel.1",            name: "Pro League",        flag: "🇧🇪" },
      { source: "espn", slug: "usa.1",            name: "MLS",               flag: "🇺🇸" },
      { source: "espn", slug: "bra.1",            name: "Brasileirão",       flag: "🇧🇷" },
      { source: "espn", slug: "arg.1",            name: "Liga Profesional",  flag: "🇦🇷" },
      { source: "espn", slug: "col.1",            name: "Liga BetPlay",      flag: "🇨🇴" },
      { source: "espn", slug: "mex.1",            name: "Liga MX",           flag: "🇲🇽" },
      { source: "espn", slug: "uefa.champions",   name: "Champions League",  logo: "https://a.espncdn.com/i/leaguelogos/soccer/500/2.png" },
      { source: "espn", slug: "uefa.europa",      name: "Europa League",     logo: "https://a.espncdn.com/i/leaguelogos/soccer/500/2310.png" },
      { source: "espn", slug: "uefa.europa.conf", name: "Conference League", logo: "https://a.espncdn.com/i/leaguelogos/soccer/500/20296.png" },
      { source: "sofascore", id: 8,    name: "World Cup 2026",      flag: "🌍" },
      { source: "sofascore", id: 672,  name: "Africa Cup of Nations", flag: "🌍" },
      { source: "sofascore", id: 6797, name: "Copa América",        flag: "🌎" },
    ],
  },
  {
    key: "basketball", name: "Basketball", icon: "🏀", hasDraw: false,
    statLabels: { played: "GP", w: "W", l: "L", pts: "PCT" },
    leagues: [
      { source: "sofascore", id: 132,   name: "NBA",            flag: "🇺🇸" },
      { source: "sofascore", id: 22,    name: "EuroLeague",     flag: "🇪🇺" },
      { source: "sofascore", id: 89,    name: "Liga ACB",       flag: "🇪🇸" },
      { source: "sofascore", id: 22136, name: "WNBA",           flag: "🇺🇸" },
    ],
  },
  {
    key: "american_football", name: "NFL", icon: "🏈", hasDraw: false,
    statLabels: { played: "GP", w: "W", d: "T", l: "L", pts: "PCT" },
    leagues: [
      { source: "sofascore", id: 9464,  name: "NFL",           flag: "🇺🇸" },
      { source: "sofascore", id: 10144, name: "NCAA Football", flag: "🇺🇸" },
    ],
  },
  {
    key: "ice_hockey", name: "Ice Hockey", icon: "🏒", hasDraw: false,
    statLabels: { played: "GP", w: "W", l: "L", pts: "Pts" },
    leagues: [
      { source: "sofascore", id: 1221, name: "NHL",   flag: "🇺🇸" },
      { source: "sofascore", id: 1264, name: "KHL",   flag: "🇷🇺" },
      { source: "sofascore", id: 27,   name: "SHL",   flag: "🇸🇪" },
    ],
  },
  {
    key: "baseball", name: "Baseball", icon: "⚾", hasDraw: false,
    statLabels: { played: "GP", w: "W", l: "L", pts: "PCT" },
    leagues: [
      { source: "sofascore", id: 168,  name: "MLB",       flag: "🇺🇸" },
      { source: "sofascore", id: 1061, name: "NPB Japan", flag: "🇯🇵" },
    ],
  },
  {
    key: "cricket", name: "Cricket", icon: "🏏", hasDraw: true,
    statLabels: { played: "Mat", w: "W", d: "NR", l: "L", pts: "Pts", extra: "NRR" },
    leagues: [
      { source: "sofascore", id: 8048,  name: "IPL",           flag: "🇮🇳" },
      { source: "sofascore", id: 9625,  name: "T20 World Cup", flag: "🌍" },
      { source: "sofascore", id: 5766,  name: "The Ashes",     flag: "🏴󠁧󠁢󠁥󠁮󠁧󠁿" },
      { source: "sofascore", id: 8614,  name: "SA20",          flag: "🇿🇦" },
      { source: "sofascore", id: 12494, name: "BBL",           flag: "🇦🇺" },
    ],
  },
  {
    key: "rugby", name: "Rugby", icon: "🏉", hasDraw: true,
    statLabels: { played: "P", w: "W", d: "D", l: "L", for: "PF", against: "PA", diff: "PD", pts: "Pts" },
    leagues: [
      { source: "sofascore", id: 2578,  name: "Premiership",         flag: "🏴󠁧󠁢󠁥󠁮󠁧󠁿" },
      { source: "sofascore", id: 2975,  name: "Top 14",              flag: "🇫🇷" },
      { source: "sofascore", id: 1082,  name: "Six Nations",         flag: "🇪🇺" },
      { source: "sofascore", id: 2676,  name: "Super Rugby Pacific", flag: "🌏" },
      { source: "sofascore", id: 2668,  name: "Rugby Championship",  flag: "🌏" },
    ],
  },
  {
    key: "tennis", name: "Tennis", icon: "🎾", hasDraw: false,
    statLabels: { played: "Matches", w: "W", l: "L", pts: "Pts" },
    leagues: [
      { source: "sofascore", id: 2480, name: "Roland Garros",   flag: "🇫🇷" },
      { source: "sofascore", id: 2977, name: "Wimbledon",       flag: "🇬🇧" },
      { source: "sofascore", id: 2986, name: "US Open",         flag: "🇺🇸" },
      { source: "sofascore", id: 2974, name: "Australian Open", flag: "🇦🇺" },
    ],
  },
  {
    key: "handball", name: "Handball", icon: "🤾", hasDraw: true,
    statLabels: { played: "P", w: "W", d: "D", l: "L", pts: "Pts" },
    leagues: [
      { source: "sofascore", id: 670,  name: "Champions League",   flag: "🇪🇺" },
      { source: "sofascore", id: 44,   name: "Bundesliga",         flag: "🇩🇪" },
      { source: "sofascore", id: 52,   name: "Starligue",          flag: "🇫🇷" },
      { source: "sofascore", id: 1753, name: "World Championship", flag: "🌍" },
    ],
  },
  {
    key: "volleyball", name: "Volleyball", icon: "🏐", hasDraw: false,
    statLabels: { played: "P", w: "W", l: "L", pts: "Pts" },
    leagues: [
      { source: "sofascore", id: 3088, name: "Nations League (M)", flag: "🌍" },
      { source: "sofascore", id: 3093, name: "Champions League",   flag: "🇪🇺" },
    ],
  },
  {
    key: "mma", name: "MMA", icon: "🥊", hasDraw: false,
    statLabels: { played: "Bouts", w: "W", l: "L", pts: "W%" },
    leagues: [
      { source: "sofascore", id: 117628, name: "UFC",              flag: "🇺🇸" },
      { source: "sofascore", id: 1,      name: "ONE Championship", flag: "🌏" },
    ],
  },
];

// Leagues whose top-player stats come from our backend cache (ESPN), not Sofascore
// Key = Sofascore tournament ID, Value = backend league_key
const SS_TO_BACKEND_KEY: Record<number, string> = {
  132:  "nba",
  9464: "nfl",
};

// ── Shared types ──────────────────────────────────────────────────────────────

interface FixtureTeam { id: string; name: string; short: string; logo: string; score: number | null; }
interface FixtureItem { id: string; date: string; status: "scheduled"|"live"|"finished"; live_minute: number|null; home: FixtureTeam; away: FixtureTeam; venue: string; }
interface UnifiedRow  { rank: number; team_id: string; team_name: string; team_short: string; team_logo: string; points: number; played: number; win: number; draw: number; lose: number; goals_for: number; goals_against: number; goal_diff: number; pct?: number; nrr?: number; form: string[]; description?: string|null; group?: string|null; }
interface SsGroup     { name: string; rows: UnifiedRow[]; }

interface EspnStandingsResp { groups: UnifiedRow[][]; }
interface SsStandingsResp   { groups: SsGroup[]; }
interface EspnFixturesResp  { fixtures: FixtureItem[]; }
interface SsFixturesResp    { fixtures: FixtureItem[]; }
interface NewsArticle       { id: string; headline: string; description: string; published: string; image: string; url: string; }
interface LeaderEntry       { rank: number; value: number; display: string; player_id: string; name: string; headshot: string; team_id: string; team_name: string; team_logo: string; }
interface LeaderCat         { name: string; abbr: string; leaders: LeaderEntry[]; }
interface SsTeam            { id: string; name: string; short: string; logo: string; country?: string; }
interface SsSeason          { id: number; year: string; }

// ── Helpers ───────────────────────────────────────────────────────────────────

const CURRENT_SEASON = 2025;
const SEASONS = Array.from({ length: 11 }, (_, i) => CURRENT_SEASON - i); // 2015/16 → 2025/26
const seasonLabel = (s: number) => `${s}/${String(s + 1).slice(-2)}`;

const fmtTime = (iso: string) =>
  new Date(iso + "Z").toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

const fmtDateLabel = (iso: string) =>
  new Date((iso.length === 10 ? iso + "T00:00:00Z" : iso + "Z"))
    .toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });

const timeAgo = (iso: string) => {
  const h = Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000);
  return h < 1 ? "just now" : h < 24 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`;
};

function groupByDate(items: FixtureItem[]): [string, FixtureItem[]][] {
  const m: Record<string, FixtureItem[]> = {};
  for (const f of items) { const d = f.date.slice(0, 10); (m[d] = m[d] || []).push(f); }
  return Object.entries(m).sort(([a], [b]) => a.localeCompare(b));
}

// ── Micro-components ──────────────────────────────────────────────────────────

function TeamLogo({ id, logo, name, size = "w-6 h-6" }: { id: string; logo: string; name: string; size?: string }) {
  const [err, setErr] = useState(false);
  const src = (!err && logo) ? logo : id ? `https://api.sofascore.com/api/v1/team/${id}/image` : "";
  return src
    ? <img src={src} alt={name} className={`${size} object-contain shrink-0`} onError={() => setErr(true)} />
    : <div className={`${size} rounded-full bg-pi-surface border border-pi-border/30 shrink-0`} />;
}

function PlayerHead({ src: s, name, size = "w-9 h-9" }: { id: string; src: string; name: string; size?: string }) {
  const [err, setErr] = useState(false);
  const url = (!err && s) ? s : "";
  return url
    ? <img src={url} alt={name} className={`${size} rounded-full object-cover object-top shrink-0`} onError={() => setErr(true)} />
    : <div className={`${size} rounded-full bg-pi-surface border border-pi-border/30 shrink-0 flex items-center justify-center`}><Star size={12} className="text-pi-muted" /></div>;
}

function QualBand({ desc }: { desc?: string | null }) {
  if (!desc) return null;
  const d = desc.toLowerCase();
  if (d.includes("champion"))    return <span className="w-0.5 absolute left-0 inset-y-0 bg-sky-500/80 rounded-r" />;
  if (d.includes("europa"))      return <span className="w-0.5 absolute left-0 inset-y-0 bg-amber-500/80 rounded-r" />;
  if (d.includes("conference"))  return <span className="w-0.5 absolute left-0 inset-y-0 bg-lime-500/80 rounded-r" />;
  if (d.includes("relega"))      return <span className="w-0.5 absolute left-0 inset-y-0 bg-rose-500/80 rounded-r" />;
  return null;
}

function StatusBadge({ f }: { f: FixtureItem }) {
  if (f.status === "live") return (
    <div className="flex flex-col items-center gap-0.5 shrink-0 min-w-[52px]">
      <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400 bg-emerald-500/15 border border-emerald-500/30 px-1.5 py-0.5 rounded-full">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse shrink-0" />LIVE
      </span>
      {f.live_minute != null && <span className="text-[10px] text-emerald-400/70 font-mono">{f.live_minute}&apos;</span>}
    </div>
  );
  if (f.status === "finished") return (
    <div className="flex flex-col items-center gap-0.5 shrink-0 min-w-[52px]">
      <span className="text-[10px] font-bold text-pi-muted bg-pi-surface border border-pi-border/30 px-1.5 py-0.5 rounded">FT</span>
      <span className="text-sm font-bold text-pi-primary tabular-nums">{f.home.score ?? "–"} – {f.away.score ?? "–"}</span>
    </div>
  );
  return (
    <div className="flex flex-col items-center gap-0.5 shrink-0 min-w-[52px]">
      <span className="text-sm font-bold text-pi-primary">{fmtTime(f.date)}</span>
      <span className="text-[10px] text-pi-muted/60">KO</span>
    </div>
  );
}

function FixtureRow({ f }: { f: FixtureItem }) {
  const fin = f.status === "finished";
  const hW = fin && f.home.score != null && f.away.score != null && f.home.score > f.away.score;
  const aW = fin && f.home.score != null && f.away.score != null && f.away.score > f.home.score;
  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-pi-border/10 last:border-0 hover:bg-white/[0.02] transition-colors">
      <div className="flex items-center gap-2 flex-1 justify-end min-w-0">
        <span className={`text-[13px] font-semibold truncate ${hW ? "text-pi-primary" : "text-pi-secondary"}`}>{f.home.short || f.home.name}</span>
        <TeamLogo id={f.home.id} logo={f.home.logo} name={f.home.name} />
      </div>
      <StatusBadge f={f} />
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <TeamLogo id={f.away.id} logo={f.away.logo} name={f.away.name} />
        <span className={`text-[13px] font-semibold truncate ${aW ? "text-pi-primary" : "text-pi-secondary"}`}>{f.away.short || f.away.name}</span>
      </div>
    </div>
  );
}

function StandingsTable({ rows, sport }: { rows: UnifiedRow[]; sport: SportConfig }) {
  const sl = sport.statLabels;
  const wlMode = !sport.hasDraw && ["basketball","american_football","baseball","ice_hockey"].includes(sport.key);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-pi-border/20">
            <th className="text-left py-2 px-4 text-pi-muted font-medium w-8">#</th>
            <th className="text-left py-2 px-2 text-pi-muted font-medium">Team</th>
            <th className="text-center py-2 px-2 text-pi-muted font-medium w-9">{sl.played}</th>
            <th className="text-center py-2 px-2 text-pi-muted font-medium w-9">{sl.w}</th>
            {sl.d && <th className="text-center py-2 px-2 text-pi-muted font-medium w-9">{sl.d}</th>}
            <th className="text-center py-2 px-2 text-pi-muted font-medium w-9">{sl.l}</th>
            {sl.for     && <th className="hidden md:table-cell text-center py-2 px-2 text-pi-muted font-medium w-9">{sl.for}</th>}
            {sl.against && <th className="hidden md:table-cell text-center py-2 px-2 text-pi-muted font-medium w-9">{sl.against}</th>}
            {sl.diff    && <th className="hidden md:table-cell text-center py-2 px-2 text-pi-muted font-medium w-9">{sl.diff}</th>}
            {sl.extra   && <th className="hidden md:table-cell text-center py-2 px-2 text-pi-muted font-medium w-14">{sl.extra}</th>}
            <th className="text-center py-2 px-2 text-pi-primary font-semibold w-14">{sl.pts}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr key={row.rank} className="border-b border-pi-border/8 hover:bg-white/[0.02] transition-colors relative">
              <QualBand desc={row.description} />
              <td className="py-2.5 pl-4 pr-2 text-pi-muted text-center font-mono text-xs">{row.rank}</td>
              <td className="py-2.5 px-2">
                <div className="flex items-center gap-2 min-w-0">
                  <TeamLogo id={row.team_id} logo={row.team_logo} name={row.team_name} />
                  <span className="font-medium text-pi-primary truncate">{row.team_name}</span>
                </div>
              </td>
              <td className="py-2.5 px-2 text-center text-pi-secondary">{row.played}</td>
              <td className="py-2.5 px-2 text-center text-pi-secondary">{row.win}</td>
              {sl.d && <td className="py-2.5 px-2 text-center text-pi-secondary">{row.draw}</td>}
              <td className="py-2.5 px-2 text-center text-pi-secondary">{row.lose}</td>
              {sl.for     && <td className="hidden md:table-cell py-2.5 px-2 text-center text-pi-muted">{row.goals_for}</td>}
              {sl.against && <td className="hidden md:table-cell py-2.5 px-2 text-center text-pi-muted">{row.goals_against}</td>}
              {sl.diff    && (
                <td className={`hidden md:table-cell py-2.5 px-2 text-center font-mono text-xs ${Number(row.goal_diff) > 0 ? "text-emerald-400" : Number(row.goal_diff) < 0 ? "text-rose-400" : "text-pi-muted"}`}>
                  {Number(row.goal_diff) > 0 ? `+${row.goal_diff}` : row.goal_diff}
                </td>
              )}
              {sl.extra === "PCT" && <td className="hidden md:table-cell py-2.5 px-2 text-center text-pi-muted text-xs font-mono">{row.pct !== undefined ? row.pct.toFixed(3) : "—"}</td>}
              {sl.extra === "NRR" && <td className="hidden md:table-cell py-2.5 px-2 text-center text-pi-muted text-xs font-mono">{row.nrr !== undefined ? (row.nrr > 0 ? `+${row.nrr.toFixed(3)}` : row.nrr.toFixed(3)) : "—"}</td>}
              <td className="py-2.5 px-2 text-center font-bold text-pi-primary">
                {wlMode ? (row.pct !== undefined ? row.pct.toFixed(3) : row.win) : row.points}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Mega-menu Dropdown ────────────────────────────────────────────────────────

interface DropdownProps {
  sport: SportConfig;
  anchorRect: DOMRect;
  selectedIdx: number;
  onSelect: (idx: number) => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

function SportDropdown({ sport, anchorRect, selectedIdx, onSelect, onMouseEnter, onMouseLeave }: DropdownProps) {
  const isMega = !!sport.groups;
  const top  = anchorRect.bottom + 8;
  // For mega-menu: left-align to anchor, but don't go off screen right
  const rawLeft = anchorRect.left;
  const menuW   = isMega ? 560 : 220;
  const left    = Math.min(rawLeft, window.innerWidth - menuW - 16);

  return (
    <div
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onMouseDown={e => e.stopPropagation()}
      className="fixed z-[999] rounded-2xl shadow-2xl border border-pi-border/40 backdrop-blur-xl"
      style={{
        top, left, width: menuW,
        background: "rgba(10,14,35,0.97)",
      }}
    >
      {isMega ? (
        /* ── Football mega-menu: 2×2 column grid ── */
        <div className="p-4 grid grid-cols-2 gap-x-6 gap-y-4">
          {sport.groups!.map(group => (
            <div key={group.name}>
              <p className="text-[10px] font-bold uppercase tracking-widest text-pi-muted/50 mb-2 px-1">{group.name}</p>
              <div className="space-y-0.5">
                {group.indices.map(idx => {
                  const lg = sport.leagues[idx];
                  if (!lg) return null;
                  const isSelected = selectedIdx === idx;
                  return (
                    <button
                      key={idx}
                      onClick={() => onSelect(idx)}
                      className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-left transition-all group ${
                        isSelected
                          ? "bg-pi-indigo/20 text-pi-primary"
                          : "text-pi-secondary hover:bg-white/[0.05] hover:text-pi-primary"
                      }`}
                    >
                      {(lg as EspnLeague).logo ? (
                        <img src={(lg as EspnLeague).logo} alt={lg.name} className="w-5 h-5 object-contain shrink-0 brightness-110" />
                      ) : (
                        <span className="text-base shrink-0 leading-none">{lg.flag}</span>
                      )}
                      <span className="text-[13px] font-medium truncate">{lg.name}</span>
                      {isSelected && <Check size={12} className="ml-auto shrink-0 text-pi-indigo-light" />}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* ── Other sports: simple list ── */
        <div className="p-2">
          <p className="text-[10px] font-bold uppercase tracking-widest text-pi-muted/50 mb-2 px-3 pt-2">{sport.name}</p>
          {sport.leagues.map((lg, idx) => {
            const isSelected = selectedIdx === idx;
            return (
              <button
                key={idx}
                onClick={() => onSelect(idx)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left transition-all ${
                  isSelected
                    ? "bg-pi-indigo/20 text-pi-primary"
                    : "text-pi-secondary hover:bg-white/[0.05] hover:text-pi-primary"
                }`}
              >
                <span className="text-base shrink-0 leading-none">{lg.flag}</span>
                <span className="text-[13px] font-medium">{lg.name}</span>
                {isSelected && <Check size={12} className="ml-auto shrink-0 text-pi-indigo-light" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Hero background per sport ─────────────────────────────────────────────────

const SPORT_HEROES: Record<string, string> = {
  football:          "https://images.unsplash.com/photo-1551958219-acbc608c6377?w=1400&q=80&auto=format&fit=crop",
  basketball:        "https://images.unsplash.com/photo-1546519638-68e109498ffc?w=1400&q=80&auto=format&fit=crop",
  american_football: "https://images.unsplash.com/photo-1612872087720-bb876e2e67d1?w=1400&q=80&auto=format&fit=crop",
  ice_hockey:        "https://images.unsplash.com/photo-1515703407324-5f753afd8be8?w=1400&q=80&auto=format&fit=crop",
  baseball:          "https://images.unsplash.com/photo-1508344928928-7165b67de128?w=1400&q=80&auto=format&fit=crop",
  cricket:           "https://images.unsplash.com/photo-1540747913346-19e32dc3e97e?w=1400&q=80&auto=format&fit=crop",
  rugby:             "https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=1400&q=80&auto=format&fit=crop",
  tennis:            "https://images.unsplash.com/photo-1554068865-24cecd4e34b8?w=1400&q=80&auto=format&fit=crop",
  handball:          "https://images.unsplash.com/photo-1580748141549-71748dbe0bdc?w=1400&q=80&auto=format&fit=crop",
  volleyball:        "https://images.unsplash.com/photo-1612872087720-bb876e2e67d1?w=1400&q=80&auto=format&fit=crop",
  mma:               "https://images.unsplash.com/photo-1549719386-74dfcbf7dbed?w=1400&q=80&auto=format&fit=crop",
};

// ── Main page ─────────────────────────────────────────────────────────────────

type PageTab = "standings" | "matches" | "news" | "teams" | "players";

export default function SportsPage() {
  const [sportKey,  setSportKey]  = useState("football");
  const [leagueIdx, setLeagueIdx] = useState(0);
  const [season,    setSeason]    = useState(CURRENT_SEASON);
  const [pageTab,   setPageTab]   = useState<PageTab>("standings");
  const [ssSeasonId, setSsSeasonId] = useState<number | null>(null);

  // Dropdown state
  const [openSport,   setOpenSport]   = useState<string | null>(null);
  const [anchorRect,  setAnchorRect]  = useState<DOMRect | null>(null);
  const closeTimer   = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const navRef        = useRef<HTMLDivElement>(null);

  const scheduleClose = useCallback(() => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setOpenSport(null), 180);
  }, []);

  const cancelClose = useCallback(() => clearTimeout(closeTimer.current), []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (navRef.current && !navRef.current.contains(e.target as Node)) {
        setOpenSport(null);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Close dropdown on Escape
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpenSport(null);
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, []);

  // Clean up close timer on unmount
  useEffect(() => () => clearTimeout(closeTimer.current), []);

  const sport  = SPORTS.find(s => s.key === sportKey)!;
  const league = sport.leagues[leagueIdx] ?? sport.leagues[0];

  // Reset when sport/league changes
  useEffect(() => {
    setPageTab("standings");
    setSsSeasonId(null);
    setLeagueIdx(0);
  }, [sportKey]);

  useEffect(() => {
    setPageTab("standings");
    setSsSeasonId(null);
  }, [leagueIdx]);

  const isEspn = league.source === "espn";
  const tournamentId = !isEspn ? (league as SsLeague).id : 0;
  // For NBA/NFL: fetch from our backend cache instead of Sofascore (which returns 404)
  const backendLeagueKey: string | null = !isEspn ? (SS_TO_BACKEND_KEY[tournamentId] ?? null) : null;

  function handleSportEnter(key: string, e: React.MouseEvent<HTMLButtonElement>) {
    cancelClose();
    setOpenSport(key);
    setAnchorRect(e.currentTarget.getBoundingClientRect());
  }
  function handleSportClick(key: string, e: React.MouseEvent<HTMLButtonElement>) {
    if (openSport === key) { setOpenSport(null); return; }
    setOpenSport(key);
    setAnchorRect(e.currentTarget.getBoundingClientRect());
  }
  function selectLeague(sKey: string, idx: number) {
    setSportKey(sKey);
    setLeagueIdx(idx);
    setOpenSport(null);
  }

  // ── Sofascore direct (browser calls bypass the server-side 403) ───────────
  const SS = "https://api.sofascore.com/api/v1";

  // 1. Seasons list (needed to resolve the current season ID)
  const { data: seasonsData } = useQuery<{ seasons: SsSeason[] }>({
    queryKey:  ["ss-seasons", tournamentId],
    queryFn:   async () => {
      const r = await fetch(`${SS}/unique-tournament/${tournamentId}/seasons`);
      if (!r.ok) throw new Error(`Sofascore ${r.status}`);
      const d = await r.json();
      return { seasons: (d.seasons ?? []).map((s: any) => ({ id: s.id, year: s.year ?? String(s.id) })) };
    },
    enabled:      !isEspn && tournamentId > 0,
    staleTime:    7 * 24 * 60 * 60 * 1000, // 7 days — season lists almost never change
    gcTime:       7 * 24 * 60 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect:   false,
    retry: 1,
  });
  useEffect(() => {
    if (seasonsData?.seasons?.length) setSsSeasonId(seasonsData.seasons[0].id);
  }, [seasonsData]);

  const ssSeasons   = (seasonsData?.seasons ?? []).filter(s => {
    const yr = parseInt(String(s.year).slice(0, 4));
    return !isNaN(yr) && yr >= CURRENT_SEASON - 10;
  });
  const isHistorical = isEspn ? season !== CURRENT_SEASON : false;
  const espnSlug    = isEspn ? (league as EspnLeague).slug : "";
  // Gate: wait for season resolution before firing data queries
  const ssReady = !isEspn && (ssSeasonId !== null || seasonsData !== undefined);

  // ── ESPN queries ───────────────────────────────────────────────────────────

  const _noRefetch = { refetchOnWindowFocus: false, refetchOnReconnect: false } as const;

  const { data: espnStandings, isLoading: espnStLoad } = useQuery<EspnStandingsResp>({
    queryKey:  ["standings", espnSlug, season],
    queryFn:   () => api.get(`/standings?slug=${espnSlug}&season=${season}`).then(r => r.data),
    enabled:   isEspn && (pageTab === "standings" || pageTab === "teams"),
    staleTime: isHistorical ? 30 * 24 * 60 * 60 * 1000 : 10 * 60 * 1000, // 10 min live, 30 days historical
    ..._noRefetch,
  });
  const { data: espnFixtures, isLoading: espnFxLoad } = useQuery<EspnFixturesResp>({
    queryKey:  ["league-fixtures", espnSlug, season],
    queryFn:   () => api.get(`/standings/fixtures?slug=${espnSlug}&season=${season}`).then(r => r.data),
    enabled:   isEspn && pageTab === "matches",
    staleTime: 24 * 60 * 60 * 1000, // 24 hours — fixtures don't change day-to-day
    gcTime:    24 * 60 * 60 * 1000,
    ..._noRefetch,
  });
  const { data: espnNews, isLoading: espnNwLoad } = useQuery<{ articles: NewsArticle[] }>({
    queryKey:  ["league-news", espnSlug],
    queryFn:   () => api.get(`/standings/news?slug=${espnSlug}`).then(r => r.data),
    enabled:   isEspn && pageTab === "news",
    staleTime: 60 * 60 * 1000, // 1 hour
    ..._noRefetch,
  });
  const { data: espnLeaders, isLoading: espnLdLoad } = useQuery<{ categories: LeaderCat[] }>({
    queryKey:  ["league-leaders", espnSlug, season],
    queryFn:   () => api.get(`/standings/leaders?slug=${espnSlug}&season=${season}`).then(r => r.data),
    enabled:   isEspn && pageTab === "players",
    staleTime: 24 * 60 * 60 * 1000, // 24 hours
    ..._noRefetch,
  });

  // ── Sofascore direct queries (browser → api.sofascore.com) ────────────────

  // Helper: normalise a standings response from Sofascore into UnifiedRow[]
  function _normSsStandings(data: any, sportKey: string): SsStandingsResp {
    const rawGroups = data?.standings ?? [];
    const groups: { name: string; rows: UnifiedRow[] }[] = [];
    for (const g of rawGroups) {
      const name = g.name || g.type || "Standings";
      const rows: UnifiedRow[] = (g.rows ?? []).map((row: any) => {
        const team = row.team ?? {};
        const tid  = String(team.id ?? "");
        const base: Partial<UnifiedRow> = {
          rank:        row.position ?? 0,
          team_id:     tid,
          team_name:   team.name ?? "",
          team_short:  team.shortName ?? team.nameCode ?? (team.name ?? "").slice(0, 3).toUpperCase(),
          team_logo:   tid ? `${SS}/team/${tid}/image` : "",
          description: row.description ?? null,
          group:       rawGroups.length > 1 ? name : null,
          form:        [],
        };
        if (sportKey === "football") {
          return { ...base, points: row.points ?? 0, played: row.matches ?? 0, win: row.wins ?? 0, draw: row.draws ?? 0, lose: row.losses ?? 0, goals_for: row.scoresFor ?? 0, goals_against: row.scoresAgainst ?? 0, goal_diff: row.scoreDiffFormatted ?? 0 } as UnifiedRow;
        } else if (["basketball","american_football","ice_hockey","baseball"].includes(sportKey)) {
          const w = row.wins ?? 0, l = row.losses ?? 0, p = w + l;
          return { ...base, points: w, played: p, win: w, draw: 0, lose: l, goals_for: 0, goals_against: 0, goal_diff: w - l, pct: p > 0 ? Math.round(w / p * 1000) / 1000 : 0 } as UnifiedRow;
        } else {
          return { ...base, points: row.points ?? 0, played: row.matches ?? 0, win: row.wins ?? 0, draw: row.draws ?? 0, lose: row.losses ?? 0, goals_for: row.scoresFor ?? 0, goals_against: row.scoresAgainst ?? 0, goal_diff: row.scoreDiffFormatted ?? 0 } as UnifiedRow;
        }
      });
      if (rows.length) groups.push({ name, rows });
    }
    return { groups };
  }

  // Helper: normalise a Sofascore event into FixtureItem
  function _normSsEvent(ev: any): FixtureItem | null {
    try {
      const h = ev.homeTeam ?? {}, a = ev.awayTeam ?? {};
      const sc = { type: ev.status?.type ?? "notstarted" };
      const status: "live"|"finished"|"scheduled" =
        sc.type === "inprogress" ? "live" : sc.type === "finished" ? "finished" : "scheduled";
      const ts = ev.startTimestamp;
      const hid = String(h.id ?? ""), aid = String(a.id ?? "");
      return {
        id: String(ev.id ?? ""),
        date: ts ? new Date(ts * 1000).toISOString().replace("Z","") : "",
        status, live_minute: status === "live" ? ev.time?.played ?? null : null,
        home: { id: hid, name: h.name ?? "", short: h.shortName ?? h.nameCode ?? "", logo: hid ? `${SS}/team/${hid}/image` : "", score: status !== "scheduled" ? ev.homeScore?.current ?? null : null },
        away: { id: aid, name: a.name ?? "", short: a.shortName ?? a.nameCode ?? "", logo: aid ? `${SS}/team/${aid}/image` : "", score: status !== "scheduled" ? ev.awayScore?.current ?? null : null },
        venue: ev.venue?.name ?? "",
      };
    } catch { return null; }
  }

  const { data: ssStandings, isLoading: ssStLoad } = useQuery<SsStandingsResp>({
    queryKey:  ["ss-standings", tournamentId, ssSeasonId, sport.key],
    queryFn:   async () => {
      const r = await fetch(`${SS}/unique-tournament/${tournamentId}/season/${ssSeasonId}/standings/total`);
      if (!r.ok) throw new Error(`Sofascore ${r.status}`);
      return _normSsStandings(await r.json(), sport.key);
    },
    enabled:   ssReady && !!ssSeasonId && tournamentId > 0 && (pageTab === "standings" || pageTab === "teams"),
    staleTime: 10 * 60 * 1000,
    retry: 1,
    ..._noRefetch,
  });

  const { data: ssFixtures, isLoading: ssFxLoad } = useQuery<SsFixturesResp>({
    queryKey:  ["ss-fixtures", tournamentId, ssSeasonId],
    queryFn:   async () => {
      const evs: FixtureItem[] = [];
      for (const dir of ["last", "next"] as const) {
        for (let pg = 0; pg < 3; pg++) {
          try {
            const r = await fetch(`${SS}/unique-tournament/${tournamentId}/season/${ssSeasonId}/events/${dir}/${pg}`);
            if (!r.ok) break;
            const d = await r.json();
            for (const ev of d.events ?? []) { const n = _normSsEvent(ev); if (n) evs.push(n); }
          } catch { break; }
        }
      }
      const seen = new Set<string>();
      const unique = evs.sort((a,b) => a.date.localeCompare(b.date)).filter(e => { if (seen.has(e.id)) return false; seen.add(e.id); return true; });
      return { fixtures: unique };
    },
    enabled:   ssReady && !!ssSeasonId && tournamentId > 0 && pageTab === "matches",
    staleTime: 24 * 60 * 60 * 1000,
    retry: 1,
    ..._noRefetch,
  });

  const { data: ssLeaders, isLoading: ssLdLoad } = useQuery<{ categories: LeaderCat[] }>({
    queryKey:  ["ss-leaders", tournamentId, ssSeasonId, sport.key],
    queryFn:   async () => {
      const r = await fetch(`${SS}/unique-tournament/${tournamentId}/season/${ssSeasonId}/top-players/overall`);
      if (!r.ok) throw new Error(`Sofascore ${r.status}`);
      const d = await r.json();
      const cats: LeaderCat[] = (d.topPlayers ?? []).map((cat: any) => ({
        name: cat.statisticsType ?? "Stats", abbr: cat.statisticsType ?? "",
        leaders: (cat.topPlayersResults ?? []).map((p: any, i: number) => ({
          rank: i + 1, value: p.statistics?.[cat.statisticsType ?? ""] ?? 0,
          display: String(p.statistics?.[cat.statisticsType ?? ""] ?? ""),
          player_id: String(p.player?.id ?? ""), name: p.player?.name ?? "",
          headshot: p.player?.id ? `${SS}/player/${p.player.id}/image` : "",
          team_id: String(p.team?.id ?? ""), team_name: p.team?.name ?? "",
          team_logo: p.team?.id ? `${SS}/team/${p.team.id}/image` : "",
        })),
      })).filter((c: LeaderCat) => c.leaders.length > 0);
      return { categories: cats };
    },
    enabled:   ssReady && !!ssSeasonId && tournamentId > 0 && pageTab === "players",
    staleTime: 24 * 60 * 60 * 1000,
    retry: 1,
    ..._noRefetch,
  });

  // Backend-cached top players (NBA, NFL) — fetched from our server, not Sofascore
  const { data: backendLeaders, isLoading: backendLdLoad } = useQuery<{ categories: LeaderCat[] }>({
    queryKey:  ["backend-leaders", backendLeagueKey],
    queryFn:   () => api.get(`/players/top-stats?league_key=${backendLeagueKey}`).then(r => r.data),
    enabled:   !!backendLeagueKey && pageTab === "players",
    staleTime: 24 * 60 * 60 * 1000,
    ..._noRefetch,
  });

  const { data: ssTeams, isLoading: ssTmLoad } = useQuery<{ teams: SsTeam[] }>({
    queryKey:  ["ss-teams", tournamentId, ssSeasonId],
    queryFn:   async () => {
      const r = await fetch(`${SS}/unique-tournament/${tournamentId}/season/${ssSeasonId}/teams`);
      if (!r.ok) throw new Error(`Sofascore ${r.status}`);
      const d = await r.json();
      return { teams: (d.teams ?? []).map((t: any) => ({ id: String(t.id ?? ""), name: t.name ?? "", short: t.shortName ?? t.nameCode ?? "", logo: t.id ? `${SS}/team/${t.id}/image` : "", country: t.country?.name })) };
    },
    enabled:   ssReady && !!ssSeasonId && tournamentId > 0 && pageTab === "teams",
    staleTime: 86_400_000,
    retry: 1,
    ..._noRefetch,
  });

  // ── Unified data ───────────────────────────────────────────────────────────

  const standingsGroups: { name: string; rows: UnifiedRow[] }[] = isEspn
    ? (espnStandings?.groups ?? []).map((g, i) => ({ name: `Group ${i + 1}`, rows: g }))
    : (ssStandings?.groups ?? []);

  const fixtures: FixtureItem[] = isEspn
    ? (espnFixtures?.fixtures ?? [])
    : (ssFixtures?.fixtures ?? []);

  const leaderCategories: LeaderCat[] = isEspn
    ? (espnLeaders?.categories ?? [])
    : backendLeagueKey
      ? (backendLeaders?.categories ?? [])
      : (ssLeaders?.categories ?? []);

  const standingsLoading = isEspn ? espnStLoad : ssStLoad;
  const fixturesLoading  = isEspn ? espnFxLoad : ssFxLoad;
  const newsLoading      = espnNwLoad;
  const leadersLoading   = isEspn ? espnLdLoad : backendLeagueKey ? backendLdLoad : ssLdLoad;

  const leagueName = league.name;
  const leagueFlag = (league as EspnLeague).logo ? undefined : league.flag;
  const leagueLogo = (league as EspnLeague).logo;

  // Sports with accessible top-player stats:
  // football: ESPN (all major leagues) + Sofascore (WC, AFCON, Copa América)
  // basketball: Sofascore (EuroLeague) — NBA via balldontlie pending
  // ice_hockey: Sofascore (NHL, SHL)
  // baseball: Sofascore (MLB)
  // american_football: ESPN (NFL)
  // mma: Sofascore (ONE Championship)
  // Hidden for: rugby, cricket, tennis, handball, volleyball (no accessible API)
  const hasPlayerStats = isEspn
    || ["football", "basketball", "ice_hockey", "baseball", "american_football", "mma"].includes(sport.key);

  const PAGE_TABS: { key: PageTab; label: string; icon: React.ReactNode }[] = [
    { key: "standings", label: "Table",       icon: <Trophy size={12} /> },
    { key: "matches",   label: "Matches",     icon: <Calendar size={12} /> },
    { key: "news",      label: "News",        icon: <Newspaper size={12} /> },
    { key: "teams",     label: "Teams",       icon: <Users size={12} /> },
    ...(hasPlayerStats ? [{ key: "players" as PageTab, label: "Top Players", icon: <Star size={12} /> }] : []),
  ];

  return (
    <div className="min-h-screen pb-24 md:pb-8">

      {/* ── Sport nav bar with hover dropdowns ────────────────────────────── */}
      <div ref={navRef} className="pt-4 md:pt-6 pb-3">
        <div className="flex items-center gap-1 overflow-x-auto scrollbar-hide pb-1 pl-4" style={{ WebkitOverflowScrolling: "touch" }}>
          {SPORTS.map(s => {
            const isActive = sportKey === s.key;
            const isOpen   = openSport === s.key;
            return (
              <button
                key={s.key}
                onMouseEnter={e => handleSportEnter(s.key, e)}
                onMouseLeave={scheduleClose}
                onClick={e => handleSportClick(s.key, e)}
                className={`
                  relative flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-[13px] font-semibold
                  transition-all duration-150 select-none whitespace-nowrap shrink-0
                  ${isActive
                    ? "bg-gradient-to-br from-pi-indigo/30 to-pi-violet/20 text-pi-primary border border-pi-indigo/40 shadow-[0_0_12px_rgba(99,102,241,0.15)]"
                    : "text-pi-secondary hover:text-pi-primary hover:bg-white/[0.05] border border-transparent"
                  }
                `}
              >
                <span className="text-base leading-none">{s.icon}</span>
                <span>{s.name}</span>
                <ChevronDown
                  size={11}
                  className={`transition-transform duration-200 ${isOpen ? "rotate-180 text-pi-indigo-light" : "text-pi-muted/60"}`}
                />
                {/* Active indicator dot */}
                {isActive && (
                  <span className="absolute -bottom-0.5 left-1/2 -translate-x-1/2 w-3 h-0.5 rounded-full bg-gradient-to-r from-pi-indigo to-pi-violet" />
                )}
              </button>
            );
          })}
          {/* Spacer — right padding equivalent inside scroll container */}
          <div className="w-4 shrink-0 select-none" aria-hidden="true" />
        </div>
      </div>

      {/* ── Dropdown portal ────────────────────────────────────────────────── */}
      {openSport && anchorRect && (() => {
        const dropSport = SPORTS.find(s => s.key === openSport)!;
        return (
          <SportDropdown
            sport={dropSport}
            anchorRect={anchorRect}
            selectedIdx={sportKey === openSport ? leagueIdx : -1}
            onSelect={idx => selectLeague(openSport, idx)}
            onMouseEnter={cancelClose}
            onMouseLeave={scheduleClose}
          />
        );
      })()}

      {/* ── Hero ───────────────────────────────────────────────────────────── */}
      <div className="relative overflow-hidden rounded-2xl mx-4 mb-0" style={{ minHeight: 130 }}>
        <img
          src={SPORT_HEROES[sportKey] ?? SPORT_HEROES.football}
          alt=""
          className="absolute inset-0 w-full h-full object-cover object-center brightness-75 saturate-125 pointer-events-none select-none"
          aria-hidden
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/5 via-black/20 to-[#070c19]/90" />
        <div className="absolute inset-0 bg-gradient-to-r from-[#070c19]/70 via-transparent to-transparent" />

        <div className="relative px-5 pt-6 pb-5 flex items-end justify-between">
          <div>
            {/* Breadcrumb */}
            <div className="flex items-center gap-1.5 mb-2 text-[11px] text-pi-muted/70 font-medium">
              <span>{sport.icon}</span>
              <span>{sport.name}</span>
              <ChevronRight size={10} />
              {leagueFlag ? <span>{leagueFlag}</span> : null}
              {leagueLogo ? <img src={leagueLogo} alt="" className="w-4 h-4 object-contain" /> : null}
              <span className="text-pi-muted">{leagueName}</span>
            </div>
            <h1 className="text-2xl md:text-3xl font-extrabold text-white font-display leading-none drop-shadow-lg">
              {leagueName}
            </h1>
            <span className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-semibold text-emerald-400/90 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-0.5 rounded-full">
              <Zap size={9} /> Live · Updates every 30 seconds
            </span>
          </div>

          {/* Season selector */}
          <div className="shrink-0">
            {isEspn ? (
              <select
                value={season}
                onChange={e => setSeason(Number(e.target.value))}
                className="bg-pi-surface/80 backdrop-blur-sm border border-pi-border/60 text-pi-primary text-xs font-semibold rounded-lg px-3 py-2 cursor-pointer focus:outline-none"
              >
                {SEASONS.map(s => <option key={s} value={s}>{seasonLabel(s)}</option>)}
              </select>
            ) : ssSeasons.length > 1 ? (
              <select
                value={ssSeasonId ?? ""}
                onChange={e => setSsSeasonId(Number(e.target.value))}
                className="bg-pi-surface/80 backdrop-blur-sm border border-pi-border/60 text-pi-primary text-xs font-semibold rounded-lg px-3 py-2 cursor-pointer focus:outline-none"
              >
                {ssSeasons.map(s => <option key={s.id} value={s.id}>{s.year}</option>)}
              </select>
            ) : null}
          </div>
        </div>
      </div>

      {/* ── Detail tabs ─────────────────────────────────────────────────────── */}
      <div className="px-4 mt-4">
        <div className="flex gap-1 border-b border-pi-border/20 mb-4">
          {PAGE_TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setPageTab(t.key)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all -mb-px ${
                pageTab === t.key
                  ? "border-pi-indigo text-pi-primary"
                  : "border-transparent text-pi-muted hover:text-pi-secondary"
              }`}
            >
              {t.icon}{t.label}
            </button>
          ))}
        </div>

        {/* ── Table ─────────────────────────────────────────────────────────── */}
        {pageTab === "standings" && (
          <div className="card">
            {standingsLoading && <div className="py-16 flex justify-center"><Spinner /></div>}
            {!standingsLoading && standingsGroups.length === 0 && (
              <p className="py-12 text-center text-pi-muted text-sm">No standings available.</p>
            )}
            {!standingsLoading && standingsGroups.map((g, gi) => (
              <div key={gi} className={gi > 0 ? "mt-6 border-t border-pi-border/20 pt-4" : ""}>
                {standingsGroups.length > 1 && (
                  <p className="text-[10px] font-bold uppercase tracking-widest text-pi-muted/50 px-4 py-2">{g.name}</p>
                )}
                <StandingsTable rows={g.rows} sport={sport} />
              </div>
            ))}
          </div>
        )}

        {/* ── Matches ───────────────────────────────────────────────────────── */}
        {pageTab === "matches" && (
          <div className="card">
            {fixturesLoading && <div className="py-16 flex justify-center"><Spinner /></div>}
            {!fixturesLoading && fixtures.length === 0 && (
              <p className="py-12 text-center text-pi-muted text-sm">No fixtures found.</p>
            )}
            {!fixturesLoading && groupByDate(fixtures).map(([day, dayF]) => (
              <div key={day} className="border-b border-pi-border/10 last:border-0">
                <div className="px-4 py-2 bg-pi-surface/50">
                  <span className="text-[11px] font-semibold text-pi-muted uppercase tracking-wider">{fmtDateLabel(day)}</span>
                </div>
                {dayF.map(f => <FixtureRow key={f.id} f={f} />)}
              </div>
            ))}
          </div>
        )}

        {/* ── News ──────────────────────────────────────────────────────────── */}
        {pageTab === "news" && (
          <div>
            {!isEspn && (
              <div className="card py-12 text-center">
                <Newspaper size={32} className="text-pi-muted/30 mx-auto mb-3" />
                <p className="text-pi-muted text-sm">News is available for football leagues.</p>
                <Link to="/news" className="mt-2 inline-block text-[13px] text-pi-indigo-light hover:underline">Browse all news →</Link>
              </div>
            )}
            {isEspn && newsLoading && <div className="py-16 flex justify-center"><Spinner /></div>}
            {isEspn && !newsLoading && (espnNews?.articles ?? []).length === 0 && (
              <p className="py-12 text-center text-pi-muted text-sm">No articles found.</p>
            )}
            {isEspn && !newsLoading && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {(espnNews?.articles ?? []).map(a => (
                  <a key={a.id} href={a.url} target="_blank" rel="noopener noreferrer" className="card group hover:border-pi-indigo/30 transition-all">
                    {a.image && (
                      <div className="relative h-40 overflow-hidden rounded-xl -mx-4 -mt-4 mb-3">
                        <img src={a.image} alt={a.headline} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" />
                        <div className="absolute inset-0 bg-gradient-to-t from-[#070c19]/80 to-transparent" />
                      </div>
                    )}
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="font-semibold text-[13px] text-pi-primary leading-snug group-hover:text-pi-indigo-light transition-colors">{a.headline}</h3>
                      <ExternalLink size={12} className="shrink-0 text-pi-muted mt-0.5" />
                    </div>
                    {a.description && <p className="text-[12px] text-pi-muted mt-1 line-clamp-2">{a.description}</p>}
                    <p className="text-[11px] text-pi-muted/60 mt-2">{timeAgo(a.published)}</p>
                  </a>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Teams ─────────────────────────────────────────────────────────── */}
        {pageTab === "teams" && (
          <div>
            {/* ESPN: derive team list from standings rows */}
            {isEspn && espnStLoad && <div className="py-16 flex justify-center"><Spinner /></div>}
            {isEspn && !espnStLoad && (() => {
              const allRows = espnStandings?.groups?.flatMap(g => g) ?? [];
              return allRows.length === 0
                ? <p className="py-12 text-center text-pi-muted text-sm">No teams found.</p>
                : (
                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                    {allRows.map(row => (
                      <Link key={row.team_id} to={`/team/${espnSlug}/${row.team_id}`}
                        className="card hover:border-pi-indigo/30 transition-all flex items-center gap-3">
                        <TeamLogo id={row.team_id} logo={row.team_logo} name={row.team_name} size="w-10 h-10" />
                        <div className="min-w-0 flex-1">
                          <p className="text-[13px] font-semibold text-pi-primary truncate">{row.team_name}</p>
                          <p className="text-[11px] text-pi-muted">{row.played} GP · {row.points} pts</p>
                        </div>
                        <ChevronRight size={13} className="text-pi-muted shrink-0" />
                      </Link>
                    ))}
                  </div>
                );
            })()}

            {/* Sofascore: dedicated teams endpoint, fallback to standings rows */}
            {!isEspn && (ssTmLoad || ssStLoad) && <div className="py-16 flex justify-center"><Spinner /></div>}
            {!isEspn && !ssTmLoad && !ssStLoad && (() => {
              // Prefer the teams endpoint; fall back to extracting from standings
              const fromTeamsApi = ssTeams?.teams ?? [];
              const fromStandings = (ssStandings?.groups ?? []).flatMap(g => g.rows).map(r => ({
                id: r.team_id, name: r.team_name, short: r.team_short, logo: r.team_logo, country: undefined,
              }));
              const teams: SsTeam[] = fromTeamsApi.length > 0 ? fromTeamsApi : fromStandings;
              return teams.length === 0
                ? <p className="py-12 text-center text-pi-muted text-sm">No team data available.</p>
                : (
                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                    {teams.map(t => (
                      <div key={t.id} className="card flex items-center gap-3">
                        <TeamLogo id={t.id} logo={t.logo} name={t.name} size="w-10 h-10" />
                        <div className="min-w-0">
                          <p className="text-[13px] font-semibold text-pi-primary truncate">{t.name}</p>
                          {t.country && <p className="text-[11px] text-pi-muted">{t.country}</p>}
                        </div>
                      </div>
                    ))}
                  </div>
                );
            })()}
          </div>
        )}

        {/* ── Top Players ────────────────────────────────────────────────────── */}
        {pageTab === "players" && (
          <div>
            {leadersLoading && <div className="py-16 flex justify-center"><Spinner /></div>}
            {!leadersLoading && leaderCategories.length === 0 && (
              <p className="py-12 text-center text-pi-muted text-sm">No player stats available.</p>
            )}
            {!leadersLoading && leaderCategories.map(cat => (
              <div key={cat.abbr} className="mb-6">
                <h3 className="text-sm font-bold text-pi-primary mb-3 flex items-center gap-2">
                  <Star size={13} className="text-amber-400" />{cat.name}
                </h3>
                <div className="card divide-y divide-pi-border/10">
                  {cat.leaders.slice(0, 10).map(p => (
                    <div key={p.player_id} className="flex items-center gap-3 px-4 py-3">
                      <span className="text-[11px] font-mono text-pi-muted w-5 text-center shrink-0">{p.rank}</span>
                      <PlayerHead id={p.player_id} src={p.headshot} name={p.name} />
                      <div className="flex-1 min-w-0">
                        <p className="text-[13px] font-semibold text-pi-primary truncate">{p.name}</p>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <TeamLogo id={p.team_id} logo={p.team_logo} name={p.team_name} size="w-4 h-4" />
                          <span className="text-[11px] text-pi-muted truncate">{p.team_name}</span>
                        </div>
                      </div>
                      <span className="text-lg font-bold text-pi-primary shrink-0">{p.display}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

      </div>
    </div>
  );
}
