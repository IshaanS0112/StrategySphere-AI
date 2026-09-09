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
  entity_key?: string | null;
  period_label?: string | null;
  period_end?: string | null;
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

// ---------------------------------------------------------------------------
// V2
// ---------------------------------------------------------------------------

export type ForceSource =
  | "COMPUTED"
  | "PARTIALLY_COMPUTED"
  | "ANALYST_INPUT"
  | "UNAVAILABLE";

export interface PorterForceEntry {
  force: string;
  score: number | null;
  source: ForceSource;
  evidence: string;
  inputs_used: string[];
  inputs_missing: string[];
  scale: string;
}

export interface PortersAnalysis {
  id: string;
  company_id: string;
  forces: PorterForceEntry[];
  composite_score: number | null;
  industry_attractiveness: "ATTRACTIVE" | "MODERATE" | "UNATTRACTIVE" | null;
  forces_scored: number;
  calculation_basis: Record<string, any>;
  generated_at: string | null;
}

export interface AxisSensitivity {
  axis: string;
  current_value: number;
  weight: number;
  derivative: number;
  required_delta: number | null;
  required_value: number | null;
  reachable: boolean;
  resulting_quadrant: string | null;
  headroom_up: number;
  headroom_down: number;
  note: string;
}

export interface Sensitivity {
  company_id: string;
  baseline_quadrant: Quadrant;
  baseline_attractiveness: number;
  baseline_strength: number;
  verdict: "ROBUST" | "FRAGILE" | "KNIFE_EDGE";
  axes: AxisSensitivity[];
  strength_sensitivity: AxisSensitivity | null;
  binding_constraint: AxisSensitivity | null;
  calculation_basis: Record<string, any>;
}

export interface Scenario {
  id: string;
  company_id: string;
  name: string;
  description: string | null;
  overrides: Record<string, any>;
  baseline_snapshot: Record<string, any>;
  scenario_result: Record<string, any>;
  delta: Record<string, { baseline: any; scenario: any; delta?: number }>;
  quadrant_changed: boolean;
  created_at: string | null;
}

export interface TimelinePoint {
  company_id: string;
  period_label: string | null;
  period_end: string | null;
  attractiveness: number;
  strength: number;
  quadrant: Quadrant;
  borderline: boolean;
  data_source: string | null;
}

export interface Timeline {
  entity_key: string;
  points: TimelinePoint[];
  excluded: { company_id: string; period_label: string | null; reason: string }[];
  attractiveness_trend: "IMPROVING" | "STABLE" | "DETERIORATING" | "INSUFFICIENT_DATA";
  strength_trend: "IMPROVING" | "STABLE" | "DETERIORATING" | "INSUFFICIENT_DATA";
  quadrant_changes: Record<string, any>[];
  summary: string;
  calculation_basis: Record<string, any>;
}
