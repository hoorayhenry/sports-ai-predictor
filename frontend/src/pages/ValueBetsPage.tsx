import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Zap } from "lucide-react";
import { fetchSports, fetchValueBets } from "../api/client";
import SportTabs from "../components/SportTabs";
import Spinner from "../components/Spinner";
import { formatDate, outcomeLabel, confidenceColor } from "../utils/format";
import { Link, useNavigate } from "react-router-dom";
import type { ValueBet } from "../api/types";
import { getCompetitionSlug } from "../utils/competitionSlug";

export default function ValueBetsPage() {
  const [sport, setSport] = useState("all");

  const { data: sports = [] } = useQuery({
    queryKey: ["sports"],
    queryFn: fetchSports,
    staleTime: 60_000,
  });

  const { data: valueBets = [], isLoading } = useQuery({
    queryKey: ["value-bets", sport],
    queryFn: () => fetchValueBets(sport === "all" ? undefined : sport),
    staleTime: 30_000,
  });

  const totalEV = valueBets.reduce((sum, b) => sum + (b.expected_value ?? 0), 0);

  return (
    <div className="min-h-screen pb-20 md:pb-6 px-4 pt-6">
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <div className="bg-yellow-500/20 p-2 rounded-xl">
          <Zap size={20} className="text-yellow-400" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-white">Value Bets</h2>
          <p className="text-xs text-slate-400">Positive expected value opportunities</p>
        </div>
      </div>

      {/* Summary */}
      {valueBets.length > 0 && (
        <div className="card px-4 py-3 mb-4 flex gap-4 text-sm">
          <div>
            <p className="text-slate-400 text-xs">Opportunities</p>
            <p className="font-bold text-white">{valueBets.length}</p>
          </div>
          <div>
            <p className="text-slate-400 text-xs">Avg EV</p>
            <p className="font-bold text-green-400">
              +{valueBets.length > 0 ? ((totalEV / valueBets.length) * 100).toFixed(1) : 0}%
            </p>
          </div>
          <div>
            <p className="text-slate-400 text-xs">High conf.</p>
            <p className="font-bold text-white">
              {valueBets.filter((b) => b.confidence === "high").length}
            </p>
          </div>
        </div>
      )}

      <div className="mb-4">
        <SportTabs sports={sports} selected={sport} onSelect={setSport} />
      </div>

      {isLoading ? (
        <div className="flex justify-center py-20">
          <Spinner size={40} />
        </div>
      ) : valueBets.length === 0 ? (
        <div className="text-center py-20 text-slate-500">
          <p className="text-5xl mb-4">💤</p>
          <p>No value bets found right now.</p>
          <p className="text-xs mt-2">Check back after more fixtures are loaded.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {valueBets.map((bet) => (
            <ValueBetCard key={bet.match_id} bet={bet} />
          ))}
        </div>
      )}
    </div>
  );
}

function ValueBetCard({ bet }: { bet: ValueBet }) {
  const navigate = useNavigate();
  const slug = getCompetitionSlug(bet.competition ?? "");
  return (
    <Link to={`/match/${bet.match_id}`}>
      <div className="card p-4 border-yellow-500/30 hover:border-yellow-500/60 transition-all">
        {/* Sport + competition */}
        <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
          <span>{bet.sport_icon}</span>
          {slug ? (
            <button
              className="truncate hover:text-pi-sky transition-colors"
              onClick={e => { e.preventDefault(); e.stopPropagation(); navigate(`/tables?slug=${slug}`); }}
            >{bet.competition}</button>
          ) : (
            <span className="truncate">{bet.competition}</span>
          )}
          <span className="ml-auto shrink-0">{formatDate(bet.match_date)}</span>
        </div>

        {/* Teams */}
        <p className="font-semibold text-sm mb-3">
          {bet.home_team} <span className="text-slate-500">vs</span> {bet.away_team}
        </p>

        {/* Bet detail */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1.5 bg-yellow-500/10 border border-yellow-500/30 rounded-full px-3 py-1 text-xs font-semibold text-yellow-300">
            <Zap size={11} />
            {outcomeLabel(bet.value_market, bet.value_outcome)}
          </div>
          <span className="text-sm font-bold text-white">@ {bet.value_odds.toFixed(2)}</span>
          <span className="text-green-400 font-bold text-sm">
            +{(bet.expected_value * 100).toFixed(1)}% EV
          </span>
          <span className={`text-xs font-semibold ml-auto ${confidenceColor(bet.confidence)}`}>
            {bet.confidence.toUpperCase()}
          </span>
        </div>

        {/* Probs */}
        <div className="mt-3 flex gap-3 text-xs text-slate-400">
          {bet.home_win_prob != null && (
            <span>H: <span className="text-slate-200">{Math.round(bet.home_win_prob * 100)}%</span></span>
          )}
          {bet.draw_prob != null && (
            <span>D: <span className="text-slate-200">{Math.round(bet.draw_prob * 100)}%</span></span>
          )}
          {bet.away_win_prob != null && (
            <span>A: <span className="text-slate-200">{Math.round(bet.away_win_prob * 100)}%</span></span>
          )}
          {bet.kelly_stake != null && (
            <span className="ml-auto">Kelly: <span className="text-sky-300">{(bet.kelly_stake * 100).toFixed(1)}%</span></span>
          )}
        </div>
      </div>
    </Link>
  );
}
