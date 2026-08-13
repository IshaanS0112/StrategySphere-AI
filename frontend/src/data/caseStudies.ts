import type { CompanyDraft, CompetitorDraft } from "../api/client";

/**
 * Demo presets.
 *
 * ⚠️ These are ILLUSTRATIVE COMPOSITES, not real companies and not figures
 * extracted from any filing. They exist so the pipeline can be exercised in one
 * click. They mirror `data/case_studies/*.json` in the repo root, which the
 * backend loader script reads — keep the two in sync if you edit either.
 *
 * For real analysis, replace them with figures from an annual report or a
 * published case study and record the source in `data_source`.
 */
export interface CaseStudy {
  key: string;
  label: string;
  summary: string;
  company: CompanyDraft;
  competitors: CompetitorDraft[];
}

export const CASE_STUDIES: CaseStudy[] = [
  {
    key: "premium_saas",
    label: "Premium B2B SaaS (illustrative)",
    summary:
      "Strong margins and growth in a fragmented, fast-growing market. Should land in or near INVEST_GROW.",
    company: {
      name: "Northwind Analytics (illustrative)",
      industry: "saas",
      data_source:
        "ILLUSTRATIVE COMPOSITE - not a real company. Replace with figures from an annual report before drawing conclusions.",
      financial_data: {
        revenue_growth_pct: 34.0,
        gross_margin_pct: 82.0,
        operating_margin_pct: 14.0,
        net_margin_pct: 9.0,
        return_on_capital_pct: 16.0,
        market_share_pct: 12.0,
        customer_retention_pct: 94.0,
        rnd_intensity_pct: 24.0,
        debt_to_equity: 0.2,
      },
      market_data: {
        market_growth_pct: 19.0,
        market_size_usd_bn: 42.0,
        industry_operating_margin_pct: 17.0,
        regulatory_outlook: "NEUTRAL",
      },
      feature_scores: { integrations: 5, support: 4, uptime: 5, reporting: 4 },
      qualitative_inputs: [
        {
          factor: "Category-defining brand in a narrow niche",
          category: "STRENGTH",
          evidence: "Consistently named in analyst shortlists for this segment.",
          impact_score: 4,
        },
        {
          factor: "Single-region engineering concentration",
          category: "WEAKNESS",
          evidence: "All delivery capacity sits in one metro, with no failover.",
          impact_score: 3,
        },
      ],
    },
    competitors: [
      {
        competitor_name: "Meridian Data",
        price_point: 1200,
        market_share_pct: 15,
        feature_scores: { integrations: 4, support: 3, uptime: 4, reporting: 4 },
        financial_data: { operating_margin_pct: 9.0, gross_margin_pct: 74.0, revenue_growth_pct: 21.0 },
      },
      {
        competitor_name: "Corvus Insights",
        price_point: 900,
        market_share_pct: 11,
        feature_scores: { integrations: 3, support: 4, uptime: 3, reporting: 5 },
        financial_data: { operating_margin_pct: 6.0, gross_margin_pct: 71.0, revenue_growth_pct: 28.0 },
      },
      {
        competitor_name: "Halcyon BI",
        price_point: 1500,
        market_share_pct: 9,
        feature_scores: { integrations: 5, support: 2, uptime: 4, reporting: 3 },
        financial_data: { operating_margin_pct: 12.0, gross_margin_pct: 78.0, revenue_growth_pct: 14.0 },
      },
      {
        competitor_name: "Tessera Cloud",
        price_point: 1100,
        market_share_pct: 7,
        feature_scores: { integrations: 3, support: 3, uptime: 5, reporting: 3 },
        financial_data: { operating_margin_pct: 4.0, gross_margin_pct: 69.0, revenue_growth_pct: 33.0 },
      },
    ],
  },
  {
    key: "commodity_manufacturer",
    label: "Squeezed manufacturer (illustrative)",
    summary:
      "Thin margins and leverage in a slow, commoditised market. Should land in or near HARVEST_DIVEST.",
    company: {
      name: "Ferrand Components (illustrative)",
      industry: "manufacturing",
      data_source:
        "ILLUSTRATIVE COMPOSITE - not a real company. Replace with figures from an annual report before drawing conclusions.",
      financial_data: {
        revenue_growth_pct: 0.8,
        gross_margin_pct: 19.0,
        operating_margin_pct: 3.0,
        net_margin_pct: 1.2,
        return_on_capital_pct: 5.0,
        market_share_pct: 4.0,
        customer_retention_pct: 62.0,
        debt_to_equity: 2.4,
      },
      market_data: {
        market_growth_pct: 1.5,
        market_size_usd_bn: 3.0,
        industry_operating_margin_pct: 5.0,
        regulatory_outlook: "ADVERSE",
        regulatory_impact_score: 4,
      },
      feature_scores: { durability: 3, lead_time: 2, certification: 3 },
      qualitative_inputs: [
        {
          factor: "Ageing plant with deferred capex",
          category: "WEAKNESS",
          evidence: "Two of three lines are past their planned replacement date.",
          impact_score: 5,
        },
      ],
    },
    competitors: [
      {
        competitor_name: "Kestrel Metalworks",
        price_point: 48,
        market_share_pct: 9,
        feature_scores: { durability: 4, lead_time: 4, certification: 4 },
        financial_data: { operating_margin_pct: 9.0, gross_margin_pct: 31.0, revenue_growth_pct: 4.0 },
      },
      {
        competitor_name: "Arbor Industrial",
        price_point: 45,
        market_share_pct: 8,
        feature_scores: { durability: 3, lead_time: 5, certification: 3 },
        financial_data: { operating_margin_pct: 7.5, gross_margin_pct: 28.0, revenue_growth_pct: 2.5 },
      },
      {
        competitor_name: "Pallas Forge",
        price_point: 51,
        market_share_pct: 7,
        feature_scores: { durability: 5, lead_time: 3, certification: 4 },
        financial_data: { operating_margin_pct: 11.0, gross_margin_pct: 34.0, revenue_growth_pct: 3.0 },
      },
      {
        competitor_name: "Dunmore Castings",
        price_point: 47,
        market_share_pct: 6,
        feature_scores: { durability: 3, lead_time: 3, certification: 5 },
        financial_data: { operating_margin_pct: 8.0, gross_margin_pct: 29.0, revenue_growth_pct: 1.0 },
      },
    ],
  },
  {
    key: "contested_retail",
    label: "Contested retailer (illustrative)",
    summary:
      "Good growth, weak balance sheet, brutal rivalry. Designed to land near a quadrant boundary and trip the borderline flag.",
    company: {
      name: "Calder & Roe (illustrative)",
      industry: "retail",
      data_source:
        "ILLUSTRATIVE COMPOSITE - not a real company. Replace with figures from an annual report before drawing conclusions.",
      financial_data: {
        revenue_growth_pct: 11.0,
        gross_margin_pct: 33.0,
        operating_margin_pct: 6.4,
        net_margin_pct: 2.9,
        return_on_capital_pct: 10.0,
        market_share_pct: 6.0,
        customer_retention_pct: 58.0,
        debt_to_equity: 1.9,
      },
      market_data: {
        market_growth_pct: 7.0,
        market_size_usd_bn: 22.0,
        industry_operating_margin_pct: 7.0,
        regulatory_outlook: "NEUTRAL",
      },
      feature_scores: { assortment: 4, delivery: 3, price_perception: 2 },
      qualitative_inputs: [
        {
          factor: "Loyalty programme with high repeat share",
          category: "STRENGTH",
          evidence: "A majority of revenue comes from enrolled members.",
          impact_score: 3,
        },
        {
          factor: "Rising last-mile delivery cost",
          category: "THREAT",
          evidence: "Fulfilment cost per order has risen for six consecutive quarters.",
          impact_score: 4,
        },
      ],
    },
    competitors: [
      {
        competitor_name: "Vale Retail",
        price_point: 74,
        market_share_pct: 8,
        feature_scores: { assortment: 4, delivery: 4, price_perception: 3 },
        financial_data: { operating_margin_pct: 6.0, gross_margin_pct: 30.0, revenue_growth_pct: 6.0 },
      },
      {
        competitor_name: "Brightmarket",
        price_point: 69,
        market_share_pct: 7,
        feature_scores: { assortment: 3, delivery: 5, price_perception: 4 },
        financial_data: { operating_margin_pct: 5.0, gross_margin_pct: 27.0, revenue_growth_pct: 9.0 },
      },
      {
        competitor_name: "Ashgrove Stores",
        price_point: 78,
        market_share_pct: 6,
        feature_scores: { assortment: 5, delivery: 2, price_perception: 2 },
        financial_data: { operating_margin_pct: 7.5, gross_margin_pct: 32.0, revenue_growth_pct: 3.0 },
      },
      {
        competitor_name: "Nine Elms Direct",
        price_point: 71,
        market_share_pct: 5,
        feature_scores: { assortment: 3, delivery: 4, price_perception: 4 },
        financial_data: { operating_margin_pct: 4.5, gross_margin_pct: 26.0, revenue_growth_pct: 12.0 },
      },
    ],
  },
];
