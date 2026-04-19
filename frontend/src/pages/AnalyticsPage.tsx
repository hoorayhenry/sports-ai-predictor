/**
 * PlaySigma Intelligence Dashboard
 * Grafana-style real-time model observability.
 *
 * Sections:
 *   1. KPI strip        — accuracy, ROI, picks, signals
 *   2. Accuracy timeline — rolling 14-day accuracy + cumulative ROI
 *   3. Market + League   — performance breakdown
 *   4. Calibration curve — predicted vs actual probability
 *   5. Feature importance — XGBoost top-20 features
 *   6. Confidence histogram + PLAY/SKIP split
 *   7. Intelligence signals feed
 *   8. Model health + training history
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AreaChart, Area, BarChart, Bar, ComposedChart,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, PieChart, Pie, Cell, Legend, Line,
} from "recharts";
import type { ValueType, NameType } from "recharts/types/component/DefaultTooltipContent";
import {
  Activity, Brain, Zap, TrendingUp, TrendingDown, Target,
  RefreshCw, AlertCircle, CheckCircle2, Clock, BarChart2,
  Database, Cpu, FlaskConical,
} from "lucide-react";
import Spinner from "../components/Spinner";
import { api } from "../api/client";

// ── Colour palette (matches Tailwind vars) ───────────────────────────────────
const C = {
  indigo:   "#6366f1",
  indigoL:  "#818cf8",
  emerald:  "#10b981",
  emeraldL: "#34d399",
  amber:    "#f59e0b",
  rose:     "#f43f5e",
  sky:      "#38bdf8",
  violet:   "#8b5cf6",
  muted:    "#64748b",
  border:   "rgba(148,163,184,0.12)",
  surface:  "rgba(15,23,42,0.6)",
};

const GROUP_COLORS: Record<string, string> = {
  "Elo":          C.violet,
  "Poisson":      C.indigo,
  "Market Odds":  C.amber,
  "Shots / xG":   C.sky,
  "Form":         C.emerald,
  "Strength":     "#a78bfa",
  "H2H":          "#fb923c",
  "Table":        "#2dd4bf",
  "Intelligence": C.rose,
  "Referee":      "#e879f9",
  "Fatigue":      C.muted,
  "Other":        "#94a3b8",
};

// ── Shared tooltip style ──────────────────────────────────────────────────────
// contentStyle only styles the box — labelStyle + itemStyle force text colours
const tooltipStyle = {
  backgroundColor: "#0d1633",
  border: "1px solid rgba(99,102,241,0.5)",
  borderRadius: 10,
  padding: "10px 14px",
  boxShadow: "0 8px 32px rgba(0,0,0,0.6)",
};
const tooltipLabelStyle = {
  color: "#ffffff",
  fontWeight: 700,
  fontSize: 13,
  marginBottom: 4,
};
const tooltipItemStyle = {
  color: "#c7d2fe",
  fontSize: 13,
  fontWeight: 500,
};

// Shared tooltip props spread onto every <Tooltip>
const TP = {
  contentStyle:  tooltipStyle,
  labelStyle:    tooltipLabelStyle,
  itemStyle:     tooltipItemStyle,
  cursor:        { stroke: "rgba(99,102,241,0.3)", strokeWidth: 1 },
} as const;

// ── Types ─────────────────────────────────────────────────────────────────────

interface Overview {
  accuracy: { all_time: number | null; total_picks: number; total_wins: number };
  roi: { all_time_units: number; last_30d_units: number; last_30d_picks: number };
  active_plays: number;
  signals: { last_7d: number; last_24h: number };
  data: { total_matches: number; finished_matches: number };
  last_retrain: string | null;
}

interface TimePoint {
  date: string;
  accuracy: number | null;
  rolling_accuracy: number | null;
  picks: number;
  cumulative_roi: number;
}

interface MarketRow  { market: string;       picks: number; wins: number; accuracy: number | null; roi: number }
interface LeagueRow  { competition: string;  picks: number; wins: number; accuracy: number | null; roi: number }
interface CalPoint   { bucket_label: string; bucket_mid: number; predicted_avg: number; actual_rate: number; count: number }
interface Feature    { feature: string; importance: number; group: string; label: string }
interface Signal     { id: number; team: string; type: string; entity: string; impact: number; confidence: number; time: string }
interface HistBucket { range: string; count: number }
interface SportRow   {
  sport: string; display_name: string;
  matches_total: number; matches_finished: number;
  picks: number; wins: number;
  accuracy: number | null; roi: number;
  model_accuracy: number | null; training_rows: number; last_trained: string | null;
}
interface LearningPoint {
  trained_at: string; training_rows: number;
  ll_result: number | null; accuracy_est: number | null;
}

// ── Recharts formatter helpers (typed to avoid ValueType | undefined errors) ──
type Fmt = (v: ValueType | undefined, name: NameType | undefined) => [string, string] | [string];
const fmtPctNamed = (label: string): Fmt => (v, name) => [
  `${((v as number ?? 0) * 100).toFixed(1)}%`,
  name === "rolling_accuracy" ? "Rolling Acc" : label,
];
const fmtRoi: Fmt   = (v) => { const n = v as number ?? 0; return [`${n > 0 ? "+" : ""}${n.toFixed(2)}u`]; };
const fmtNum: Fmt   = (v) => [`${((v as number ?? 0) * 100).toFixed(1)}%`, "Accuracy"];
const fmtLabelShort = (label: unknown) => typeof label === "string" ? shortDate(label) : String(label ?? "");

// ── Helpers ───────────────────────────────────────────────────────────────────

function pct(v: number | null | undefined, decimals = 1): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(decimals)}%`;
}
function num(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString();
}
function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "Never";
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3_600_000);
  const d = Math.floor(h / 24);
  if (d > 0) return `${d}d ago`;
  if (h > 0) return `${h}h ago`;
  return "< 1h ago";
}
function shortDate(iso: string) {
  return iso.slice(5);   // "MM-DD"
}

// ── Sub-components ────────────────────────────────────────────────────────────

function KpiCard({
  icon, label, value, sub, trend, accent = C.indigoL,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  trend?: "up" | "down" | null;
  accent?: string;
}) {
  return (
    <div className="card p-5 flex flex-col gap-2.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-lg" style={{ background: `${accent}25` }}>
            {icon}
          </div>
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{label}</span>
        </div>
        {trend === "up"   && <TrendingUp  size={15} className="text-pi-emerald" />}
        {trend === "down" && <TrendingDown size={15} className="text-pi-rose" />}
      </div>
      <p className="text-3xl font-extrabold text-white tabular-nums font-display">{value}</p>
      {sub && <p className="text-xs text-slate-400 leading-snug">{sub}</p>}
    </div>
  );
}

function SectionHeader({ icon, title, sub }: { icon: React.ReactNode; title: string; sub?: string }) {
  return (
    <div className="flex items-center gap-3 mb-5">
      <div className="p-2 bg-pi-indigo/15 rounded-lg">{icon}</div>
      <div>
        <h3 className="font-bold text-white font-display text-base leading-tight">{title}</h3>
        {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

function EmptyChart({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-44 gap-3">
      <AlertCircle size={28} className="text-slate-500" />
      <p className="text-sm text-slate-400 text-center max-w-xs leading-relaxed">{message}</p>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const qc = useQueryClient();

  const q = <T,>(key: string, path: string, refetchMs = 120_000) =>
    useQuery<T>({
      queryKey: [key],
      queryFn:  () => api.get(path).then(r => r.data),
      staleTime: 60_000,
      refetchInterval: refetchMs,
    });

  const overview      = q<Overview>          ("an-overview",     "/analytics/overview",              60_000);
  const timeline      = q<{data: TimePoint[]}>    ("an-timeline",     "/analytics/accuracy-timeline",     300_000);
  const roiTl         = q<{data: TimePoint[]}>    ("an-roi",          "/analytics/roi-timeline",          300_000);
  const markets       = q<{data: MarketRow[]}>    ("an-markets",      "/analytics/market-performance",    300_000);
  const leagues       = q<{data: LeagueRow[]}>    ("an-leagues",      "/analytics/league-performance",    300_000);
  const calibration   = q<{data: CalPoint[]}>     ("an-cal",          "/analytics/calibration",           300_000);
  const features      = q<{data: Feature[], status?: string}>("an-feat","analytics/feature-importance",   900_000);
  const signals       = q<{feed: Signal[], daily: any[]}>  ("an-sigs","analytics/signals-feed",          60_000);
  const histogram     = q<{histogram: HistBucket[], play_count: number, skip_count: number, play_rate: number | null}>
                          ("an-hist",     "/analytics/confidence-histogram",  120_000);
  const health        = q<any>              ("an-health",       "/analytics/model-health",          300_000);
  const sportBreakdown = q<{data: SportRow[]}>("an-sport-bd",  "/analytics/sport-breakdown",        300_000);
  // Live training progress — polls every 2s while training, 30s when idle
  const trainProg = useQuery<any>({
    queryKey: ["an-train-prog"],
    queryFn:  () => api.get("/analytics/training-progress").then(r => r.data),
    staleTime: 0,
    refetchInterval: (query) => (query.state.data as any)?.is_training ? 2_000 : 30_000,
  });
  const learningCurve  = q<{data: Record<string, LearningPoint[]>, sports: string[]}>(
                          "an-learn",          "/analytics/learning-curve",         600_000);

  const retrain = useMutation({
    mutationFn: () => api.post("/decisions/analytics/trigger-retrain"),
    onSuccess:  () => setTimeout(() => qc.invalidateQueries(), 3000),
  });

  const ov = overview.data;
  const tl = timeline.data?.data ?? [];
  const rl = roiTl.data?.data   ?? [];

  // ── Sport emoji map ────────────────────────────────────────────────
  const SPORT_ICONS: Record<string, string> = {
    football: "⚽", basketball: "🏀", tennis: "🎾", baseball: "⚾",
    american_football: "🏈", ice_hockey: "🏒", cricket: "🏏",
    rugby: "🏉", handball: "🤾", volleyball: "🏐",
  };

  // ── Accuracy colour ────────────────────────────────────────────────
  function accColor(v: number | null | undefined) {
    if (v == null) return C.muted;
    if (v >= 0.58) return C.emerald;
    if (v >= 0.50) return C.amber;
    return C.rose;
  }
  const currentRoi = rl.length ? rl[rl.length - 1].cumulative_roi   : null;

  return (
    <div className="min-h-screen pb-24 md:pb-8 px-4 md:px-6 pt-6">

      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-extrabold text-white font-display flex items-center gap-3">
            <Brain size={26} className="text-pi-indigo-light" />
            Intelligence Dashboard
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Live model observability · Calibration · Feature signals · ROI tracking
          </p>
        </div>
        <button
          onClick={() => retrain.mutate()}
          disabled={retrain.isPending}
          className="btn-secondary flex items-center gap-1.5 text-xs"
        >
          <RefreshCw size={12} className={retrain.isPending ? "animate-spin" : ""} />
          {retrain.isPending ? "Retraining…" : "Retrain Now"}
        </button>
      </div>

      {/* ── 1. KPI strip ────────────────────────────────────────────── */}
      {overview.isLoading ? (
        <div className="flex justify-center py-8"><Spinner size={36} /></div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4 mb-6">
          <KpiCard
            icon={<Target size={14} style={{ color: accColor(ov?.accuracy.all_time) }} />}
            label="Overall Accuracy"
            value={pct(ov?.accuracy.all_time)}
            sub={`${num(ov?.accuracy.total_wins)} wins / ${num(ov?.accuracy.total_picks)} picks`}
            accent={accColor(ov?.accuracy.all_time)}
            trend={ov?.accuracy.all_time != null ? (ov.accuracy.all_time >= 0.55 ? "up" : "down") : null}
          />
          <KpiCard
            icon={<TrendingUp size={14} style={{ color: (currentRoi ?? 0) >= 0 ? C.emerald : C.rose }} />}
            label="Cumulative ROI"
            value={currentRoi != null ? `${currentRoi > 0 ? "+" : ""}${currentRoi.toFixed(1)}u` : "—"}
            sub={`Last 30d: ${ov?.roi.last_30d_units != null ? (ov.roi.last_30d_units > 0 ? "+" : "") + ov.roi.last_30d_units.toFixed(1) + "u" : "—"}`}
            accent={(currentRoi ?? 0) >= 0 ? C.emerald : C.rose}
            trend={(currentRoi ?? 0) >= 0 ? "up" : "down"}
          />
          <KpiCard
            icon={<Zap size={14} style={{ color: C.amber }} />}
            label="Active PLAY Picks"
            value={num(ov?.active_plays)}
            sub="Upcoming matches"
            accent={C.amber}
          />
          <KpiCard
            icon={<Activity size={14} style={{ color: C.sky }} />}
            label="Intel Signals (7d)"
            value={num(ov?.signals.last_7d)}
            sub={`${num(ov?.signals.last_24h)} in last 24h`}
            accent={C.sky}
          />
          <KpiCard
            icon={<Database size={14} style={{ color: C.violet }} />}
            label="Training Matches"
            value={num(ov?.data.finished_matches)}
            sub={`${num(ov?.data.total_matches)} total in DB`}
            accent={C.violet}
          />
          <KpiCard
            icon={<Clock size={14} style={{ color: C.muted }} />}
            label="Last Retrain"
            value={timeAgo(ov?.last_retrain)}
            sub="Auto-retrains weekly"
            accent={C.muted}
          />
        </div>
      )}

      {/* ── 2. Sport-by-Sport AI Performance ──────────────────────── */}
      <div className="card p-5 mb-6">
        <SectionHeader
          icon={<Brain size={14} className="text-pi-indigo-light" />}
          title="AI Performance by Sport"
          sub="Prediction accuracy, training data volume and model confidence across every sport"
        />
        {!sportBreakdown.data?.data?.length ? (
          <EmptyChart message="Sport breakdown will populate as matches are ingested and predictions resolve. Daily ingestion runs at 02:00 UTC." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-pi-border/20">
                  <th className="text-left text-[11px] text-pi-muted font-semibold pb-2 pr-4">Sport</th>
                  <th className="text-right text-[11px] text-pi-muted font-semibold pb-2 px-3">Training Data</th>
                  <th className="text-right text-[11px] text-pi-muted font-semibold pb-2 px-3">Picks</th>
                  <th className="text-right text-[11px] text-pi-muted font-semibold pb-2 px-3">Pick Acc.</th>
                  <th className="text-right text-[11px] text-pi-muted font-semibold pb-2 px-3">Model Acc.</th>
                  <th className="text-right text-[11px] text-pi-muted font-semibold pb-2 px-3">ROI</th>
                  <th className="text-left text-[11px] text-pi-muted font-semibold pb-2 pl-4">Progress</th>
                </tr>
              </thead>
              <tbody>
                {sportBreakdown.data.data.map((s) => {
                  const modelAcc = s.model_accuracy;
                  const pickAcc  = s.accuracy;
                  // Progress bar based on training data (50k rows = full bar)
                  const progress = Math.min(100, (s.training_rows / 50_000) * 100);
                  return (
                    <tr key={s.sport} className="border-b border-pi-border/10 last:border-0 hover:bg-white/2">
                      <td className="py-2.5 pr-4">
                        <div className="flex items-center gap-2">
                          <span className="text-base">{SPORT_ICONS[s.sport] ?? "🏆"}</span>
                          <span className="font-semibold text-white">{s.display_name}</span>
                        </div>
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        <span className="text-pi-primary font-medium">{s.training_rows.toLocaleString()}</span>
                        <span className="text-[10px] text-pi-muted ml-1">rows</span>
                      </td>
                      <td className="py-2.5 px-3 text-right text-pi-secondary">{s.picks}</td>
                      <td className="py-2.5 px-3 text-right font-semibold" style={{ color: accColor(pickAcc) }}>
                        {pct(pickAcc)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-semibold" style={{ color: accColor(modelAcc) }}>
                        {modelAcc != null ? pct(modelAcc) : <span className="text-pi-muted text-[11px]">no model</span>}
                      </td>
                      <td className="py-2.5 px-3 text-right" style={{ color: s.roi >= 0 ? C.emerald : C.rose }}>
                        {s.roi > 0 ? "+" : ""}{s.roi.toFixed(1)}u
                      </td>
                      <td className="py-2.5 pl-4">
                        <div className="flex items-center gap-2">
                          <div className="w-24 h-1.5 bg-pi-surface rounded-full overflow-hidden">
                            <div
                              className="h-1.5 rounded-full transition-all"
                              style={{
                                width: `${progress}%`,
                                background: progress >= 80 ? C.emerald : progress >= 40 ? C.amber : C.indigo,
                              }}
                            />
                          </div>
                          <span className="text-[10px] text-pi-muted">{progress.toFixed(0)}%</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="text-[10px] text-pi-muted mt-3">
              Progress bar = training data vs 50,000 row target. More data = higher accuracy. Daily ingestion adds new matches automatically.
            </p>
          </div>
        )}
      </div>

      {/* ── 3. Learning Curve ───────────────────────────────────────── */}
      <div className="card p-5 mb-6">
        <SectionHeader
          icon={<TrendingUp size={14} className="text-pi-emerald" />}
          title="AI Learning Curve"
          sub="Model accuracy improving over time as more data is consumed — each point is one retraining run"
        />
        {!learningCurve.data?.sports?.length ? (
          <EmptyChart message="Learning curve appears after the first model retraining. Auto-retrains every Sunday at 03:00 UTC." />
        ) : (
          <div className="grid md:grid-cols-2 gap-5">
            {learningCurve.data.sports.slice(0, 6).map(sport => {
              const pts = learningCurve.data!.data[sport] ?? [];
              if (!pts.length) return null;
              return (
                <div key={sport}>
                  <p className="text-xs font-semibold text-pi-primary mb-2 flex items-center gap-2">
                    <span>{SPORT_ICONS[sport] ?? "🏆"}</span>
                    {sport.replace("_", " ").replace(/\b\w/g, c => c.toUpperCase())}
                    <span className="text-pi-muted font-normal">({pts.length} runs)</span>
                  </p>
                  <ResponsiveContainer width="100%" height={140}>
                    <ComposedChart data={pts} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                      <XAxis dataKey="trained_at" tickFormatter={v => v.slice(5, 10)} tick={{ fontSize: 9, fill: C.muted }} />
                      <YAxis
                        tickFormatter={v => `${(v * 100).toFixed(0)}%`}
                        tick={{ fontSize: 9, fill: C.muted }}
                        domain={[0.3, 1]}
                      />
                      <Tooltip
                        {...TP}
                        formatter={(v: ValueType | undefined, name: NameType | undefined) => [
                          `${((v as number ?? 0) * 100).toFixed(1)}%`,
                          name === "accuracy_est" ? "Est. Accuracy" : String(name),
                        ]}
                        labelFormatter={(l) => `Trained ${l}`}
                      />
                      <ReferenceLine y={0.55} stroke={C.amber} strokeDasharray="4 4" />
                      <Area dataKey="accuracy_est" stroke={C.emerald} fill={C.emerald} fillOpacity={0.1} strokeWidth={2} dot={{ fill: C.emerald, r: 2 }} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── 4. Accuracy + ROI timelines ─────────────────────────────── */}
      <div className="grid md:grid-cols-2 gap-5 mb-6">

        {/* Accuracy timeline */}
        <div className="card p-5">
          <SectionHeader
            icon={<Target size={14} className="text-pi-emerald" />}
            title="Model Accuracy Over Time"
            sub="14-day rolling accuracy on PLAY picks"
          />
          {tl.length === 0 ? (
            <EmptyChart message="No resolved picks yet. Accuracy chart appears once picks resolve after matches finish." />
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={tl} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 10, fill: C.muted }} />
                <YAxis tickFormatter={v => `${(v * 100).toFixed(0)}%`} tick={{ fontSize: 10, fill: C.muted }} domain={[0.3, 1]} />
                <Tooltip
                  {...TP}
                  formatter={fmtPctNamed("Daily Acc")}
                  labelFormatter={fmtLabelShort}
                />
                <ReferenceLine y={0.55} stroke={C.amber} strokeDasharray="4 4" label={{ value: "55%", fill: C.amber, fontSize: 10 }} />
                <Bar dataKey="accuracy" fill={C.indigoL} opacity={0.25} radius={[2,2,0,0]} />
                <Line dataKey="rolling_accuracy" stroke={C.emerald} strokeWidth={2.5} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* ROI timeline */}
        <div className="card p-5">
          <SectionHeader
            icon={<TrendingUp size={14} className="text-pi-amber" />}
            title="Cumulative ROI (Units)"
            sub="Running profit/loss on all PLAY bets at 1 unit stake"
          />
          {rl.length === 0 ? (
            <EmptyChart message="No resolved picks yet. ROI tracker starts once picks are settled." />
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={rl} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="roiGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor={C.emerald} stopOpacity={0.3} />
                    <stop offset="95%" stopColor={C.emerald} stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 10, fill: C.muted }} />
                <YAxis tick={{ fontSize: 10, fill: C.muted }} />
                <Tooltip
                  {...TP}
                  formatter={fmtRoi}
                  labelFormatter={fmtLabelShort}
                />
                <ReferenceLine y={0} stroke={C.muted} strokeDasharray="3 3" />
                <Area
                  dataKey="cumulative_roi"
                  stroke={C.emerald}
                  fill="url(#roiGrad)"
                  strokeWidth={2.5}
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── 3. Market + League breakdown ────────────────────────────── */}
      <div className="grid md:grid-cols-2 gap-5 mb-6">

        {/* Market performance */}
        <div className="card p-5">
          <SectionHeader
            icon={<BarChart2 size={14} className="text-pi-indigo-light" />}
            title="Accuracy by Market"
            sub="1X2 result, Over/Under, BTTS"
          />
          {!markets.data?.data?.length ? (
            <EmptyChart message="No resolved picks by market yet." />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={markets.data.data} layout="vertical" margin={{ left: 60, right: 30, top: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={C.border} horizontal={false} />
                  <XAxis type="number" tickFormatter={v => `${(v*100).toFixed(0)}%`} tick={{ fontSize: 10, fill: C.muted }} domain={[0, 1]} />
                  <YAxis type="category" dataKey="market" tick={{ fontSize: 11, fill: "#e2e8f0" }} width={55} />
                  <Tooltip
                    {...TP}
                    formatter={fmtNum}
                  />
                  <ReferenceLine x={0.55} stroke={C.amber} strokeDasharray="4 4" />
                  <Bar dataKey="accuracy" radius={[0,4,4,0]}>
                    {markets.data.data.map((entry, i) => (
                      <Cell
                        key={i}
                        fill={(entry.accuracy ?? 0) >= 0.55 ? C.emerald : (entry.accuracy ?? 0) >= 0.45 ? C.amber : C.rose}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <div className="grid grid-cols-3 gap-2 mt-3">
                {markets.data.data.map(m => (
                  <div key={m.market} className="text-center">
                    <p className="text-[10px] text-pi-muted">{m.market}</p>
                    <p className="font-bold text-pi-primary text-sm">{pct(m.accuracy)}</p>
                    <p className="text-[10px] text-pi-muted">{m.picks} picks · {m.roi > 0 ? "+" : ""}{m.roi.toFixed(1)}u</p>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* League performance */}
        <div className="card p-5">
          <SectionHeader
            icon={<Activity size={14} className="text-pi-sky" />}
            title="Accuracy by League"
            sub="Top competitions by pick volume"
          />
          {!leagues.data?.data?.length ? (
            <EmptyChart message="No resolved picks by league yet." />
          ) : (
            <div className="space-y-1.5 max-h-56 overflow-y-auto pr-1">
              {leagues.data.data.map((l, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-[11px] text-pi-secondary w-36 truncate shrink-0">{l.competition}</span>
                  <div className="flex-1 h-2 bg-pi-surface rounded-full overflow-hidden">
                    <div
                      className="h-2 rounded-full transition-all"
                      style={{
                        width: `${Math.min(100, (l.accuracy ?? 0) * 100)}%`,
                        background: (l.accuracy ?? 0) >= 0.55 ? C.emerald : (l.accuracy ?? 0) >= 0.45 ? C.amber : C.rose,
                      }}
                    />
                  </div>
                  <span className="text-[11px] font-semibold w-10 text-right"
                    style={{ color: (l.accuracy ?? 0) >= 0.55 ? C.emerald : (l.accuracy ?? 0) >= 0.45 ? C.amber : C.rose }}>
                    {pct(l.accuracy, 0)}
                  </span>
                  <span className="text-[10px] text-pi-muted w-8 text-right">{l.picks}p</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── 4. Calibration curve ────────────────────────────────────── */}
      <div className="card p-5 mb-6">
        <SectionHeader
          icon={<FlaskConical size={14} className="text-pi-violet" />}
          title="Probability Calibration Curve"
          sub="Does a predicted 70% probability actually win 70% of the time? The diagonal = perfect calibration."
        />
        {!calibration.data?.data?.length ? (
          <EmptyChart message="Calibration data builds up as picks are resolved. Needs 100+ resolved picks across all probability ranges." />
        ) : (
          <div className="grid md:grid-cols-3 gap-4">
            <div className="md:col-span-2">
              <ResponsiveContainer width="100%" height={220}>
                <ComposedChart data={calibration.data.data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                  <XAxis
                    dataKey="bucket_mid"
                    tickFormatter={v => `${(v*100).toFixed(0)}%`}
                    tick={{ fontSize: 10, fill: C.muted }}
                    label={{ value: "Predicted probability", position: "insideBottom", offset: -2, fontSize: 10, fill: C.muted }}
                  />
                  <YAxis
                    tickFormatter={v => `${(v*100).toFixed(0)}%`}
                    tick={{ fontSize: 10, fill: C.muted }}
                    domain={[0, 1]}
                    label={{ value: "Actual win rate", angle: -90, position: "insideLeft", offset: 25, fontSize: 10, fill: C.muted }}
                  />
                  <Tooltip
                    {...TP}
                    formatter={fmtPctNamed("Predicted avg")}
                  />
                  {/* Perfect calibration diagonal */}
                  <ReferenceLine
                    segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]}
                    stroke={C.muted}
                    strokeDasharray="6 3"
                    label={{ value: "Perfect", fill: C.muted, fontSize: 9 }}
                  />
                  <Bar dataKey="actual_rate" fill={C.indigo} opacity={0.5} radius={[3,3,0,0]} />
                  <Line dataKey="predicted_avg" stroke={C.amber} strokeWidth={2} dot={{ fill: C.amber, r: 3 }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="space-y-2">
              <p className="text-xs font-semibold text-pi-primary mb-2">Reading this chart</p>
              <div className="text-xs text-pi-secondary space-y-2 leading-relaxed">
                <p><span className="text-pi-amber font-semibold">Orange line</span> = what the model predicted.</p>
                <p><span style={{ color: C.indigo }} className="font-semibold">Purple bars</span> = what actually happened.</p>
                <p>If bars align with the dashed diagonal, the model is well-calibrated — a 65% prediction genuinely wins 65% of the time.</p>
                <p>Bars above diagonal = model is underconfident (reality better than expected).</p>
                <p>Bars below diagonal = model is overconfident (it overestimates its certainty).</p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── 5. Feature importance ───────────────────────────────────── */}
      <div className="card p-5 mb-6">
        <SectionHeader
          icon={<Cpu size={14} className="text-pi-indigo-light" />}
          title="Feature Importance (XGBoost)"
          sub="Which signals drive predictions most — extracted from live trained model"
        />
        {features.isLoading ? (
          <div className="flex justify-center py-8"><Spinner size={28} /></div>
        ) : !features.data?.data?.length ? (
          <EmptyChart message={features.data?.status === "no_model" ? "No trained model found. Run a retrain first." : "Feature importance becomes available after the first training run."} />
        ) : (
          <div className="grid md:grid-cols-5 gap-4">
            <div className="md:col-span-3">
              <ResponsiveContainer width="100%" height={320}>
                <BarChart
                  data={features.data.data.slice(0, 15)}
                  layout="vertical"
                  margin={{ left: 155, right: 30, top: 4, bottom: 4 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke={C.border} horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 9, fill: C.muted }} />
                  <YAxis type="category" dataKey="label" tick={{ fontSize: 10, fill: "#e2e8f0" }} width={150} />
                  <Tooltip
                    {...TP}
                    formatter={((v: ValueType | undefined, _: NameType | undefined, props: { payload?: { group?: string } }) => [
                      ((v as number) ?? 0).toFixed(5),
                      `${props.payload?.group ?? ""} feature`,
                    ]) as Fmt}
                  />
                  <Bar dataKey="importance" radius={[0,4,4,0]}>
                    {features.data.data.slice(0, 15).map((f, i) => (
                      <Cell key={i} fill={GROUP_COLORS[f.group] ?? C.indigoL} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="md:col-span-2">
              <p className="text-xs font-semibold text-pi-primary mb-3">Feature groups</p>
              <div className="space-y-1.5">
                {Object.entries(GROUP_COLORS).map(([group, color]) => {
                  const hasFeatures = features.data!.data.some(f => f.group === group);
                  if (!hasFeatures) return null;
                  const totalImp = features.data!.data
                    .filter(f => f.group === group)
                    .reduce((s, f) => s + f.importance, 0);
                  return (
                    <div key={group} className="flex items-center gap-2">
                      <div className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: color }} />
                      <span className="text-[11px] text-pi-secondary flex-1">{group}</span>
                      <div className="w-16 h-1.5 bg-pi-surface rounded-full overflow-hidden">
                        <div className="h-1.5 rounded-full" style={{ background: color, width: `${Math.min(100, totalImp * 800)}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
              <p className="text-[11px] text-pi-muted mt-3 leading-relaxed">
                Market Odds and Elo tend to dominate early training. As more data accumulates, Shot/xG and Dixon-Coles features grow in influence.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* ── 6. Confidence histogram + PLAY/SKIP split ───────────────── */}
      <div className="grid md:grid-cols-2 gap-5 mb-6">

        {/* Histogram */}
        <div className="card p-5">
          <SectionHeader
            icon={<BarChart2 size={14} className="text-pi-sky" />}
            title="Confidence Distribution"
            sub="Score spread across all PLAY decisions"
          />
          {!histogram.data?.histogram?.some(b => b.count > 0) ? (
            <EmptyChart message="No PLAY decisions found yet." />
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={histogram.data!.histogram} margin={{ left: -20, right: 4, top: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                <XAxis dataKey="range" tick={{ fontSize: 9, fill: C.muted }} />
                <YAxis tick={{ fontSize: 10, fill: C.muted }} />
                <Tooltip {...TP} />
                <Bar dataKey="count" radius={[3,3,0,0]}>
                  {histogram.data!.histogram.map((b, i) => {
                    const mid = parseInt(b.range);
                    return (
                      <Cell
                        key={i}
                        fill={mid >= 75 ? C.emerald : mid >= 65 ? C.amber : C.indigo}
                      />
                    );
                  })}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* PLAY/SKIP donut */}
        <div className="card p-5">
          <SectionHeader
            icon={<Target size={14} className="text-pi-emerald" />}
            title="PLAY vs SKIP Ratio"
            sub="Decision selectivity — lower PLAY rate = more selective model"
          />
          {histogram.data == null ? (
            <EmptyChart message="No decision data yet." />
          ) : (
            <div className="flex items-center gap-6 justify-center h-40">
              <PieChart width={140} height={140}>
                <Pie
                  data={[
                    { name: "PLAY", value: histogram.data.play_count },
                    { name: "SKIP", value: histogram.data.skip_count },
                  ]}
                  cx={65} cy={65} innerRadius={42} outerRadius={65}
                  paddingAngle={3} dataKey="value"
                >
                  <Cell fill={C.emerald} />
                  <Cell fill={C.border} />
                </Pie>
                <Tooltip {...TP} />
              </PieChart>
              <div className="space-y-3">
                <div>
                  <p className="text-xs text-pi-muted">PLAY</p>
                  <p className="text-xl font-bold text-pi-emerald">{num(histogram.data.play_count)}</p>
                  <p className="text-[11px] text-pi-muted">{pct(histogram.data.play_rate)}</p>
                </div>
                <div>
                  <p className="text-xs text-pi-muted">SKIP</p>
                  <p className="text-xl font-bold" style={{ color: C.muted }}>{num(histogram.data.skip_count)}</p>
                  <p className="text-[11px] text-pi-muted">{pct(histogram.data.play_rate != null ? 1 - histogram.data.play_rate : null)}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── 7. Intelligence signals feed ────────────────────────────── */}
      <div className="card p-5 mb-6">
        <SectionHeader
          icon={<Zap size={14} className="text-pi-amber" />}
          title="Intelligence Signals Feed"
          sub="Injury, suspension and form signals scraped and extracted in real time"
        />
        <div className="grid md:grid-cols-2 gap-4">

          {/* Signal volume chart */}
          <div>
            <p className="text-xs text-slate-400 mb-3 font-medium">Signal volume — last 7 days</p>
            {!signals.data?.daily?.length ? (
              <EmptyChart message="No signals in the last 7 days." />
            ) : (
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={signals.data.daily} margin={{ left: -20, right: 4, top: 4, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                  <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 10, fill: C.muted }} />
                  <YAxis tick={{ fontSize: 10, fill: C.muted }} />
                  <Tooltip {...TP} />
                  {["injury", "suspension", "return", "morale", "lineup"].map((type, i) => (
                    <Bar key={type} dataKey={type} stackId="a" fill={[C.rose, C.amber, C.emerald, C.sky, C.violet][i]} radius={i === 4 ? [3,3,0,0] : undefined} />
                  ))}
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Live signal feed */}
          <div>
            <p className="text-xs text-slate-400 mb-3 font-medium">Recent signals</p>
            {!signals.data?.feed?.length ? (
              <p className="text-sm text-slate-400 py-4 text-center">No recent signals</p>
            ) : (
              <div className="space-y-1.5 max-h-44 overflow-y-auto pr-1">
                {signals.data.feed.map(sig => {
                  const icons: Record<string, React.ReactNode> = {
                    injury:     <AlertCircle size={16} className="text-rose-400" />,
                    suspension: <span className="inline-block w-4 h-4 rounded-sm bg-rose-500 text-white text-[10px] font-bold flex items-center justify-center leading-none">R</span>,
                    return:     <CheckCircle2 size={16} className="text-emerald-400" />,
                    morale:     <Activity size={16} className="text-sky-400" />,
                    lineup:     <Cpu size={16} className="text-violet-400" />,
                  };
                  const impColor = sig.impact < -0.5 ? C.rose : sig.impact < 0 ? C.amber : C.emerald;
                  return (
                    <div key={sig.id} className="flex items-start gap-3 p-3 rounded-lg" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(99,120,180,0.2)" }}>
                      <span className="shrink-0 mt-0.5">{icons[sig.type] ?? <Activity size={16} className="text-slate-400" />}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-white truncate">{sig.entity || sig.team}</p>
                        <p className="text-xs text-slate-400">{sig.team} · {sig.type}</p>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="text-sm font-bold" style={{ color: impColor }}>
                          {sig.impact > 0 ? "+" : ""}{sig.impact.toFixed(2)}
                        </p>
                        <p className="text-xs text-slate-400">{timeAgo(sig.time)}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── 8a. Model Training Status ───────────────────────────────── */}
      <div className="card p-5 mb-6">
        <div className="flex items-start justify-between mb-5">
          <SectionHeader
            icon={<Cpu size={14} className="text-pi-emerald" />}
            title="Model Training Status"
            sub="Live status of trained models across all sports — auto-retrains every Sunday at 03:00 UTC"
          />
          {trainProg.data?.is_training && (
            <span className="flex items-center gap-1.5 text-[11px] text-pi-emerald font-semibold animate-pulse shrink-0">
              <span className="w-2 h-2 rounded-full bg-pi-emerald inline-block" />
              Training…
            </span>
          )}
        </div>

        {/* Overall live progress bar — shown while training (or just finished) */}
        {trainProg.data && (trainProg.data.is_training || trainProg.data.overall_pct > 0) && (
          <div className="mb-5">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[11px] text-pi-secondary font-medium">
                {trainProg.data.is_training
                  ? `Training ${trainProg.data.current_sport?.replace(/_/g, " ") ?? "…"}${trainProg.data.current_market ? ` · ${trainProg.data.current_market}` : ""}`
                  : "Training complete"}
              </span>
              <span className="text-[11px] font-bold text-white tabular-nums">
                {trainProg.data.overall_pct.toFixed(0)}%
              </span>
            </div>
            <div className="h-2.5 rounded-full bg-pi-surface overflow-hidden">
              <div
                className="h-2.5 rounded-full transition-all duration-500"
                style={{
                  width: `${trainProg.data.overall_pct}%`,
                  background: trainProg.data.is_training
                    ? `linear-gradient(90deg, ${C.indigo}, ${C.emerald})`
                    : C.emerald,
                  boxShadow: trainProg.data.is_training ? `0 0 8px ${C.indigo}80` : "none",
                }}
              />
            </div>
            {trainProg.data.is_training && (
              <p className="text-[10px] text-pi-muted mt-1">
                {Object.values(trainProg.data.sports as Record<string, any>).filter(s => s.status === "done").length} of 10 sports complete
              </p>
            )}
          </div>
        )}

        {health.isLoading || sportBreakdown.isLoading ? (
          <div className="flex justify-center py-8"><Spinner size={28} /></div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
              {["football","basketball","tennis","baseball","american_football","ice_hockey","cricket","rugby","handball","volleyball"].map(sport => {
                const modelFile   = health.data?.model_files?.find((m: any) => m.sport === sport);
                const sportRow    = sportBreakdown.data?.data?.find((s: SportRow) => s.sport === sport);
                const liveSport   = (trainProg.data?.sports as Record<string, any> | undefined)?.[sport];

                // Live state overrides static when actively training
                const isLiveTraining = liveSport?.status === "training";
                const isLiveDone     = liveSport?.status === "done";
                const livePct        = liveSport?.pct ?? 0;
                const liveMarketsDone = liveSport?.markets_done ?? 0;
                const liveMarketsTotal = liveSport?.markets_total ?? 7;

                const isTrained   = isLiveDone || !!modelFile;
                const lastTrained = modelFile?.modified ?? sportRow?.last_trained;
                const trainingRows = liveSport?.rows ?? sportRow?.training_rows ?? 0;
                const modelAcc    = isLiveDone ? liveSport?.accuracy : sportRow?.model_accuracy;

                const daysSince = lastTrained
                  ? (Date.now() - new Date(lastTrained).getTime()) / 86_400_000
                  : Infinity;
                const isStale = isTrained && !isLiveTraining && !isLiveDone && daysSince > 7;

                const statusColor = isLiveTraining ? C.indigo
                  : !isTrained   ? C.rose
                  : isStale      ? C.amber
                  : C.emerald;
                const statusLabel = isLiveTraining ? "Training"
                  : !isTrained   ? "No Model"
                  : isStale      ? "Stale"
                  : "Trained";
                const statusIcon  = isLiveTraining ? "⟳"
                  : !isTrained   ? "✕"
                  : isStale      ? "!"
                  : "✓";

                return (
                  <div key={sport} className="rounded-xl p-3 flex flex-col gap-1"
                    style={{
                      background: isLiveTraining ? `${C.indigo}10` : "rgba(255,255,255,0.03)",
                      border: `1px solid ${statusColor}33`,
                    }}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-lg">{SPORT_ICONS[sport] ?? "🏆"}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-bold ${isLiveTraining ? "animate-pulse" : ""}`}
                        style={{ background: `${statusColor}20`, color: statusColor }}>
                        {statusIcon} {statusLabel}
                      </span>
                    </div>
                    <p className="text-[11px] font-semibold text-white capitalize leading-tight">
                      {sport.replace(/_/g, " ")}
                    </p>

                    {/* Live training progress bar */}
                    {isLiveTraining ? (
                      <>
                        <p className="text-[10px] text-pi-muted">{trainingRows.toLocaleString()} rows</p>
                        <p className="text-[10px] text-pi-secondary">
                          Market {liveMarketsDone}/{liveMarketsTotal}
                          {trainProg.data?.current_sport === sport && trainProg.data?.current_market
                            ? ` · ${trainProg.data.current_market}`
                            : ""}
                        </p>
                        <div className="mt-1.5 h-2 rounded-full bg-pi-surface overflow-hidden">
                          <div
                            className="h-2 rounded-full transition-all duration-500"
                            style={{
                              width: `${livePct}%`,
                              background: `linear-gradient(90deg, ${C.indigo}, ${C.violet})`,
                              boxShadow: `0 0 6px ${C.indigo}80`,
                            }}
                          />
                        </div>
                        <p className="text-[10px] font-bold tabular-nums" style={{ color: C.indigo }}>
                          {livePct.toFixed(0)}%
                        </p>
                      </>
                    ) : isTrained ? (
                      <>
                        <p className="text-[10px] text-pi-muted">{timeAgo(lastTrained)}</p>
                        <p className="text-[10px] text-pi-secondary">{trainingRows.toLocaleString()} rows</p>
                        {modelAcc != null && (
                          <p className="text-[10px] font-bold mt-0.5" style={{ color: accColor(modelAcc) }}>
                            {pct(modelAcc)} acc
                          </p>
                        )}
                        <div className="mt-1.5 h-1 rounded-full bg-pi-surface overflow-hidden">
                          <div className="h-1 rounded-full transition-all"
                            style={{
                              width: `${Math.min(100, (trainingRows / 50_000) * 100)}%`,
                              background: trainingRows >= 40_000 ? C.emerald : trainingRows >= 10_000 ? C.amber : C.indigo,
                            }}
                          />
                        </div>
                      </>
                    ) : (
                      <p className="text-[10px] text-pi-muted mt-1 leading-snug">Needs training data</p>
                    )}
                  </div>
                );
              })}
            </div>
            <p className="text-[10px] text-pi-muted mt-3 leading-relaxed">
              Stale = model not retrained in 7+ days. Data bar = training rows vs 50k target.
              {" "}Training runs in the background and does not block the app.
            </p>
          </>
        )}
      </div>

      {/* ── 8b. Model health + training log ─────────────────────────── */}
      <div className="grid md:grid-cols-2 gap-5 mb-6">

        {/* Model files */}
        <div className="card p-5">
          <SectionHeader
            icon={<Database size={14} className="text-pi-violet" />}
            title="Model Files"
            sub="Trained model artefacts on disk"
          />
          {!health.data?.model_files?.length ? (
            <div className="text-sm text-slate-400 space-y-3">
              <p>No trained models found on disk.</p>
              <button
                onClick={() => retrain.mutate()}
                disabled={retrain.isPending}
                className="btn-primary text-xs flex items-center gap-1.5"
              >
                <RefreshCw size={11} className={retrain.isPending ? "animate-spin" : ""} />
                {retrain.isPending ? "Training…" : "Train First Model"}
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              {health.data.model_files.map((m: any, i: number) => (
                <div key={i} className="flex items-center gap-3 py-2 border-b border-pi-border/20 last:border-0">
                  <span className="text-lg">{SPORT_ICONS[m.sport as string] ?? "🏆"}</span>
                  <div className="flex-1">
                    <p className="text-sm font-semibold text-white capitalize">{m.sport}</p>
                    <p className="text-xs text-slate-400">{m.size_kb} KB · updated {timeAgo(m.modified)}</p>
                  </div>
                  <CheckCircle2 size={14} className="text-pi-emerald" />
                </div>
              ))}
              <p className="text-xs text-slate-400 pt-2">
                {health.data.features_count} features · data up to{" "}
                {health.data.latest_match_date ? health.data.latest_match_date.slice(0, 10) : "—"}
              </p>
            </div>
          )}
        </div>

        {/* Training history */}
        <div className="card p-5">
          <SectionHeader
            icon={<Brain size={14} className="text-pi-indigo-light" />}
            title="Training History"
            sub="Each row = one retraining run on accumulated data"
          />
          {!health.data?.training_history?.length ? (
            <p className="text-xs text-pi-muted">No training runs yet. Model auto-retrains every Sunday.</p>
          ) : (
            <div className="space-y-1.5 max-h-52 overflow-y-auto pr-1">
              {health.data.training_history.map((l: any) => {
                const acc = l.accuracy as Record<string, number>;
                const resultAcc = acc?.result;
                return (
                  <div key={l.id} className="flex items-center gap-2 py-1.5 border-b border-pi-border/20 last:border-0">
                    <span className="text-sm">{SPORT_ICONS[l.sport as string] ?? "🏆"}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-medium text-pi-primary capitalize">{l.sport}</span>
                        <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-semibold ${
                          l.status === "trained" ? "bg-emerald-500/15 text-emerald-400" :
                          l.status === "skipped" ? "bg-amber-500/15 text-amber-400" :
                          "bg-rose-500/10 text-rose-400"
                        }`}>{l.status}</span>
                      </div>
                      <p className="text-[10px] text-pi-muted">
                        {l.training_rows.toLocaleString()} rows · {new Date(l.trained_at).toLocaleDateString()}
                      </p>
                    </div>
                    {resultAcc != null && (
                      <div className="text-right shrink-0">
                        <p className="text-[10px] text-pi-muted">log-loss</p>
                        <p className="text-xs font-semibold text-pi-primary">{resultAcc.toFixed(3)}</p>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ── 9. Automation schedule ──────────────────────────────────── */}
      <div className="card p-5">
        <SectionHeader
          icon={<Clock size={14} className="text-pi-muted" />}
          title="Automation Schedule"
          sub="Every background job and its cadence"
        />
        <div className="grid md:grid-cols-2 gap-2">
          {[
            { label: "Live scores (all sports)",    freq: "60s live / 5 min idle",  dot: "bg-pi-emerald",      note: "Sofascore primary · ESPN fallback · adaptive rate" },
            { label: "Clubs standings + fixtures",  freq: "Every 5 minutes",        dot: "bg-pi-emerald",      note: "All leagues · DB-only reads for users" },
            { label: "Clubs news + top scorers",    freq: "Every 30 minutes",       dot: "bg-pi-sky",          note: "ESPN · all supported leagues" },
            { label: "Intelligence signals",        freq: "Every 30 minutes",       dot: "bg-pi-amber",        note: "Gemini NLP extraction from news" },
            { label: "Pre-match lineups",           freq: "Every 1 hour",           dot: "bg-pi-sky",          note: "API-Football · PLAY picks only" },
            { label: "ML predictions",              freq: "Every 3 hours",          dot: "bg-pi-indigo-light", note: "All upcoming matches · all sports" },
            { label: "News + articles",             freq: "Every 3 hours",          dot: "bg-pi-sky",          note: "Gemini rewrite pipeline" },
            { label: "Odds refresh",                freq: "Every 6 hours",          dot: "bg-pi-sky",          note: "Sportybet + Odds API" },
            { label: "Match result resolution",     freq: "Every 2 hours",          dot: "bg-pi-amber",        note: "Updates PerformanceLog" },
            { label: "Multi-sport data ingestion",  freq: "Daily 02:00 UTC",        dot: "bg-pi-violet",       note: "Sofascore + ESPN · all 10 sports · feeds ML training" },
            { label: "Daily picks + email",         freq: "Daily 08:00 UTC",        dot: "bg-pi-violet",       note: "Decision engine run" },
            { label: "Model retraining (all sports)",freq: "Weekly Sunday 03:00 UTC",dot: "bg-pi-indigo-light", note: "Full retrain after daily ingest completes" },
          ].map(({ label, freq, dot, note }) => (
            <div key={label} className="flex items-start gap-3 py-2.5 border-b last:border-0" style={{ borderColor: "rgba(99,120,180,0.15)" }}>
              <span className={`w-2.5 h-2.5 rounded-full mt-1 shrink-0 ${dot}`} />
              <div className="flex-1 min-w-0">
                <span className="text-sm font-medium text-white">{label}</span>
                <p className="text-xs text-slate-400">{note}</p>
              </div>
              <span className="text-xs text-indigo-400 font-semibold shrink-0 text-right">{freq}</span>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}
