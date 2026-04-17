export interface Sport {
  id: number;
  key: string;
  name: string;
  icon: string;
  upcoming_matches: number;
}

export interface Competition {
  id: number;
  name: string;
  country: string;
}

export interface Odds {
  bookmaker: string;
  market: string;
  outcome: string;
  price: number;
  point?: number;
}

export interface PredictionValueBet {
  market: string;
  outcome: string;
  prob: number;
  odds: number;
  ev: number;
  kelly: number;
  confidence: "high" | "medium" | "low";
}

export interface PredictionMarkets {
  result?: Record<string, number>;
  over15?: { over: number; under: number };
  over25?: { over: number; under: number };
  over35?: { over: number; under: number };
  btts?: { yes: number; no: number };
  home_cs?: { yes: number; no: number };
  away_cs?: { yes: number; no: number };
  // Poisson-derived scalars
  double_chance_1x?: number;
  double_chance_x2?: number;
  double_chance_12?: number;
  dnb_home?: number;
  dnb_away?: number;
  home_clean_sheet?: number;
  away_clean_sheet?: number;
  home_win_to_nil?: number;
  away_win_to_nil?: number;
  btts_home_win?: number;
  btts_draw?: number;
  btts_away_win?: number;
  exp_home_goals?: number;
  exp_away_goals?: number;
  top_correct_scores?: Array<{ score: string; prob: number }>;
  value_bets?: PredictionValueBet[];
  [key: string]: unknown; // allows AH keys with dots like "ah_home_-0.5"
}

export interface Prediction {
  predicted_result: string | null;
  home_win_prob: number | null;
  draw_prob: number | null;
  away_win_prob: number | null;
  over25_prob: number | null;
  btts_prob: number | null;
  is_value_bet: boolean;
  value_market: string | null;
  value_outcome: string | null;
  value_odds: number | null;
  expected_value: number | null;
  kelly_stake: number | null;
  confidence: "high" | "medium" | "low" | null;
  markets: PredictionMarkets | null;
}

export interface IntelligenceSignal {
  type: "injury" | "suspension" | "return" | "morale" | "lineup";
  player: string | null;
  team: string;
  impact: number;       // -1.0 to +1.0
  confidence: number;   // 0 to 1
  source: string;
  note: string;
}

export interface Intelligence {
  has_intelligence: boolean;
  signals: IntelligenceSignal[];
}

export interface Match {
  id: number;
  external_id: string;
  sport: string;
  sport_icon: string;
  competition: string;
  country: string;
  home_team: string;
  away_team: string;
  home_elo: number;
  away_elo: number;
  match_date: string;
  status: string;
  live_minute: number | null;
  home_score: number | null;
  away_score: number | null;
  result: string | null;
  odds: Odds[];
  prediction: Prediction | null;
  intelligence: Intelligence | null;
}

export interface MatchDecision {
  match_id: number;
  sport: string | null;
  sport_icon: string;
  competition: string | null;
  country: string | null;
  home_team: string;
  away_team: string;
  match_date: string;
  status: string;
  // Decision
  ai_decision: "PLAY" | "SKIP";
  confidence_score: number;
  prob_tag: "HIGH" | "MEDIUM" | "RISKY";
  top_prob: number;
  predicted_outcome: string | null;
  has_volatility: boolean;
  volatility_reason: string | null;
  recommended_odds: number | null;
  recommended_stake_pct: number | null;
  score_breakdown: {
    probability: number;
    expected_value: number;
    form: number;
    consistency: number;
  };
  // SKIP reason (null on PLAY)
  skip_reason: string | null;
  // Value intelligence
  market_prob: number | null;
  market_prob_pct: number | null;
  model_prob_pct: number | null;
  edge: number | null;
  edge_pct: number | null;
  value_label: "strong_value" | "fair_value" | "no_value" | "no_odds" | null;
  // Closing Line Value
  clv: number | null;
  // Probabilities
  home_win_prob: number | null;
  draw_prob: number | null;
  away_win_prob: number | null;
  over25_prob: number | null;
  btts_prob: number | null;
  is_value_bet: boolean;
  expected_value: number | null;
  markets: PredictionMarkets | null;
}

export interface DailyPicksResponse {
  picks: MatchDecision[];
  total_analysed: number;
  total_plays: number;
  total_skipped: number;
  selection_rate: number;
}

export interface SmartSetMatch {
  match_id: number;
  home_team: string;
  away_team: string;
  sport: string;
  sport_icon: string;
  competition: string;
  match_date: string;
  ai_decision: string;
  confidence: number;
  prob_tag: string;
  predicted_outcome: string;
  top_prob: number;
  rec_odds: number;
}

export interface SmartSet {
  id: number;
  set_number: number;
  generated_date: string;
  match_count: number;
  overall_confidence: number;
  combined_probability: number;
  avg_odds: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  status: string;
  wins: number;
  losses: number;
  roi: number | null;
  matches: SmartSetMatch[];
}

export interface PerformanceStats {
  period_days: number;
  total_picks: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl_units: number;
  roi_pct: number;
  by_sport: Record<string, { wins: number; total: number; pnl: number; win_rate: number }>;
  top_competitions: { competition: string; win_rate: number; sample: number }[];
}

export interface PredictionHistory {
  match_id: number;
  sport: string;
  sport_icon: string;
  competition: string;
  home_team: string;
  away_team: string;
  match_date: string | null;
  // Prediction
  ai_decision: "PLAY" | "SKIP";
  confidence_score: number;
  predicted_outcome: string;
  predicted_outcome_label: string;
  predicted_prob: number | null;
  recommended_odds: number | null;
  // Actual result
  actual_result: string;
  actual_result_label: string;
  // Outcome
  is_correct: boolean;
  profit_loss_units: number;
  resolved_at: string;
}

export interface ValueBet {
  match_id: number;
  sport: string;
  sport_icon: string;
  competition: string;
  home_team: string;
  away_team: string;
  match_date: string;
  predicted_result: string | null;
  home_win_prob: number | null;
  draw_prob: number | null;
  away_win_prob: number | null;
  over25_prob: number | null;
  btts_prob: number | null;
  value_market: string;
  value_outcome: string;
  value_odds: number;
  expected_value: number;
  kelly_stake: number;
  confidence: "high" | "medium" | "low";
}
