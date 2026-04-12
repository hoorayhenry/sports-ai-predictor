import axios from "axios";
import type { Sport, Competition, Match, ValueBet } from "./types";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";

const api = axios.create({ baseURL: BASE });

export const fetchSports = () =>
  api.get<Sport[]>("/sports").then((r) => r.data);

export const fetchCompetitions = (sportKey: string) =>
  api.get<Competition[]>(`/sports/${sportKey}/competitions`).then((r) => r.data);

export const fetchMatches = (params: {
  sport?: string;
  competition_id?: number;
  status?: string;
  days?: number;
}) => api.get<Match[]>("/matches", { params }).then((r) => r.data);

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
