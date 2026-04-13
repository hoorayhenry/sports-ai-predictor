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
  home_score: number | null;
  away_score: number | null;
  result: string | null;
  odds: Odds[];
  prediction: Prediction | null;
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
  // Probabilities
  home_win_prob: number | null;
  draw_prob: number | null;
  away_win_prob: number | null;
  over25_prob: number | null;
  btts_prob: number | null;
  is_value_bet: boolean;
  expected_value: number | null;
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
