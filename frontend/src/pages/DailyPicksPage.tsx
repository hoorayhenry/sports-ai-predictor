import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Flame, RefreshCw, ChevronDown, ChevronUp, AlertTriangle } from "lucide-react";
import { fetchDailyPicks, fetchSports, triggerDecisionsNow } from "../api/client";
import SportTabs from "../components/SportTabs";
import Spinner from "../components/Spinner";
import { formatDate } from "../utils/format";
import { Link } from "react-router-dom";
import type { MatchDecision } from "../api/types";

// Human-readable market labels
function marketLabel(outcome: string | null): string {
  if (!outcome) return "—";
  const map: Record<string, string> = {
    H:     "Home Win",
    D:     "Draw",
    A:     "Away Win",
    over:  "Over 2.5 Goals",
    under: "Under 2.5 Goals",
    yes:   "Both Teams Score",
    no:    "Clean Sheet",
  };
  return map[outcome] ?? outcome;
}

// Confidence arc SVG — clean circular progress indicator
function ConfidenceArc({ score }: { score: number }) {
  const R  = 30;
  const C  = 2 * Math.PI * R;
  const fill = Math.min(1, score / 100) * C;
  const color =
    score >= 75 ? "#10b981" :
    score >= 60 ? "#f59e0b" : "#f43f5e";
  const label =
    score >= 75 ? "HIGH" :
    score >= 60 ? "MED"  : "RISKY";

  return (
    <div className="relative shrink-0 w-[72px] h-[72px]">
      <svg width="72" height="72" className="rotate-[-90deg]" viewBox="0 0 72 72">
        <circle cx="36" cy="36" r={R} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="5" />
        <circle
          cx="36" cy="36" r={R}
          fill="none"
          stroke={color}
          strokeWidth="5"
          strokeDasharray={`${fill} ${C}`}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 4px ${color}60)` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[22px] font-bold font-display tabular-nums leading-none" style={{ color }}>
          {Math.round(score)}
        </span>
        <span className="text-[8px] font-bold tracking-widest uppercase mt-0.5" style={{ color, opacity: 0.7 }}>
          {label}
        </span>
      </div>
    </div>
  );
}

// ── Main pick card (PLAY) ──────────────────────────────────────────────────
function PlayCard({ pick }: { pick: MatchDecision }) {
  const [expanded, setExpanded] = useState(false);
  const conf   = Math.round(pick.confidence_score);
  const prob   = Math.round(pick.top_prob * 100);
  const market = marketLabel(pick.predicted_outcome);

  const accentColor =
    conf >= 75 ? "rgba(16,185,129,0.35)"  :
    conf >= 60 ? "rgba(245,158,11,0.35)"  : "rgba(244,63,94,0.35)";
  const barColor =
    conf >= 75 ? "linear-gradient(90deg,#10b981,#34d399)" :
    conf >= 60 ? "linear-gradient(90deg,#f59e0b,#fbbf24)" :
                 "linear-gradient(90deg,#f43f5e,#fb7185)";

  return (
    <Link to={`/match/${pick.match_id}`} onClick={e => e.stopPropagation()}>
      <div
        className="card card-play overflow-hidden cursor-pointer group"
        style={{ borderColor: accentColor }}
      >
        {/* ── Competition header ─── */}
        <div className="flex items-center justify-between px-5 py-2 border-b border-white/5 bg-white/[0.02]">
          <span className="flex items-center gap-1.5 text-[11px] font-semibold text-pi-muted uppercase tracking-wider">
            <span className="text-base leading-none">{pick.sport_icon}</span>
            {pick.competition}
          </span>
          <span className="text-[11px] text-pi-muted/70 font-medium">{formatDate(pick.match_date)}</span>
        </div>

        {/* ── Main content row ─── */}
        <div className="flex items-center gap-4 px-5 py-4">

          {/* Confidence arc */}
          <ConfidenceArc score={conf} />

          {/* Teams + market */}
          <div className="flex-1 min-w-0">
            {/* Team matchup */}
            <div className="flex items-center gap-2 mb-3">
              <span className="font-display font-bold text-[17px] text-pi-primary truncate leading-none flex-1">
                {pick.home_team}
              </span>
              <span className="text-[10px] font-bold text-pi-muted/60 bg-white/5 rounded px-1.5 py-0.5 shrink-0 tracking-widest">
                VS
              </span>
              <span className="font-display font-bold text-[17px] text-pi-primary truncate leading-none flex-1 text-right">
                {pick.away_team}
              </span>
            </div>

            {/* Market prediction */}
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <span className="section-label text-pi-muted/60">Prediction</span>
                <span className="font-display font-bold text-[13px] text-white tracking-wide">{market}</span>
              </div>
              <span className="text-[12px] font-bold text-pi-secondary tabular-nums">{prob}%</span>
            </div>

            {/* Probability bar */}
            <div className="h-2 bg-white/5 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${prob}%`, background: barColor }}
              />
            </div>
          </div>

          {/* Odds + PLAY badge */}
          <div className="shrink-0 flex flex-col items-center gap-2 pl-2">
            <div
              className="rounded-xl px-3 py-2 text-center border"
              style={{ background: "rgba(16,185,129,0.08)", borderColor: "rgba(16,185,129,0.3)" }}
            >
              <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-emerald-400/60 mb-0.5">PLAY</p>
              {pick.recommended_odds ? (
                <p className="text-2xl font-bold text-pi-amber tabular-nums font-display leading-none">
                  {pick.recommended_odds.toFixed(2)}
                </p>
              ) : (
                <p className="text-sm font-bold text-emerald-400 font-display">—</p>
              )}
            </div>
            {pick.recommended_stake_pct && (
              <span className="text-[10px] text-pi-muted/60 text-center">
                Kelly {(pick.recommended_stake_pct * 100).toFixed(1)}%
              </span>
            )}
          </div>
        </div>

        {/* ── Expandable detail ─── */}
        <button
          className="w-full flex items-center justify-between px-5 py-2 border-t border-white/5 hover:bg-white/[0.02] transition-colors text-left"
          onClick={e => { e.preventDefault(); setExpanded(v => !v); }}
        >
          <span className="text-[10px] text-pi-muted/50 uppercase tracking-wider font-semibold">Score breakdown</span>
          {expanded ? <ChevronUp size={12} className="text-pi-muted/40" /> : <ChevronDown size={12} className="text-pi-muted/40" />}
        </button>

        {expanded && pick.score_breakdown && (
          <div className="px-5 pb-4 grid grid-cols-4 gap-3 border-t border-white/[0.04]">
            {[
              { label: "Probability", val: pick.score_breakdown.probability,    max: 40, color: "#818cf8" },
              { label: "Exp. Value",  val: pick.score_breakdown.expected_value,  max: 20, color: "#34d399" },
              { label: "Form",        val: pick.score_breakdown.form,            max: 20, color: "#f59e0b" },
              { label: "Consistency", val: pick.score_breakdown.consistency,     max: 20, color: "#f472b6" },
            ].map(({ label, val, max, color }) => (
              <div key={label} className="pt-3">
                <div className="flex justify-between items-baseline mb-1.5">
                  <span className="text-[10px] text-pi-muted/60 font-medium">{label}</span>
                  <span className="text-[11px] font-bold tabular-nums" style={{ color }}>{val.toFixed(0)}</span>
                </div>
                <div className="h-1 bg-white/5 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${Math.min(100, (val / max) * 100)}%`, background: color }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}

        {pick.has_volatility && (
          <div className="px-5 py-2 border-t border-amber-500/10 bg-amber-500/5 flex items-center gap-2">
            <AlertTriangle size={11} className="text-pi-amber shrink-0" />
            <span className="text-[11px] text-pi-amber/80">{pick.volatility_reason || "Some uncertainty detected"}</span>
          </div>
        )}
      </div>
    </Link>
  );
}

// ── Compact SKIP row ───────────────────────────────────────────────────────
function SkipRow({ pick }: { pick: MatchDecision }) {
  return (
    <Link to={`/match/${pick.match_id}`}>
      <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-pi-border/20 bg-white/[0.015] hover:bg-white/[0.03] transition-colors">
        <span className="text-base leading-none shrink-0">{pick.sport_icon}</span>
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-semibold text-pi-secondary/80 truncate leading-none">
            {pick.home_team} <span className="text-pi-muted/40 font-normal">vs</span> {pick.away_team}
          </p>
          <p className="text-[11px] text-pi-muted/50 mt-0.5">{pick.competition}</p>
        </div>
        <span className="text-[11px] font-bold text-pi-muted/50 bg-pi-surface px-2 py-0.5 rounded-full border border-pi-border/20">
          SKIP
        </span>
      </div>
    </Link>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────
export default function DailyPicksPage() {
  const [sport, setSport] = useState("all");
  const [showSkips, setShowSkips] = useState(false);

  const { data: sports = [] } = useQuery({
    queryKey: ["sports"],
    queryFn: fetchSports,
    staleTime: 60_000,
  });

  const { data: picks = [], isLoading, refetch } = useQuery({
    queryKey: ["daily-picks", sport],
    queryFn: () => fetchDailyPicks(sport === "all" ? undefined : sport),
    staleTime: 30_000,
  });

  const runNow = useMutation({
    mutationFn: () => triggerDecisionsNow(false),
    onSuccess: () => setTimeout(() => refetch(), 3000),
  });

  const playPicks = picks.filter(p => p.ai_decision === "PLAY");
  const skipPicks = picks.filter(p => p.ai_decision === "SKIP");

  const highConf = playPicks.filter(p => p.confidence_score >= 75).length;

  return (
    <div className="min-h-screen pb-20 md:pb-6">

      {/* ── Hero ────────────────────────────────────────────── */}
      <div className="relative overflow-hidden rounded-b-2xl md:rounded-2xl md:mx-4 md:mt-4 mb-6" style={{ minHeight: 180 }}>
        <img
          src="https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=1400&q=80&auto=format&fit=crop"
          alt=""
          className="absolute inset-0 w-full h-full object-cover object-top brightness-75 saturate-125 select-none pointer-events-none"
          aria-hidden="true"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/10 via-black/25 to-[#070c19]/92" />
        <div className="absolute inset-0 bg-gradient-to-r from-[#070c19]/80 via-transparent to-transparent" />

        <div className="relative px-5 pt-7 pb-6 flex items-end justify-between">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <div className="bg-pi-emerald/20 p-1.5 rounded-lg backdrop-blur-sm">
                <Flame size={15} className="text-pi-emerald" />
              </div>
              <span className="section-label text-pi-emerald/80">AI Selections</span>
            </div>
            <h1 className="text-3xl md:text-4xl font-extrabold text-white font-display leading-none mb-3 drop-shadow-lg">
              Daily Picks
            </h1>
            {/* Stats strip */}
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 rounded-full backdrop-blur-sm">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                {playPicks.length} Plays
              </span>
              {highConf > 0 && (
                <span className="text-xs font-semibold text-emerald-300/80 bg-white/5 px-2 py-0.5 rounded-full border border-white/10">
                  {highConf} High Confidence
                </span>
              )}
            </div>
          </div>

          <button
            onClick={() => runNow.mutate()}
            disabled={runNow.isPending}
            className="btn-ghost flex items-center gap-1.5 shrink-0 backdrop-blur-sm"
          >
            <RefreshCw size={13} className={runNow.isPending ? "animate-spin" : ""} />
            {runNow.isPending ? "Running..." : "Refresh"}
          </button>
        </div>
      </div>

      <div className="px-4">

        {/* ── Sport filter ─────────────────────────────────── */}
        <div className="mb-5">
          <SportTabs sports={sports} selected={sport} onSelect={setSport} />
        </div>

        {isLoading ? (
          <div className="flex justify-center py-24"><Spinner size={44} /></div>

        ) : picks.length === 0 ? (
          <div className="card p-10 text-center">
            <div className="w-16 h-16 rounded-2xl bg-pi-emerald/10 border border-emerald-500/20 flex items-center justify-center mx-auto mb-4">
              <Flame size={24} className="text-pi-emerald/60" />
            </div>
            <p className="font-display text-xl font-bold text-pi-primary mb-2 tracking-wide">No Picks Yet</p>
            <p className="text-sm text-pi-muted mb-5 max-w-xs mx-auto">
              The AI engine is analysing upcoming matches. Click Refresh to run the engine now.
            </p>
            <button onClick={() => runNow.mutate()} className="btn-primary">
              Run AI Engine
            </button>
          </div>

        ) : (
          <>
            {/* ── PLAY picks ─────────────────────────────── */}
            {playPicks.length > 0 && (
              <div className="space-y-3 mb-6">
                {playPicks.map((pick) => (
                  <PlayCard key={pick.match_id} pick={pick} />
                ))}
              </div>
            )}

            {playPicks.length === 0 && (
              <div className="card p-6 text-center mb-6">
                <p className="font-display text-base font-semibold text-pi-primary mb-1 tracking-wide">No PLAY picks today</p>
                <p className="text-sm text-pi-muted">The AI only recommends high-confidence selections. Nothing clears the bar right now.</p>
              </div>
            )}

            {/* ── SKIP picks (collapsed) ─────────────────── */}
            {skipPicks.length > 0 && (
              <div>
                <button
                  onClick={() => setShowSkips(v => !v)}
                  className="flex items-center gap-2 mb-3 text-pi-muted/60 hover:text-pi-muted transition-colors"
                >
                  <span className="text-[11px] font-semibold uppercase tracking-wider">
                    {skipPicks.length} Analysed · Not Recommended
                  </span>
                  {showSkips ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                </button>
                {showSkips && (
                  <div className="space-y-1.5">
                    {skipPicks.map(pick => (
                      <SkipRow key={pick.match_id} pick={pick} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}

      </div>
    </div>
  );
}
