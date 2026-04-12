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
