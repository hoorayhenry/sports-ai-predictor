import { useState, useMemo } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Zap, RefreshCw, ChevronDown, ChevronUp,
  TrendingUp, Activity, BarChart2, AlertTriangle,
  ArrowUpRight, Clock, Target,
} from "lucide-react";
import { fetchDailyPicks, fetchSports, triggerDecisionsNow } from "../api/client";
import SportTabs from "../components/SportTabs";
import Spinner from "../components/Spinner";
import { formatDate } from "../utils/format";
import { Link } from "react-router-dom";
import type { MatchDecision } from "../api/types";

// ── Helpers ───────────────────────────────────────────────────────────────

function outcomeLabel(outcome: string | null): string {
  if (!outcome) return "—";
  const map: Record<string, string> = {
    H: "Home Win", D: "Draw", A: "Away Win",
    over: "Over 2.5", under: "Under 2.5",
    yes: "Both Teams Score", no: "Clean Sheet",
  };
  return map[outcome] ?? outcome;
}

function valueLabelConfig(label: string | null) {
  switch (label) {
    case "strong_value": return { text: "High Value",  cls: "text-violet-400 bg-violet-500/10 border-violet-500/25" };
    case "fair_value":   return { text: "Fair Value",  cls: "text-amber-400  bg-amber-500/10  border-amber-500/25"  };
    case "no_value":     return { text: "Low Value",   cls: "text-slate-400  bg-slate-500/10  border-slate-500/20"  };
    default:             return { text: "No Odds",     cls: "text-slate-500  bg-slate-500/5   border-slate-500/15"  };
  }
}

function confConfig(score: number) {
  if (score >= 75) return { label: "Strong",   color: "#10b981", glow: "#10b98140" };
  if (score >= 60) return { label: "Moderate", color: "#f59e0b", glow: "#f59e0b40" };
  return              { label: "Watch",    color: "#f43f5e", glow: "#f43f5e40" };
}

function edgeColor(edgePct: number | null): string {
  if (edgePct == null) return "#64748b";
  if (edgePct >= 8)  return "#10b981";
  if (edgePct >= 4)  return "#f59e0b";
  return "#f43f5e";
}

// ── Sub-components ────────────────────────────────────────────────────────

function StatTile({ icon, label, value, sub }: {
  icon: React.ReactNode; label: string; value: string | number; sub?: string;
}) {
  return (
    <div className="flex items-center gap-2.5 bg-white/[0.035] border border-white/[0.06] rounded-xl px-3.5 py-2.5 min-w-0">
      <div className="text-pi-muted/50 shrink-0">{icon}</div>
      <div className="min-w-0">
        <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-pi-muted/50 mb-0.5 whitespace-nowrap">{label}</p>
        <p className="text-[15px] font-extrabold text-pi-primary font-display tabular-nums leading-none">{value}</p>
        {sub && <p className="text-[9px] text-pi-muted/40 mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

function ConfidenceRing({ score }: { score: number }) {
  const R  = 26;
  const C  = 2 * Math.PI * R;
  const fill = Math.min(1, score / 100) * C;
  const { label, color, glow } = confConfig(score);

  return (
    <div className="relative shrink-0 w-[60px] h-[60px]">
      <svg width="60" height="60" className="rotate-[-90deg]" viewBox="0 0 60 60">
        <circle cx="30" cy="30" r={R} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="4" />
        <circle
          cx="30" cy="30" r={R}
          fill="none"
          stroke={color}
          strokeWidth="4"
          strokeDasharray={`${fill} ${C}`}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 5px ${glow})` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[16px] font-extrabold font-display tabular-nums leading-none" style={{ color }}>
          {Math.round(score)}
        </span>
        <span className="text-[7px] font-bold tracking-widest uppercase mt-[1px]" style={{ color, opacity: 0.65 }}>
          {label}
        </span>
      </div>
    </div>
  );
}

function ModelVsMarketBar({ modelPct, marketPct }: { modelPct: number; marketPct: number }) {
  const edge = modelPct - marketPct;
  const eColor = edgeColor(edge);

  return (
    <div className="space-y-[5px]">
      {/* Model bar */}
      <div className="flex items-center gap-2">
        <span className="text-[8px] font-bold uppercase tracking-[0.15em] text-emerald-400/60 w-[38px] text-right shrink-0">
          Model
        </span>
        <div className="flex-1 h-[5px] bg-white/5 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${Math.min(100, modelPct)}%`, background: "linear-gradient(90deg,#10b981,#34d399)" }}
          />
        </div>
        <span className="text-[10px] font-bold tabular-nums text-emerald-400 w-[30px] text-right">
          {modelPct.toFixed(0)}%
        </span>
      </div>

      {/* Market bar */}
      <div className="flex items-center gap-2">
        <span className="text-[8px] font-bold uppercase tracking-[0.15em] text-blue-400/60 w-[38px] text-right shrink-0">
          Market
        </span>
        <div className="flex-1 h-[5px] bg-white/5 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${Math.min(100, marketPct)}%`, background: "linear-gradient(90deg,#3b82f6,#60a5fa)" }}
          />
        </div>
        <span className="text-[10px] font-bold tabular-nums text-blue-400 w-[30px] text-right">
          {marketPct.toFixed(0)}%
        </span>
      </div>

      {/* Edge indicator */}
      <div className="flex justify-end pt-[1px]">
        <span
          className="flex items-center gap-0.5 text-[9px] font-bold uppercase tracking-[0.12em] px-1.5 py-[2px] rounded-full"
          style={{ color: eColor, background: `${eColor}18`, border: `1px solid ${eColor}30` }}
        >
          <ArrowUpRight size={8} />
          {edge > 0 ? "+" : ""}{edge.toFixed(1)}% Model Advantage
        </span>
      </div>
    </div>
  );
}

function ScoreBreakdown({ breakdown }: { breakdown: MatchDecision["score_breakdown"] }) {
  const items = [
    { label: "Probability",    val: breakdown.probability,    max: 40, color: "#818cf8" },
    { label: "Value Rating",   val: breakdown.expected_value, max: 20, color: "#34d399" },
    { label: "Form",           val: breakdown.form,           max: 20, color: "#f59e0b" },
    { label: "Consistency",    val: breakdown.consistency,    max: 20, color: "#f472b6" },
  ];

  return (
    <div className="grid grid-cols-4 gap-3 px-4 pb-4 pt-3 border-t border-white/[0.04]">
      {items.map(({ label, val, max, color }) => (
        <div key={label}>
          <div className="flex justify-between items-baseline mb-1">
            <span className="text-[9px] text-pi-muted/50 font-semibold uppercase tracking-wider">{label}</span>
            <span className="text-[10px] font-bold tabular-nums" style={{ color }}>{val.toFixed(0)}</span>
          </div>
          <div className="h-[3px] bg-white/5 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full"
              style={{ width: `${Math.min(100, (val / max) * 100)}%`, background: color }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Signal Card (PLAY) ────────────────────────────────────────────────────

function SignalCard({ pick }: { pick: MatchDecision }) {
  const [expanded, setExpanded] = useState(false);

  const conf    = Math.round(pick.confidence_score);
  const outcome = outcomeLabel(pick.predicted_outcome);
  const vCfg    = valueLabelConfig(pick.value_label);
  const { color: cColor } = confConfig(conf);

  const hasEdge   = pick.model_prob_pct != null && pick.market_prob_pct != null;
  const edgePct   = pick.edge_pct;
  const eColor    = edgeColor(edgePct);

  // Accent glow based on value label
  const accentBorder =
    pick.value_label === "strong_value" ? "rgba(139,92,246,0.35)" :
    pick.value_label === "fair_value"   ? "rgba(245,158,11,0.30)" :
                                          "rgba(255,255,255,0.07)";

  return (
    <Link to={`/match/${pick.match_id}`} className="block">
      <div
        className="rounded-2xl overflow-hidden cursor-pointer group transition-all duration-200
          hover:translate-y-[-1px] hover:shadow-xl"
        style={{
          background: "linear-gradient(135deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0.015) 100%)",
          border: `1px solid ${accentBorder}`,
          boxShadow: `0 1px 3px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.04)`,
        }}
      >
        {/* ── Competition / time header ── */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.05] bg-white/[0.015]">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm leading-none shrink-0">{pick.sport_icon}</span>
            <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-pi-muted/60 truncate">
              {pick.competition}
            </span>
          </div>
          <div className="flex items-center gap-3 shrink-0 ml-2">
            {/* Strong Signal badge */}
            <span className="flex items-center gap-1 text-[9px] font-extrabold uppercase tracking-[0.18em] text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 px-2 py-[3px] rounded-full">
              <Zap size={7} />
              Strong Signal
            </span>
            {/* Value label */}
            <span className={`text-[9px] font-bold uppercase tracking-[0.15em] px-2 py-[3px] rounded-full border ${vCfg.cls}`}>
              {vCfg.text}
            </span>
          </div>
        </div>

        {/* ── Main content ── */}
        <div className="px-4 py-4 flex items-start gap-4">

          {/* Left: teams + signal + edge bars */}
          <div className="flex-1 min-w-0 space-y-3.5">

            {/* Teams matchup */}
            <div className="flex items-center gap-2">
              <span className="font-display font-bold text-[16px] text-white truncate flex-1 leading-tight">
                {pick.home_team}
              </span>
              <span className="text-[9px] font-bold text-pi-muted/40 bg-white/5 rounded px-1.5 py-0.5 shrink-0 tracking-widest uppercase">
                vs
              </span>
              <span className="font-display font-bold text-[16px] text-white truncate flex-1 text-right leading-tight">
                {pick.away_team}
              </span>
            </div>

            {/* AI Signal outcome */}
            <div className="flex items-center gap-2">
              <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-pi-muted/40">AI Signal</span>
              <span className="text-[12px] font-extrabold text-white font-display tracking-wide">{outcome}</span>
              {pick.top_prob != null && (
                <span className="text-[10px] font-bold tabular-nums ml-auto" style={{ color: cColor }}>
                  {Math.round(pick.top_prob * 100)}%
                </span>
              )}
            </div>

            {/* Model vs Market bars */}
            {hasEdge ? (
              <ModelVsMarketBar
                modelPct={pick.model_prob_pct!}
                marketPct={pick.market_prob_pct!}
              />
            ) : (
              /* Fallback: simple probability bar */
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-pi-muted/40">Model Confidence</span>
                  <span className="text-[10px] font-bold tabular-nums" style={{ color: cColor }}>
                    {Math.round(pick.top_prob * 100)}%
                  </span>
                </div>
                <div className="h-[5px] bg-white/5 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.round(pick.top_prob * 100)}%`,
                      background: `linear-gradient(90deg, ${cColor}, ${cColor}aa)`,
                    }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Right: confidence ring + odds + kelly */}
          <div className="shrink-0 flex flex-col items-center gap-2.5 pt-1">
            <ConfidenceRing score={conf} />

            {pick.recommended_odds ? (
              <div
                className="w-full text-center rounded-xl px-2.5 py-1.5 border"
                style={{ background: "rgba(245,158,11,0.07)", borderColor: "rgba(245,158,11,0.25)" }}
              >
                <p className="text-[7px] font-bold uppercase tracking-[0.2em] text-amber-400/50 mb-[1px]">Odds</p>
                <p className="text-[18px] font-extrabold text-pi-amber tabular-nums font-display leading-none">
                  {pick.recommended_odds.toFixed(2)}
                </p>
              </div>
            ) : null}

            {pick.recommended_stake_pct && (
              <div className="text-center">
                <p className="text-[7px] font-bold uppercase tracking-[0.15em] text-pi-muted/35 mb-[1px]">Kelly</p>
                <p className="text-[11px] font-bold tabular-nums text-pi-muted/55">
                  {(pick.recommended_stake_pct * 100).toFixed(1)}%
                </p>
              </div>
            )}
          </div>
        </div>

        {/* ── Volatility warning ── */}
        {pick.has_volatility && (
          <div className="mx-4 mb-3 flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-500/5 border border-amber-500/15">
            <AlertTriangle size={10} className="text-pi-amber shrink-0" />
            <span className="text-[10px] text-pi-amber/70">{pick.volatility_reason || "Elevated uncertainty detected"}</span>
          </div>
        )}

        {/* ── Expand toggle ── */}
        <button
          className="w-full flex items-center justify-between px-4 py-2.5 border-t border-white/[0.04]
            hover:bg-white/[0.02] transition-colors text-left"
          onClick={e => { e.preventDefault(); setExpanded(v => !v); }}
        >
          <span className="flex items-center gap-1.5 text-[9px] text-pi-muted/40 uppercase tracking-wider font-bold">
            <BarChart2 size={9} />
            Score breakdown
          </span>
          {expanded
            ? <ChevronUp size={11} className="text-pi-muted/30" />
            : <ChevronDown size={11} className="text-pi-muted/30" />
          }
        </button>

        {expanded && pick.score_breakdown && (
          <ScoreBreakdown breakdown={pick.score_breakdown} />
        )}
      </div>
    </Link>
  );
}

// ── Analysed Row (SKIP) ───────────────────────────────────────────────────

function AnalysedRow({ pick }: { pick: MatchDecision }) {
  return (
    <Link to={`/match/${pick.match_id}`}>
      <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-white/[0.05] bg-white/[0.01]
        hover:bg-white/[0.025] transition-colors group">
        <span className="text-sm leading-none shrink-0">{pick.sport_icon}</span>

        <div className="flex-1 min-w-0">
          <p className="text-[12px] font-semibold text-pi-secondary/70 truncate leading-none">
            {pick.home_team} <span className="text-pi-muted/30 font-normal">vs</span> {pick.away_team}
          </p>
          <p className="text-[10px] text-pi-muted/40 mt-0.5">{pick.competition}</p>
        </div>

        <div className="shrink-0 text-right space-y-0.5">
          <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-pi-muted/35 bg-white/[0.03]
            border border-white/[0.05] px-2 py-[3px] rounded-full">
            No Clear Edge
          </p>
          {pick.skip_reason && (
            <p className="text-[9px] text-pi-muted/30 max-w-[160px] text-right leading-tight">
              {pick.skip_reason}
            </p>
          )}
        </div>
      </div>
    </Link>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function DailyPicksPage() {
  const [sport, setSport]       = useState("all");
  const [showSkips, setShowSkips] = useState(false);

  const { data: sports = [] } = useQuery({
    queryKey: ["sports"],
    queryFn: fetchSports,
    staleTime: 60_000,
  });

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["daily-picks", sport],
    queryFn: () => fetchDailyPicks(sport === "all" ? undefined : sport),
    staleTime: 30_000,
  });

  const runNow = useMutation({
    mutationFn: () => triggerDecisionsNow(false),
    onSuccess:  () => setTimeout(() => refetch(), 3000),
  });

  const picks: MatchDecision[] = data?.picks ?? [];
  const totalAnalysed = data?.total_analysed ?? 0;
  const totalPlays    = data?.total_plays    ?? 0;
  const selectionRate = data?.selection_rate ?? 0;

  // We only show PLAY picks in the main feed (already filtered by backend),
  // but keep a SKIP section using all-decisions endpoint is optional.
  // For now derive from picks array (backend returns PLAY only in daily-picks)
  const playPicks = picks.filter(p => p.ai_decision === "PLAY");
  const skipPicks = picks.filter(p => p.ai_decision === "SKIP");

  const avgEdge = useMemo(() => {
    const withEdge = playPicks.filter(p => p.edge_pct != null);
    if (!withEdge.length) return null;
    return withEdge.reduce((s, p) => s + p.edge_pct!, 0) / withEdge.length;
  }, [playPicks]);

  const highConf = playPicks.filter(p => p.confidence_score >= 75).length;

  return (
    <div className="min-h-screen pb-24 md:pb-6">

      {/* ── Hero header ─────────────────────────────────────────────────── */}
      <div
        className="relative overflow-hidden rounded-b-2xl md:rounded-2xl md:mx-4 md:mt-4 mb-5"
        style={{ minHeight: 160 }}
      >
        <img
          src="https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=1400&q=80&auto=format&fit=crop"
          alt=""
          className="absolute inset-0 w-full h-full object-cover object-top brightness-50 saturate-150 select-none pointer-events-none"
          aria-hidden="true"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/20 via-black/40 to-[#070c19]/95" />
        <div className="absolute inset-0 bg-gradient-to-r from-[#070c19]/75 via-transparent to-transparent" />

        <div className="relative px-5 pt-7 pb-5">
          {/* Title row */}
          <div className="flex items-start justify-between mb-4">
            <div>
              <div className="flex items-center gap-2 mb-1.5">
                <div className="bg-emerald-500/15 p-1.5 rounded-lg border border-emerald-500/20">
                  <Zap size={13} className="text-emerald-400" />
                </div>
                <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-emerald-400/70">
                  AI Signal Intelligence
                </span>
              </div>
              <h1 className="text-[28px] md:text-[34px] font-extrabold text-white font-display leading-none drop-shadow-lg">
                Daily Signals
              </h1>
            </div>

            <button
              onClick={() => runNow.mutate()}
              disabled={runNow.isPending}
              className="btn-ghost flex items-center gap-1.5 shrink-0 backdrop-blur-sm mt-1"
            >
              <RefreshCw size={12} className={runNow.isPending ? "animate-spin" : ""} />
              {runNow.isPending ? "Running…" : "Refresh"}
            </button>
          </div>

          {/* Stats tiles */}
          {!isLoading && (
            <div className="flex gap-2 flex-wrap">
              <StatTile
                icon={<Activity size={13} />}
                label="Analysed"
                value={totalAnalysed}
                sub="matches today"
              />
              <StatTile
                icon={<Zap size={13} />}
                label="Strong Signals"
                value={totalPlays}
                sub={highConf > 0 ? `${highConf} high conf` : undefined}
              />
              <StatTile
                icon={<Target size={13} />}
                label="Selection Rate"
                value={`${selectionRate}%`}
                sub="engine selectivity"
              />
              {avgEdge != null && (
                <StatTile
                  icon={<TrendingUp size={13} />}
                  label="Avg Edge"
                  value={`+${avgEdge.toFixed(1)}%`}
                  sub="model advantage"
                />
              )}
            </div>
          )}
        </div>
      </div>

      <div className="px-4">

        {/* ── Sport filter ────────────────────────────────────────────── */}
        <div className="mb-5">
          <SportTabs sports={sports} selected={sport} onSelect={setSport} />
        </div>

        {isLoading ? (
          <div className="flex justify-center py-24"><Spinner size={44} /></div>

        ) : picks.length === 0 && totalAnalysed === 0 ? (
          /* Nothing analysed yet */
          <div className="card p-10 text-center">
            <div className="w-14 h-14 rounded-2xl bg-emerald-500/8 border border-emerald-500/15 flex items-center justify-center mx-auto mb-4">
              <Zap size={22} className="text-emerald-500/40" />
            </div>
            <p className="font-display text-lg font-bold text-pi-primary mb-2">No Signals Yet</p>
            <p className="text-sm text-pi-muted mb-5 max-w-xs mx-auto">
              The intelligence engine hasn't analysed today's matches. Run it now to generate signals.
            </p>
            <button onClick={() => runNow.mutate()} className="btn-primary">
              Run Intelligence Engine
            </button>
          </div>

        ) : (
          <>
            {/* ── Strong Signals (PLAY) ──────────────────────────────── */}
            {playPicks.length > 0 ? (
              <div className="space-y-3 mb-6">
                {playPicks.map(pick => (
                  <SignalCard key={pick.match_id} pick={pick} />
                ))}
              </div>
            ) : (
              <div className="card p-6 text-center mb-6">
                <div className="w-10 h-10 rounded-xl bg-white/[0.03] border border-white/[0.07] flex items-center justify-center mx-auto mb-3">
                  <Zap size={18} className="text-pi-muted/30" />
                </div>
                <p className="font-display text-sm font-semibold text-pi-primary mb-1">No strong signals today</p>
                <p className="text-[12px] text-pi-muted/60 max-w-xs mx-auto">
                  The engine analysed {totalAnalysed} {totalAnalysed === 1 ? "match" : "matches"} and found no opportunities
                  meeting the EV + edge threshold.
                </p>
              </div>
            )}

            {/* ── Analysed / skipped (collapsed) ──────────────────────── */}
            {totalAnalysed > 0 && (
              <div>
                <button
                  onClick={() => setShowSkips(v => !v)}
                  className="flex items-center gap-2 mb-3 text-pi-muted/50 hover:text-pi-muted/70 transition-colors"
                >
                  <Clock size={11} />
                  <span className="text-[10px] font-bold uppercase tracking-wider">
                    {totalAnalysed - totalPlays} analysed · no clear edge
                  </span>
                  {showSkips ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                </button>

                {showSkips && skipPicks.length > 0 && (
                  <div className="space-y-1.5">
                    {skipPicks.map(pick => (
                      <AnalysedRow key={pick.match_id} pick={pick} />
                    ))}
                    {skipPicks.length < (totalAnalysed - totalPlays) && (
                      <p className="text-[10px] text-pi-muted/30 text-center pt-1">
                        Showing {skipPicks.length} of {totalAnalysed - totalPlays} analysed matches
                      </p>
                    )}
                  </div>
                )}

                {showSkips && skipPicks.length === 0 && (
                  <p className="text-[11px] text-pi-muted/40 px-1">
                    Detailed skip data not available in this view. Use the Predictions page for full analysis.
                  </p>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
