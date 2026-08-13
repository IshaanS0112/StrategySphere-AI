export type SwotCategory = "STRENGTH" | "WEAKNESS" | "OPPORTUNITY" | "THREAT";
export type Quadrant = "INVEST_GROW" | "SELECTIVE_INVEST" | "HARVEST_DIVEST";
export type MarginBasis = "MARGIN" | "MARKUP";

export interface SwotFactor {
  factor: string;
  category: SwotCategory;
  evidence: string;
  impact_score: number;
  /** computed_financial | computed_market | analyst_input */
  source: string;
  metric?: string | null;
  benchmark_basis?: string | null;
}

export interface Company {
  id: string;
  name: string;
  industry: string | null;
  financial_data: Record<string, unknown>;
  market_data: Record<string, unknown>;
  feature_scores: Record<string, number>;
  qualitative_inputs: unknown[];
  data_source: string | null;
  created_at: string | null;
}

export interface Competitor {
  id: string;
  company_id: string;
  competitor_name: string;
  price_point: number | null;
  market_share_pct: number | null;
  feature_scores: Record<string, number>;
  financial_data: Record<string, unknown>;
  added_at: string | null;
}

export interface SwotAnalysis {
  id: string;
  company_id: string;
  strengths: SwotFactor[];
  weaknesses: SwotFactor[];
  opportunities: SwotFactor[];
  threats: SwotFactor[];
  calculation_basis: Record<string, any>;
  generated_at: string | null;
}

export interface MarketAttractiveness {
  id: string;
  company_id: string;
  market_growth_score: number;
  market_size_score: number;
  profitability_score: number;
  competitive_intensity_score: number;
  overall_attractiveness_score: number;
  competitive_strength_score: number;
  quadrant: Quadrant;
  borderline: boolean;
  calculation_basis: Record<string, any>;
  calculated_at: string | null;
}

export interface PricingRecommendation {
  id: string;
  company_id: string;
  cost_base: number;
  competitor_avg_price: number | null;
  target_margin_pct: number;
  margin_basis: MarginBasis;
  recommended_price_range: { min: number; optimal: number; max: number };
  reasoning: {
    steps?: string[];
    warnings?: string[];
    margin_basis_note?: string;
    confidence?: string;
  };
  calculation_basis: Record<string, any>;
  calculated_at: string | null;
}

export interface StrategyReport {
  id: string;
  company_id: string;
  structured_context: Record<string, any>;
  ai_narrative: {
    executive_summary?: string;
    strategic_position?: string;
    key_factors?: { factor: string; implication: string }[];
    pricing_rationale?: string;
    recommendation?: string;
    generated_by?: string;
    fallback_reason?: string;
    dropped_citations?: number;
  } | null;
  narrative_source: string | null;
  generated_at: string | null;
}

export interface Methodology {
  frameworks: string[];
  attractiveness_weights: Record<string, number>;
  quadrant_thresholds: { high: number; low: number; borderline_margin: number };
  benchmark_provenance: string;
  llm_role: string;
  [key: string]: unknown;
}
