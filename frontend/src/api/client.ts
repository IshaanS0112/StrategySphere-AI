import type {
  AllocationRun,
  BenchmarkProvenance,
  Company,
  Competitor,
  Job,
  MarketAttractiveness,
  Methodology,
  PortersAnalysis,
  PricingRecommendation,
  Scenario,
  Page,
  Portfolio,
  Problem,
  Sensitivity,
  StrategyReport,
  SwotAnalysis,
  ThreePoint,
  Timeline,
  UncertaintyAnalysis,
} from "./types";

// In dev, Vite proxies /api -> :8000. In the Docker image, nginx does the same.
// Either way the browser only ever talks to its own origin.
const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
    /** Stable machine code from the problem document, e.g. */
    readonly code?: string,
    /** Quote this in a bug report; it ties the failure to the server's logs. */
    readonly requestId?: string,
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
    // Every error is now an RFC 9457 problem document, including the ones
    // FastAPI raises itself, so there is one shape to parse rather than two.
    let problem: Partial<Problem> = {};
    try {
      problem = (await response.json()) as Problem;
    } catch {
      problem = { detail: await response.text() };
    }
    const message =
      typeof problem.detail === "string" && problem.detail
        ? problem.detail
        : `Request failed (${response.status})`;
    throw new ApiError(
      message,
      response.status,
      problem.detail,
      problem.code,
      problem.request_id,
    );
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

  listCompanies: (params?: {
    limit?: number;
    cursor?: string;
    industry?: string;
    q?: string;
    with_total?: boolean;
  }) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params ?? {})) {
      if (value !== undefined && value !== "") query.set(key, String(value));
    }
    const suffix = query.toString() ? `?${query}` : "";
    return request<Page<Company>>(`/companies${suffix}`);
  },
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

  // --- V2 ---
  runPorters: (id: string) =>
    request<PortersAnalysis>(`/companies/${id}/porters-analysis`, { method: "POST" }),
  getPorters: (id: string) => request<PortersAnalysis>(`/companies/${id}/porters-analysis`),

  getSensitivity: (id: string) => request<Sensitivity>(`/companies/${id}/sensitivity`),

  listScenarios: (id: string) => request<Scenario[]>(`/companies/${id}/scenarios`),
  createScenario: (
    id: string,
    body: { name: string; description?: string; overrides: Record<string, unknown> },
  ) =>
    request<Scenario>(`/companies/${id}/scenarios`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteScenario: (id: string, scenarioId: string) =>
    request<void>(`/companies/${id}/scenarios/${scenarioId}`, { method: "DELETE" }),

  // --- V3 ---
  runUncertainty: (
    id: string,
    body: { uncertainty_inputs?: Record<string, ThreePoint>; persist_inputs?: boolean },
  ) =>
    request<UncertaintyAnalysis>(`/companies/${id}/uncertainty`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getUncertainty: (id: string) =>
    request<UncertaintyAnalysis>(`/companies/${id}/uncertainty`),

  listPortfolios: () => request<Portfolio[]>("/portfolios"),
  getPortfolio: (id: string) => request<Portfolio>(`/portfolios/${id}`),
  createPortfolio: (body: {
    name: string;
    description?: string;
    budget: number;
    members: {
      company_id: string;
      revenue?: number | null;
      capital_requested: number;
      capital_floor?: number;
    }[];
  }) =>
    request<Portfolio>("/portfolios", { method: "POST", body: JSON.stringify(body) }),
  deletePortfolio: (id: string) =>
    request<void>(`/portfolios/${id}`, { method: "DELETE" }),
  allocate: (id: string, body: { budget?: number }) =>
    request<AllocationRun>(`/portfolios/${id}/allocate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listAllocations: (id: string) => request<AllocationRun[]>(`/portfolios/${id}/allocations`),

  benchmarkProvenance: () => request<BenchmarkProvenance>("/benchmarks/provenance"),

  listJobs: (params?: { kind?: string; state?: string; limit?: number }) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params ?? {})) {
      if (value !== undefined) query.set(key, String(value));
    }
    const suffix = query.toString() ? `?${query}` : "";
    return request<Job[]>(`/jobs${suffix}`);
  },
  getJob: (id: string) => request<Job>(`/jobs/${id}`),
  cancelJob: (id: string) =>
    request<Job>(`/jobs/${id}/cancel`, { method: "POST" }),
  buildBenchmarks: (body: { period?: string; sic_limit?: number; offline?: boolean }) =>
    request<Job>("/benchmarks/build", { method: "POST", body: JSON.stringify(body) }),

  listEntities: () =>
    request<{ entity_key: string; name: string; periods: (string | null)[] }[]>("/entities"),
  getTimeline: (entityKey: string) =>
    request<Timeline>(`/entities/${entityKey}/timeline`),
};
