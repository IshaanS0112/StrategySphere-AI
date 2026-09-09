import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, optional } from "../api/client";
import type {
  Company,
  Competitor,
  MarketAttractiveness,
  PortersAnalysis,
  PricingRecommendation,
  Scenario,
  Sensitivity,
  StrategyReport,
  SwotAnalysis,
} from "../api/types";
import AttractivenessMatrix from "../components/AttractivenessMatrix";
import PortersView from "../components/PortersView";
import ScenarioPanel from "../components/ScenarioPanel";
import SensitivityPanel from "../components/SensitivityPanel";
import PricingView from "../components/PricingView";
import ReportView from "../components/ReportView";
import SWOTGrid from "../components/SWOTGrid";

type Stage = "swot" | "matrix" | "pricing" | "report" | "porters" | "scenario";

function StageShell({
  index,
  title,
  subtitle,
  action,
  children,
}: {
  index: number;
  title: string;
  subtitle: string;
  action: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-200">
            <span className="mr-2 text-slate-600">{index}</span>
            {title}
          </h2>
          <p className="mt-0.5 max-w-2xl text-xs leading-relaxed text-slate-500">{subtitle}</p>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export default function CompanyDetail() {
  const { companyId = "" } = useParams();

  const [company, setCompany] = useState<Company | null>(null);
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [swot, setSwot] = useState<SwotAnalysis | null>(null);
  const [matrix, setMatrix] = useState<MarketAttractiveness | null>(null);
  const [pricing, setPricing] = useState<PricingRecommendation | null>(null);
  const [report, setReport] = useState<StrategyReport | null>(null);
  const [porters, setPorters] = useState<PortersAnalysis | null>(null);
  const [sensitivity, setSensitivity] = useState<Sensitivity | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);

  const [costBase, setCostBase] = useState("100");
  const [margin, setMargin] = useState("40");
  const [basis, setBasis] = useState("MARGIN");

  const [busy, setBusy] = useState<Stage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [c, comps, s, m, p, r, pf, sc] = await Promise.all([
        api.getCompany(companyId),
        api.listCompetitors(companyId),
        optional(api.getSwot(companyId)),
        optional(api.getAttractiveness(companyId)),
        optional(api.getPricing(companyId)),
        optional(api.getReport(companyId)),
        optional(api.getPorters(companyId)),
        api.listScenarios(companyId),
      ]);
      setCompany(c);
      setCompetitors(comps);
      setSwot(s);
      setMatrix(m);
      setPricing(p);
      setReport(r);
      setPorters(pf);
      setScenarios(sc);
      // Sensitivity is derived from the stored matrix row, so it only exists
      // once the matrix has been run. A 409 here is expected, not an error.
      setSensitivity(m ? await api.getSensitivity(companyId).catch(() => null) : null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [companyId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(stage: Stage) {
    setBusy(stage);
    setError(null);
    try {
      if (stage === "swot") setSwot(await api.runSwot(companyId));
      if (stage === "matrix") setMatrix(await api.runAttractiveness(companyId));
      if (stage === "pricing") {
        setPricing(
          await api.runPricing(companyId, {
            cost_base: Number(costBase),
            // The API takes a fraction; the form takes percent, because
            // "40" is what a human types for a 40% target.
            target_margin_pct: Number(margin) / 100,
            margin_basis: basis,
          }),
        );
      }
      if (stage === "report") setReport(await api.runReport(companyId));
      if (stage === "porters") setPorters(await api.runPorters(companyId));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function createScenario(body: {
    name: string;
    description?: string;
    overrides: Record<string, unknown>;
  }) {
    setBusy("scenario");
    setError(null);
    try {
      const created = await api.createScenario(companyId, body);
      setScenarios((prev) => [...prev, created]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function removeScenario(scenarioId: string) {
    try {
      await api.deleteScenario(companyId, scenarioId);
      setScenarios((prev) => prev.filter((s) => s.id !== scenarioId));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (!company) {
    return (
      <p className="panel p-6 text-sm text-slate-400">
        {error ?? "Loading…"}{" "}
        <Link to="/" className="text-accent">
          Back
        </Link>
      </p>
    );
  }

  return (
    <div className="space-y-8">
      <header className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-slate-100">{company.name}</h1>
            <p className="text-xs text-slate-500">
              {company.industry ?? "industry unspecified"} · {competitors.length} competitor(s)
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            {company.entity_key && (
              <Link to={`/entities/${company.entity_key}`} className="btn-ghost">
                Timeline
              </Link>
            )}
            <Link to="/" className="btn-ghost">
              All companies
            </Link>
          </div>
        </div>
        {company.period_label && (
          <p className="mt-2 text-xs text-slate-400">
            Period <span className="text-slate-200">{company.period_label}</span>
            {company.period_end ? ` (ends ${company.period_end})` : ""} ·{" "}
            <span className="font-mono text-slate-500">{company.entity_key}</span>
          </p>
        )}
        <p className="mt-3 border-t border-edge pt-3 text-xs leading-relaxed text-slate-500">
          <span className="text-slate-400">Source:</span> {company.data_source}
        </p>
      </header>

      {error && <p className="panel border-negative/40 p-3 text-xs text-negative">{error}</p>}

      <StageShell
        index={1}
        title="SWOT scoring"
        subtitle="Financial metrics compared against the peer-set median (or the industry band when there are too few peers), bucketed into 1-5 impact scores. Metrics inside the neutral band produce no factor."
        action={
          <button className="btn-primary" onClick={() => void run("swot")} disabled={busy !== null}>
            {busy === "swot" ? "Scoring…" : swot ? "Re-run" : "Run SWOT"}
          </button>
        }
      >
        {swot ? (
          <SWOTGrid analysis={swot} />
        ) : (
          <p className="panel p-5 text-sm text-slate-500">Not run yet.</p>
        )}
      </StageShell>

      <StageShell
        index={2}
        title="GE-McKinsey matrix"
        subtitle="Market attractiveness from growth, size, industry profitability, and HHI-derived competitive intensity. Competitive strength from the scored SWOT grid."
        action={
          <button
            className="btn-primary"
            onClick={() => void run("matrix")}
            disabled={busy !== null || !swot}
            title={swot ? undefined : "Run the SWOT analysis first"}
          >
            {busy === "matrix" ? "Computing…" : matrix ? "Re-run" : "Run matrix"}
          </button>
        }
      >
        {matrix ? (
          <AttractivenessMatrix result={matrix} />
        ) : (
          <p className="panel p-5 text-sm text-slate-500">
            {swot ? "Not run yet." : "Blocked: the strength axis comes from the SWOT grid."}
          </p>
        )}
      </StageShell>

      <StageShell
        index={3}
        title="Pricing"
        subtitle="Cost-plus anchor blended with the competitor benchmark, then adjusted for the shared-feature quality gap and floored at cost."
        action={
          <button
            className="btn-primary"
            onClick={() => void run("pricing")}
            disabled={busy !== null}
          >
            {busy === "pricing" ? "Pricing…" : pricing ? "Re-run" : "Run pricing"}
          </button>
        }
      >
        <div className="panel grid gap-3 p-4 sm:grid-cols-3">
          <div>
            <label className="label" htmlFor="cost">
              Cost base
            </label>
            <input
              id="cost"
              className="field font-mono"
              inputMode="decimal"
              value={costBase}
              onChange={(e) => setCostBase(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="margin">
              Target margin %
            </label>
            <input
              id="margin"
              className="field font-mono"
              inputMode="decimal"
              value={margin}
              onChange={(e) => setMargin(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="basis">
              Basis
            </label>
            <select
              id="basis"
              className="field"
              value={basis}
              onChange={(e) => setBasis(e.target.value)}
            >
              <option value="MARGIN">MARGIN — cost / (1 − m)</option>
              <option value="MARKUP">MARKUP — cost × (1 + m)</option>
            </select>
          </div>
        </div>
        {pricing ? (
          <PricingView result={pricing} />
        ) : (
          <p className="panel p-5 text-sm text-slate-500">Not run yet.</p>
        )}
      </StageShell>

      <StageShell
        index={4}
        title="Executive report"
        subtitle="The structured context is frozen from the stages above, then narrated. With no API key configured, the templated fallback produces the same numbers without the prose."
        action={
          <button
            className="btn-primary"
            onClick={() => void run("report")}
            disabled={busy !== null || !matrix}
            title={matrix ? undefined : "Run the matrix first"}
          >
            {busy === "report" ? "Generating…" : report ? "Re-generate" : "Generate report"}
          </button>
        }
      >
        {report ? (
          <ReportView report={report} />
        ) : (
          <p className="panel p-5 text-sm text-slate-500">
            {matrix ? "Not generated yet." : "Blocked: there is nothing computed to narrate."}
          </p>
        )}
      </StageShell>

      <StageShell
        index={5}
        title="Porter's Five Forces"
        subtitle="Industry structure rather than firm position, so it needs no upstream stage. Rivalry is computed from HHI; two of the five forces have no proxy in this data and are analyst input or nothing."
        action={
          <button
            className="btn-primary"
            onClick={() => void run("porters")}
            disabled={busy !== null}
          >
            {busy === "porters" ? "Scoring…" : porters ? "Re-run" : "Run five forces"}
          </button>
        }
      >
        {porters ? (
          <PortersView analysis={porters} />
        ) : (
          <p className="panel p-5 text-sm text-slate-500">Not run yet.</p>
        )}
      </StageShell>

      <StageShell
        index={6}
        title="Sensitivity"
        subtitle="The minimum change in any single input that would flip the quadrant. Solved exactly rather than searched, because the attractiveness score is linear in its axes."
        action={<span className="text-xs text-slate-600">derived from the stored matrix</span>}
      >
        {sensitivity ? (
          <SensitivityPanel result={sensitivity} />
        ) : (
          <p className="panel p-5 text-sm text-slate-500">
            {matrix ? "Re-run the matrix to refresh this." : "Blocked: needs a matrix result."}
          </p>
        )}
      </StageShell>

      <StageShell
        index={7}
        title="What-if scenarios"
        subtitle="Recompute the pipeline under a named set of overrides and diff against the stored baseline. Nothing here mutates the company."
        action={<span className="text-xs text-slate-600">{scenarios.length} saved</span>}
      >
        {matrix ? (
          <ScenarioPanel
            scenarios={scenarios}
            busy={busy === "scenario"}
            onCreate={createScenario}
            onDelete={removeScenario}
          />
        ) : (
          <p className="panel p-5 text-sm text-slate-500">
            Blocked: a scenario is a delta from a baseline placement.
          </p>
        )}
      </StageShell>
    </div>
  );
}
