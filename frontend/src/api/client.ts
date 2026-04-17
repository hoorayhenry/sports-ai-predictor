import axios from "axios";
import type { Sport, Competition, Match, ValueBet, MatchDecision, DailyPicksResponse, SmartSet, PerformanceStats, PredictionHistory } from "./types";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";

export const api = axios.create({ baseURL: BASE });

export const fetchSports = () =>
  api.get<Sport[]>("/sports").then((r) => r.data);

export const fetchCompetitions = (sportKey: string) =>
  api.get<Competition[]>(`/sports/${sportKey}/competitions`).then((r) => r.data);

export interface MatchPage {
  matches: Match[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export const fetchMatches = (params: {
  sport?: string;
  competition_id?: number;
  status?: string;
  days?: number;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}) => api.get<MatchPage>("/matches", { params }).then((r) => r.data);

export const fetchMatch = (id: number) =>
  api.get<Match>(`/matches/${id}`).then((r) => r.data);

export const fetchValueBets = (sport?: string) =>
  api.get<ValueBet[]>("/predictions/value-bets", { params: sport ? { sport } : {} }).then((r) => r.data);

export const triggerPrediction = (matchId: number) =>
  api.post(`/predictions/run/${matchId}`).then((r) => r.data);

export const triggerAllPredictions = (sport?: string) =>
  api.post("/predictions/run-all", null, { params: sport ? { sport } : {} }).then((r) => r.data);

export const fetchPredictionStats = () =>
  api.get("/predictions/stats").then((r) => r.data);

// Decision engine
export const fetchDailyPicks = (sport?: string, days = 7) =>
  api.get<DailyPicksResponse>("/decisions/daily-picks", { params: { ...(sport ? { sport } : {}), days, limit: 50 } }).then((r) => r.data);

export const fetchAllDecisions = (params?: {
  sport?: string; decision?: string; prob_tag?: string; days?: number;
}) => api.get<MatchDecision[]>("/decisions/all", { params }).then((r) => r.data);

export const fetchSmartSets = (dateStr?: string) =>
  api.get<SmartSet[]>("/decisions/smart-sets", { params: dateStr ? { date_str: dateStr } : {} }).then((r) => r.data);

export const fetchPerformance = (sport?: string, days?: number) =>
  api.get<PerformanceStats>("/decisions/performance", { params: { sport, days } }).then((r) => r.data);

export const triggerDecisionsNow = (sendEmail = false) =>
  api.post("/decisions/run-now", null, { params: { send_email: sendEmail } }).then((r) => r.data);

export const fetchPredictionHistory = (params?: {
  sport?: string; days?: number; decision?: string; limit?: number;
}) => api.get<PredictionHistory[]>("/decisions/history", { params }).then((r) => r.data);

export interface LiveScoresResponse {
  live_count: number;
  matches: Match[];
}

export const fetchLiveScores = () =>
  api.get<LiveScoresResponse>("/matches/live/scores").then((r) => r.data);
