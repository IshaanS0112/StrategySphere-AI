import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";

/**
 * Manual entry.
 *
 * Numeric fields are kept as strings in state and only parsed on submit: a
 * controlled number input that reparses on every keystroke makes it impossible
 * to type "0.4" (the intermediate "0." is not a number) and silently drops
 * trailing decimals.
 */

interface MetricField {
  key: string;
  label: string;
  hint?: string;
}

const FINANCIAL_FIELDS: MetricField[] = [
  { key: "revenue_growth_pct", label: "Revenue growth %" },
  { key: "gross_margin_pct", label: "Gross margin %" },
  { key: "operating_margin_pct", label: "Operating margin %" },
  { key: "net_margin_pct", label: "Net margin %" },
  { key: "return_on_capital_pct", label: "Return on capital %" },
  { key: "market_share_pct", label: "Market share %", hint: "feeds the HHI" },
  { key: "customer_retention_pct", label: "Customer retention %" },
  { key: "rnd_intensity_pct", label: "R&D intensity %" },
  { key: "debt_to_equity", label: "Debt-to-equity x", hint: "lower is better" },
];

const MARKET_FIELDS: MetricField[] = [
  { key: "market_growth_pct", label: "Market growth % p.a." },
  { key: "market_size_usd_bn", label: "Market size USD bn" },
  { key: "industry_operating_margin_pct", label: "Industry operating margin %" },
];

function parseNumbers(raw: Record<string, string>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(raw)) {
    const trimmed = value.trim();
    if (trimmed === "") continue;
    const parsed = Number(trimmed);
    if (Number.isFinite(parsed)) out[key] = parsed;
  }
  return out;
}

export default function NewCompany() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [dataSource, setDataSource] = useState("");
  const [financials, setFinancials] = useState<Record<string, string>>({});
  const [market, setMarket] = useState<Record<string, string>>({});
  const [regulatory, setRegulatory] = useState("NEUTRAL");
  const [features, setFeatures] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function parseFeatures(): Record<string, number> {
    const out: Record<string, number> = {};
    for (const pair of features.split(",")) {
      const [key, value] = pair.split(":").map((part) => part.trim());
      if (!key || value === undefined) continue;
      const parsed = Number(value);
      if (Number.isFinite(parsed)) out[key] = parsed;
    }
    return out;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const company = await api.createCompany({
        name: name.trim(),
        industry: industry.trim() || null,
        data_source: dataSource.trim(),
        financial_data: parseNumbers(financials),
        market_data: { ...parseNumbers(market), regulatory_outlook: regulatory },
        feature_scores: parseFeatures(),
        qualitative_inputs: [],
      });
      navigate(`/companies/${company.id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <section className="panel p-5">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-slate-300">
          Company
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="name">
              Name
            </label>
            <input
              id="name"
              className="field"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="label" htmlFor="industry">
              Industry
            </label>
            <input
              id="industry"
              className="field"
              placeholder="saas / retail / manufacturing"
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
            />
          </div>
        </div>
        <div className="mt-4">
          <label className="label" htmlFor="source">
            Data source (required)
          </label>
          <input
            id="source"
            className="field"
            placeholder="e.g. FY2025 annual report, MD&A section"
            value={dataSource}
            onChange={(e) => setDataSource(e.target.value)}
            required
            minLength={3}
          />
          <p className="mt-1 text-xs text-slate-500">
            Recorded on every downstream result. A case study with no provenance is not a
            case study.
          </p>
        </div>
      </section>

      <section className="panel p-5">
        <h2 className="mb-1 text-sm font-semibold uppercase tracking-wider text-slate-300">
          Financials
        </h2>
        <p className="mb-4 text-xs text-slate-500">
          Leave a field blank to omit it. Omitted metrics are skipped by the SWOT engine,
          not imputed.
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          {FINANCIAL_FIELDS.map((field) => (
            <div key={field.key}>
              <label className="label" htmlFor={field.key}>
                {field.label}
                {field.hint ? <span className="ml-1 text-slate-600">{field.hint}</span> : null}
              </label>
              <input
                id={field.key}
                className="field font-mono"
                inputMode="decimal"
                value={financials[field.key] ?? ""}
                onChange={(e) =>
                  setFinancials((prev) => ({ ...prev, [field.key]: e.target.value }))
                }
              />
            </div>
          ))}
        </div>
      </section>

      <section className="panel p-5">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-slate-300">
          Market
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {MARKET_FIELDS.map((field) => (
            <div key={field.key}>
              <label className="label" htmlFor={field.key}>
                {field.label}
              </label>
              <input
                id={field.key}
                className="field font-mono"
                inputMode="decimal"
                value={market[field.key] ?? ""}
                onChange={(e) => setMarket((prev) => ({ ...prev, [field.key]: e.target.value }))}
              />
            </div>
          ))}
          <div>
            <label className="label" htmlFor="regulatory">
              Regulatory outlook
            </label>
            <select
              id="regulatory"
              className="field"
              value={regulatory}
              onChange={(e) => setRegulatory(e.target.value)}
            >
              <option value="FAVOURABLE">Favourable</option>
              <option value="NEUTRAL">Neutral</option>
              <option value="ADVERSE">Adverse</option>
            </select>
          </div>
        </div>
      </section>

      <section className="panel p-5">
        <h2 className="mb-1 text-sm font-semibold uppercase tracking-wider text-slate-300">
          Feature scores
        </h2>
        <p className="mb-3 text-xs text-slate-500">
          Comma-separated <code>name: score</code> pairs on a 1-5 scale. Use the same
          feature names on the competitors — only shared features are compared.
        </p>
        <input
          className="field font-mono"
          placeholder="speed: 4, support: 3, uptime: 5"
          value={features}
          onChange={(e) => setFeatures(e.target.value)}
        />
      </section>

      {error && <p className="panel border-negative/40 p-3 text-xs text-negative">{error}</p>}

      <div className="flex gap-3">
        <button className="btn-primary" disabled={submitting}>
          {submitting ? "Creating…" : "Create company"}
        </button>
        <button type="button" className="btn-ghost" onClick={() => navigate("/")}>
          Cancel
        </button>
      </div>
    </form>
  );
}
