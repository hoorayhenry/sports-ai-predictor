import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Zap, TrendingUp, Target, Shield } from "lucide-react";
import { fetchMatch } from "../api/client";
import Spinner from "../components/Spinner";
import { formatDate, outcomeLabel, confidenceColor, resultLabel } from "../utils/format";
import type { Odds, PredictionMarkets, PredictionValueBet } from "../api/types";

// ─── helpers ────────────────────────────────────────────────────────────────

function p(v: number | undefined | null): string {
  if (v == null) return "—";
  return `${Math.round(v * 100)}%`;
}

function numPct(v: number | undefined | null): number {
  return v == null ? 0 : Math.round(v * 100);
}

const CONF_COLOR: Record<string, string> = {
  high: "text-green-400",
  medium: "text-yellow-400",
  low: "text-orange-400",
};

// ─── sub-components ──────────────────────────────────────────────────────────

function ProbRow({ label, prob, color }: { label: string; prob: number; color: string }) {
  const colors: Record<string, string> = {
    sky: "bg-sky-500",
    slate: "bg-slate-400",
    orange: "bg-orange-500",
  };
  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-slate-300 w-28 truncate">{label}</span>
      <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-2 rounded-full ${colors[color] || "bg-sky-500"} transition-all`}
          style={{ width: `${Math.round(prob * 100)}%` }}
        />
      </div>
      <span className="text-sm font-semibold text-white w-10 text-right">
        {Math.round(prob * 100)}%
      </span>
    </div>
  );
}

function StatTile({
  label,
  value,
  bar = false,
  color = "purple",
}: {
  label: string;
  value: number | null | undefined;
  bar?: boolean;
  color?: string;
}) {
  const barColors: Record<string, string> = {
    purple: "bg-purple-500",
    green: "bg-green-500",
    sky: "bg-sky-500",
    orange: "bg-orange-500",
    teal: "bg-teal-500",
    pink: "bg-pink-500",
    yellow: "bg-yellow-500",
    indigo: "bg-indigo-500",
  };
  return (
    <div className="bg-[#0f172a] rounded-xl p-3">
      <p className="text-xs text-slate-400 mb-1 leading-tight">{label}</p>
      <p className="text-xl font-bold text-white">{p(value)}</p>
      {bar && (
        <div className="h-1 rounded-full bg-slate-700 mt-2">
          <div
            className={`h-1 rounded-full ${barColors[color] || "bg-purple-500"}`}
            style={{ width: p(value) }}
          />
        </div>
      )}
    </div>
  );
}

function SectionHeader({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <span className="text-slate-400">{icon}</span>
      <h3 className="font-semibold font-display text-sm">{title}</h3>
    </div>
  );
}

function ValueBetRow({ vb }: { vb: PredictionValueBet }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-700/50 last:border-0">
      <div className="min-w-0">
        <p className="text-sm font-semibold text-white truncate">
          {outcomeLabel(vb.market, vb.outcome)}
        </p>
        <p className="text-xs text-slate-400">
          Model: {p(vb.prob)} · Kelly: {((vb.kelly) * 100).toFixed(1)}% bankroll
        </p>
      </div>
      <div className="text-right shrink-0 ml-3">
        <p className="text-yellow-300 font-bold">{vb.odds.toFixed(2)}</p>
        <p className={`text-xs font-semibold ${CONF_COLOR[vb.confidence] ?? "text-slate-400"}`}>
          EV +{(vb.ev * 100).toFixed(1)}%
        </p>
      </div>
    </div>
  );
}

function OddsTable({ title, odds }: { title: string; odds: Odds[] }) {
  const byBookmaker: Record<string, Odds[]> = {};
  for (const o of odds) {
    if (!byBookmaker[o.bookmaker]) byBookmaker[o.bookmaker] = [];
    const exists = byBookmaker[o.bookmaker].find((x) => x.outcome === o.outcome);
    if (!exists || exists.price < o.price) {
      byBookmaker[o.bookmaker] = byBookmaker[o.bookmaker].filter((x) => x.outcome !== o.outcome);
      byBookmaker[o.bookmaker].push(o);
    }
  }
  const outcomes = [...new Set(odds.map((o) => o.outcome))];
  const bookmakers = Object.keys(byBookmaker);
  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-700/50">
        <h3 className="font-semibold text-sm">{title}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="text-left px-4 py-2 text-slate-500 font-medium text-xs">Bookmaker</th>
              {outcomes.map((o) => (
                <th key={o} className="text-right px-3 py-2 text-slate-500 font-medium text-xs capitalize">
                  {o}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bookmakers.map((bm, i) => (
              <tr key={bm} className={i % 2 === 0 ? "bg-[#1a2744]/30" : ""}>
                <td className="px-4 py-2.5 text-slate-300 capitalize font-medium text-xs">{bm}</td>
                {outcomes.map((out) => {
                  const entry = byBookmaker[bm]?.find((o) => o.outcome === out);
                  return (
                    <td key={out} className="px-3 py-2.5 text-right font-semibold">
                      {entry ? (
                        <span className="text-white">{entry.price.toFixed(2)}</span>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── main page ───────────────────────────────────────────────────────────────

type Tab = "overview" | "markets" | "scores";

export default function MatchDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState<Tab>("overview");

  const { data: match, isLoading } = useQuery({
    queryKey: ["match", id],
    queryFn: () => fetchMatch(Number(id)),
    enabled: !!id,
  });

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <Spinner size={48} />
      </div>
    );
  }

  if (!match) {
    return (
      <div className="flex justify-center items-center min-h-screen text-slate-400">
        Match not found.
      </div>
    );
  }

  const pred = match.prediction;
  const m = pred?.markets as PredictionMarkets | null | undefined;
  const h2hOdds = match.odds.filter((o) => o.market === "h2h");
  const totalsOdds = match.odds.filter((o) => o.market === "totals");
  const bttsOdds = match.odds.filter((o) => o.market === "btts");
  const valueBets = m?.value_bets ?? [];
  const topScores = m?.top_correct_scores ?? [];
  const hasAdvanced = m && (
    m.double_chance_1x != null ||
    m.dnb_home != null ||
    m.home_win_to_nil != null ||
    m.home_clean_sheet != null
  );

  const TABS: { key: Tab; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "markets", label: "Markets" },
    { key: "scores", label: "Correct Scores" },
  ];

  return (
    <div className="min-h-screen pb-20 md:pb-6">
      {/* Top bar */}
      <div className="sticky top-0 z-10 navbar-glass px-4 py-3 flex items-center gap-3">
        <Link to="/" className="text-slate-400 hover:text-white transition-colors">
          <ArrowLeft size={20} />
        </Link>
        <div className="min-w-0">
          <p className="text-xs text-slate-500 truncate">
            {match.sport_icon} {match.competition}
          </p>
          <p className="text-sm font-semibold truncate">
            {match.home_team} vs {match.away_team}
          </p>
        </div>
        <p className="ml-auto text-xs text-slate-500 shrink-0">{formatDate(match.match_date)}</p>
      </div>

      <div className="px-4 pt-6 space-y-4">
        {/* Scoreboard */}
        <div className="card p-6 text-center">
          {match.status === "finished" && match.home_score != null ? (
            <>
              <div className="text-5xl font-bold mb-2">
                {match.home_score} – {match.away_score}
              </div>
              <p className="text-slate-400 text-sm">{resultLabel(match.result)}</p>
            </>
          ) : (
            <p className="text-slate-400 text-sm uppercase tracking-wider">{match.status}</p>
          )}
          <div className="flex justify-between items-start mt-4">
            <div className="flex-1 text-left">
              <p className="font-bold text-lg">{match.home_team}</p>
              <p className="text-xs text-slate-500">ELO {Math.round(match.home_elo)}</p>
            </div>
            <div className="text-slate-600 font-bold">VS</div>
            <div className="flex-1 text-right">
              <p className="font-bold text-lg">{match.away_team}</p>
              <p className="text-xs text-slate-500">ELO {Math.round(match.away_elo)}</p>
            </div>
          </div>

          {/* xG row */}
          {m && (m.exp_home_goals != null || m.exp_away_goals != null) && (
            <div className="flex justify-between items-center mt-4 px-2">
              <div className="text-left">
                <p className="text-xs text-slate-500">xG</p>
                <p className="text-lg font-bold text-sky-400">{m.exp_home_goals?.toFixed(2) ?? "—"}</p>
              </div>
              <p className="text-xs text-slate-600">Expected Goals</p>
              <div className="text-right">
                <p className="text-xs text-slate-500">xG</p>
                <p className="text-lg font-bold text-orange-400">{m.exp_away_goals?.toFixed(2) ?? "—"}</p>
              </div>
            </div>
          )}
        </div>

        {/* Tab bar — only show when prediction data is available */}
        {pred && (
          <div className="flex gap-1 bg-[#0f172a] rounded-xl p-1">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`flex-1 py-2 text-xs font-semibold rounded-lg transition-colors ${
                  tab === t.key
                    ? "bg-sky-600 text-white"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}

        {/* ── OVERVIEW TAB ─────────────────────────────────────────────── */}
        {tab === "overview" && pred && (
          <>
            {/* 1X2 + value badge */}
            <div className={`card p-4 ${pred.is_value_bet ? "border-yellow-500/40" : ""}`}>
              <div className="flex items-center gap-2 mb-4">
                <h3 className="font-semibold font-display">Prediction</h3>
                {pred.is_value_bet && (
                  <span className="flex items-center gap-1 bg-yellow-500/20 text-yellow-400 text-xs px-2 py-0.5 rounded-full font-semibold">
                    <Zap size={11} /> Value Bet
                  </span>
                )}
              </div>

              {/* 1X2 result bars */}
              {pred.home_win_prob != null && (
                <div className="space-y-2 mb-4">
                  <ProbRow label={match.home_team} prob={pred.home_win_prob} color="sky" />
                  {pred.draw_prob != null && pred.draw_prob > 0 && (
                    <ProbRow label="Draw" prob={pred.draw_prob} color="slate" />
                  )}
                  <ProbRow label={match.away_team} prob={pred.away_win_prob ?? 0} color="orange" />
                </div>
              )}

              {/* Goals markets grid */}
              <div className="grid grid-cols-2 gap-3 mb-4">
                {m?.over15 && (
                  <StatTile label="Over 1.5 Goals" value={m.over15.over} bar color="indigo" />
                )}
                {pred.over25_prob != null && (
                  <StatTile label="Over 2.5 Goals" value={pred.over25_prob} bar color="purple" />
                )}
                {m?.over35 && (
                  <StatTile label="Over 3.5 Goals" value={m.over35.over} bar color="pink" />
                )}
                {pred.btts_prob != null && (
                  <StatTile label="Both Teams Score" value={pred.btts_prob} bar color="green" />
                )}
              </div>

              {/* Top value bet */}
              {pred.is_value_bet && pred.value_outcome && (
                <div className="bg-yellow-500/5 border border-yellow-500/30 rounded-xl p-4">
                  <p className="text-xs text-yellow-400/70 font-semibold uppercase tracking-wider mb-2">
                    Top Value Bet
                  </p>
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="font-bold text-white">
                      {outcomeLabel(pred.value_market!, pred.value_outcome)}
                    </span>
                    <span className="text-xl font-bold text-yellow-300">
                      @ {pred.value_odds?.toFixed(2)}
                    </span>
                  </div>
                  <div className="flex gap-4 mt-2 text-sm">
                    <div>
                      <p className="text-slate-400 text-xs">Expected Value</p>
                      <p className="text-green-400 font-bold">
                        +{((pred.expected_value ?? 0) * 100).toFixed(1)}%
                      </p>
                    </div>
                    <div>
                      <p className="text-slate-400 text-xs">Kelly Stake</p>
                      <p className="text-sky-400 font-bold">
                        {((pred.kelly_stake ?? 0) * 100).toFixed(1)}% bankroll
                      </p>
                    </div>
                    {pred.confidence && (
                      <div className="ml-auto">
                        <p className="text-slate-400 text-xs">Confidence</p>
                        <p className={`font-bold ${confidenceColor(pred.confidence)}`}>
                          {pred.confidence.toUpperCase()}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* All value bets */}
            {valueBets.length > 1 && (
              <div className="card p-4">
                <SectionHeader icon={<Zap size={14} />} title={`All Value Bets (${valueBets.length})`} />
                {valueBets.map((vb, i) => (
                  <ValueBetRow key={i} vb={vb} />
                ))}
              </div>
            )}
          </>
        )}

        {/* ── MARKETS TAB ──────────────────────────────────────────────── */}
        {tab === "markets" && pred && m && (
          <>
            {/* Double Chance */}
            {(m.double_chance_1x != null || m.double_chance_x2 != null) && (
              <div className="card p-4">
                <SectionHeader icon={<TrendingUp size={14} />} title="Double Chance" />
                <div className="grid grid-cols-3 gap-3">
                  <StatTile label={`${match.home_team} or Draw`} value={m.double_chance_1x} bar color="sky" />
                  <StatTile label={`Draw or ${match.away_team}`} value={m.double_chance_x2} bar color="orange" />
                  <StatTile label={`${match.home_team} or ${match.away_team}`} value={m.double_chance_12} bar color="purple" />
                </div>
              </div>
            )}

            {/* Draw No Bet */}
            {(m.dnb_home != null || m.dnb_away != null) && (
              <div className="card p-4">
                <SectionHeader icon={<Target size={14} />} title="Draw No Bet" />
                <div className="grid grid-cols-2 gap-3">
                  <StatTile label={`${match.home_team} (DNB)`} value={m.dnb_home} bar color="sky" />
                  <StatTile label={`${match.away_team} (DNB)`} value={m.dnb_away} bar color="orange" />
                </div>
              </div>
            )}

            {/* Win to Nil */}
            {(m.home_win_to_nil != null || m.away_win_to_nil != null) && (
              <div className="card p-4">
                <SectionHeader icon={<Shield size={14} />} title="Win to Nil" />
                <div className="grid grid-cols-2 gap-3">
                  <StatTile label={`${match.home_team} Win to Nil`} value={m.home_win_to_nil} bar color="teal" />
                  <StatTile label={`${match.away_team} Win to Nil`} value={m.away_win_to_nil} bar color="teal" />
                </div>
              </div>
            )}

            {/* Clean Sheets */}
            {(m.home_clean_sheet != null || m.away_clean_sheet != null) && (
              <div className="card p-4">
                <SectionHeader icon={<Shield size={14} />} title="Clean Sheet" />
                <div className="grid grid-cols-2 gap-3">
                  <StatTile label={`${match.home_team} Clean Sheet`} value={m.home_clean_sheet} bar color="green" />
                  <StatTile label={`${match.away_team} Clean Sheet`} value={m.away_clean_sheet} bar color="green" />
                </div>
              </div>
            )}

            {/* BTTS + Result */}
            {(m.btts_home_win != null || m.btts_draw != null || m.btts_away_win != null) && (
              <div className="card p-4">
                <SectionHeader icon={<TrendingUp size={14} />} title="BTTS + Result" />
                <div className="grid grid-cols-3 gap-3">
                  <StatTile label={`BTTS + ${match.home_team} Win`} value={m.btts_home_win} bar color="sky" />
                  <StatTile label="BTTS + Draw" value={m.btts_draw} bar color="slate" />
                  <StatTile label={`BTTS + ${match.away_team} Win`} value={m.btts_away_win} bar color="orange" />
                </div>
              </div>
            )}

            {/* Asian Handicap */}
            {(m["ah_home_-0.5"] != null || m["ah_home_+0.5"] != null) && (
              <div className="card overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-700/50">
                  <h3 className="font-semibold text-sm">Asian Handicap</h3>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-700/50">
                      <th className="text-left px-4 py-2 text-slate-500 font-medium text-xs">Line</th>
                      <th className="text-right px-3 py-2 text-slate-500 font-medium text-xs">{match.home_team}</th>
                      <th className="text-right px-3 py-2 text-slate-500 font-medium text-xs">Push</th>
                      <th className="text-right px-3 py-2 text-slate-500 font-medium text-xs">{match.away_team}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(
                      [
                        ["-0.5", "ah_home_-0.5", null, "ah_away_-0.5"],
                        ["+0.5", "ah_home_+0.5", null, "ah_away_+0.5"],
                        ["-1.0", "ah_home_-1.0", "ah_push_-1.0", "ah_away_-1.0"],
                        ["+1.0", "ah_home_+1.0", "ah_push_+1.0", "ah_away_+1.0"],
                      ] as [string, string, string | null, string][]
                    )
                      .filter(([, hk]) => m[hk] != null)
                      .map(([line, hk, pk, ak], i) => (
                        <tr key={line} className={i % 2 === 0 ? "bg-[#1a2744]/30" : ""}>
                          <td className="px-4 py-2.5 text-slate-300 font-medium text-xs">{line}</td>
                          <td className="px-3 py-2.5 text-right font-semibold text-white text-xs">
                            {p(m[hk] as number)}
                          </td>
                          <td className="px-3 py-2.5 text-right text-slate-500 text-xs">
                            {pk ? p(m[pk] as number) : "—"}
                          </td>
                          <td className="px-3 py-2.5 text-right font-semibold text-white text-xs">
                            {p(m[ak] as number)}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Over/Under full grid */}
            {(m["over_1.5"] != null || m["over_3.5"] != null || m["over_4.5"] != null) && (
              <div className="card overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-700/50">
                  <h3 className="font-semibold text-sm">Over / Under — All Lines</h3>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-700/50">
                      <th className="text-left px-4 py-2 text-slate-500 font-medium text-xs">Goals</th>
                      <th className="text-right px-3 py-2 text-slate-500 font-medium text-xs">Over</th>
                      <th className="text-right px-3 py-2 text-slate-500 font-medium text-xs">Under</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(
                      [
                        ["0.5", "over_0.5", "under_0.5"],
                        ["1.5", "over_1.5", "under_1.5"],
                        ["2.5", null, null],
                        ["3.5", "over_3.5", "under_3.5"],
                        ["4.5", "over_4.5", "under_4.5"],
                      ] as [string, string | null, string | null][]
                    ).map(([line, ok, uk], i) => {
                      const overVal =
                        ok ? (m[ok] as number | undefined) :
                        line === "2.5" ? pred.over25_prob ?? undefined : undefined;
                      const underVal =
                        uk ? (m[uk] as number | undefined) :
                        line === "2.5" && pred.over25_prob != null
                          ? 1 - pred.over25_prob
                          : undefined;
                      if (overVal == null) return null;
                      return (
                        <tr key={line} className={i % 2 === 0 ? "bg-[#1a2744]/30" : ""}>
                          <td className="px-4 py-2.5 text-slate-300 font-medium text-xs">{line}</td>
                          <td className="px-3 py-2.5 text-right font-semibold text-white text-xs">
                            {p(overVal)}
                          </td>
                          <td className="px-3 py-2.5 text-right text-slate-400 text-xs">
                            {p(underVal)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* Fallback when no advanced data yet */}
            {!hasAdvanced && (
              <div className="card p-6 text-center text-slate-500 text-sm">
                Advanced market data will appear after the model runs for this match.
              </div>
            )}
          </>
        )}

        {/* ── CORRECT SCORES TAB ──────────────────────────────────────── */}
        {tab === "scores" && pred && (
          <>
            {topScores.length > 0 ? (
              <div className="card overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-700/50">
                  <h3 className="font-semibold text-sm">Top Correct Score Probabilities</h3>
                </div>
                <div className="divide-y divide-slate-700/50">
                  {topScores.map((cs, i) => (
                    <div key={cs.score} className="flex items-center px-4 py-3 gap-3">
                      <span className="text-xs text-slate-500 w-5">{i + 1}</span>
                      <span className="font-bold text-white text-lg flex-1 text-center">{cs.score}</span>
                      <div className="flex items-center gap-2 w-28">
                        <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
                          <div
                            className="h-2 rounded-full bg-sky-500"
                            style={{ width: `${Math.min(100, numPct(cs.prob))}%` }}
                          />
                        </div>
                        <span className="text-sm font-semibold text-white w-8 text-right">
                          {p(cs.prob)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="card p-6 text-center text-slate-500 text-sm">
                Correct score data will appear after the Poisson model runs for this match.
              </div>
            )}
          </>
        )}

        {/* Odds comparison — always visible */}
        {h2hOdds.length > 0 && <OddsTable title="Match Result Odds (1X2)" odds={h2hOdds} />}
        {totalsOdds.length > 0 && <OddsTable title="Totals" odds={totalsOdds} />}
        {bttsOdds.length > 0 && <OddsTable title="Both Teams To Score" odds={bttsOdds} />}
      </div>
    </div>
  );
}
