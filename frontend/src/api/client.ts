import type {
  Company,
  Competitor,
  MarketAttractiveness,
  Methodology,
  PricingRecommendation,
  StrategyReport,
  SwotAnalysis,
} from "./types";

// In dev, Vite proxies /api -> :8000. In the Docker image, nginx does the same.
// Either way the browser only ever talks to its own origin.
const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = await response.text();
    }
    // FastAPI's detail is a string for our explicit HTTPExceptions and an
    // array of error objects for request-validation failures.
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map((d: any) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`)
              .join("; ")
          : `Request failed (${response.status})`;
    throw new ApiError(message, response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** A 404 from a stage that has not been run yet is expected, not an error. */
export async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export interface CompanyDraft {
  name: string;
  industry?: string | null;
  data_source: string;
  financial_data: Record<string, number>;
  market_data: Record<string, unknown>;
  feature_scores: Record<string, number>;
  qualitative_inputs: {
    factor: string;
    category: string;
    evidence: string;
    impact_score: number;
  }[];
}

export interface CompetitorDraft {
  competitor_name: string;
  price_point?: number | null;
  market_share_pct?: number | null;
  feature_scores: Record<string, number>;
  financial_data: Record<string, number>;
}

export const api = {
  methodology: () => request<Methodology>("/methodology"),

  listCompanies: () => request<Company[]>("/companies"),
  getCompany: (id: string) => request<Company>(`/companies/${id}`),
  createCompany: (body: CompanyDraft) =>
    request<Company>("/companies", { method: "POST", body: JSON.stringify(body) }),
  deleteCompany: (id: string) =>
    request<void>(`/companies/${id}`, { method: "DELETE" }),

  listCompetitors: (id: string) => request<Competitor[]>(`/companies/${id}/competitors`),
  addCompetitor: (id: string, body: CompetitorDraft) =>
    request<Competitor>(`/companies/${id}/competitors`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  runSwot: (id: string) =>
    request<SwotAnalysis>(`/companies/${id}/swot-analysis`, { method: "POST" }),
  getSwot: (id: string) => request<SwotAnalysis>(`/companies/${id}/swot-analysis`),

  runAttractiveness: (id: string) =>
    request<MarketAttractiveness>(`/companies/${id}/market-attractiveness`, {
      method: "POST",
    }),
  getAttractiveness: (id: string) =>
    request<MarketAttractiveness>(`/companies/${id}/market-attractiveness`),

  runPricing: (
    id: string,
    body: { cost_base: number; target_margin_pct: number; margin_basis?: string },
  ) =>
    request<PricingRecommendation>(`/companies/${id}/pricing-recommendation`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getPricing: (id: string) =>
    request<PricingRecommendation>(`/companies/${id}/pricing-recommendation`),

  runReport: (id: string) =>
    request<StrategyReport>(`/companies/${id}/generate-strategy-report`, { method: "POST" }),
  getReport: (id: string) => request<StrategyReport>(`/companies/${id}/strategy-report`),
};
