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
  ThreePoint,
  UncertaintyAnalysis,
} from "../api/types";
import AttractivenessMatrix from "../components/AttractivenessMatrix";
import PortersView from "../components/PortersView";
import ScenarioPanel from "../components/ScenarioPanel";
import PricingView from "../components/PricingView";
import ReportView from "../components/ReportView";
import SensitivityPanel from "../components/SensitivityPanel";
import SWOTGrid from "../components/SWOTGrid";
import UncertaintyPanel from "../components/UncertaintyPanel";

type Stage =
  | "swot"
  | "matrix"
  | "pricing"
  | "report"
  | "porters"
  | "scenario"
  | "uncertainty";

function StageShell({
  index,
  title,
  subtitle,
  action,
  done,
  children,
}: {
  index: number;
  title: string;
  subtitle: string;
  action: React.ReactNode;
  done?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <section className="space-y-3 scroll-mt-20">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 gap-3">
          {/* The step number carries whether the stage has run, so the page
              reads as a pipeline with progress rather than a list of panels. */}
          <span
            aria-hidden="true"
            className={[
              "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border text-2xs font-semibold",
              done
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-edge bg-panel-2 text-slate-600",
            ].join(" ")}
          >
            {index}
          </span>
          <div className="min-w-0">
            <h2 className="section-title">{title}</h2>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-slate-500">{subtitle}</p>
          </div>
        </div>
        <div className="shrink-0">{action}</div>
      </div>
      <div className="pl-0 sm:pl-9">{children}</div>
    </section>
  );
}

function NotRun({ children }: { children: React.ReactNode }) {
  return (
    <div className="panel border-dashed p-6 text-center">
      <p className="text-xs text-slate-500">{children}</p>
    </div>
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
  const [uncertainty, setUncertainty] = useState<UncertaintyAnalysis | null>(null);

  const [costBase, setCostBase] = useState("100");
  const [margin, setMargin] = useState("40");
  const [basis, setBasis] = useState("MARGIN");

  const [busy, setBusy] = useState<Stage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [c, comps, s, m, p, r, pf, sc, unc] = await Promise.all([
        api.getCompany(companyId),
        api.listCompetitors(companyId),
        optional(api.getSwot(companyId)),
        optional(api.getAttractiveness(companyId)),
        optional(api.getPricing(companyId)),
        optional(api.getReport(companyId)),
        optional(api.getPorters(companyId)),
        api.listScenarios(companyId),
        optional(api.getUncertainty(companyId)),
      ]);
      setCompany(c);
      setCompetitors(comps);
      setSwot(s);
      setMatrix(m);
      setPricing(p);
      setReport(r);
      setPorters(pf);
      setScenarios(sc);
      setUncertainty(unc);
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

  async function runUncertainty(inputs: Record<string, ThreePoint> | undefined) {
    setBusy("uncertainty");
    setError(null);
    try {
      setUncertainty(
        await api.runUncertainty(companyId, {
          uncertainty_inputs: inputs,
          // Stated ranges are persisted so the next run of this company starts
          // from the same assumptions rather than from nothing.
          persist_inputs: inputs !== undefined,
        }),
      );
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
      <div className="panel p-10 text-center">
        <p className="text-sm text-slate-400">{error ?? "Loading…"}</p>
        <Link to="/" className="btn-ghost mt-4">
          Back to companies
        </Link>
      </div>
    );
  }

  return (
    <div className="animate-fade-up space-y-10">
      <header className="panel overflow-hidden">
        <div className="flex flex-wrap items-start justify-between gap-4 p-5">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold tracking-tight text-slate-50">
              {company.name}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {company.industry && <span className="chip chip-neutral">{company.industry}</span>}
              <span className="chip chip-neutral">
                {competitors.length} competitor{competitors.length === 1 ? "" : "s"}
              </span>
              {company.period_label && (
                <span className="chip chip-neutral">
                  {company.period_label}
                  {company.period_end ? ` · ends ${company.period_end}` : ""}
                </span>
              )}
            </div>
          </div>
          <div className="flex shrink-0 gap-2">
            {company.entity_key && (
              <Link to={`/entities/${company.entity_key}`} className="btn-ghost">
                Timeline
              </Link>
            )}
            <Link to="/portfolios" className="btn-ghost">
              Portfolio
            </Link>
          </div>
        </div>

        {/* Headline figures, once the matrix exists. An executive reading this
            page should not have to scroll to find the verdict. */}
        {matrix && (
          <dl className="grid grid-cols-2 divide-x divide-edge/40 border-t border-edge/70 sm:grid-cols-4">
            {[
              ["Attractiveness", matrix.overall_attractiveness_score.toFixed(2)],
              ["Strength", matrix.competitive_strength_score.toFixed(2)],
              ["Quadrant", matrix.quadrant.replace(/_/g, " ")],
              [
                "Stability",
                uncertainty
                  ? `${uncertainty.verdict_stability} · ${uncertainty.entropy_bits.toFixed(2)} bits`
                  : "not sampled",
              ],
            ].map(([label, value], i) => (
              <div key={label} className="px-5 py-3">
                <dt className="label mb-1">{label}</dt>
                <dd
                  className={[
                    "truncate text-sm font-semibold",
                    i < 2 ? "num text-slate-50" : "text-slate-200",
                  ].join(" ")}
                >
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        )}

        <p className="border-t border-edge/70 px-5 py-3 text-2xs leading-relaxed text-slate-600">
          <span className="font-semibold uppercase tracking-label text-slate-500">Source</span>{" "}
          {company.data_source}
        </p>
      </header>

      {error && (
        <p className="panel border-negative/40 bg-negative/5 p-3 text-xs text-negative">
          {error}
        </p>
      )}

      <StageShell
        index={1}
        done={Boolean(swot)}
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
          <NotRun>Not run yet.</NotRun>
        )}
      </StageShell>

      <StageShell
        index={2}
        done={Boolean(matrix)}
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
        done={Boolean(pricing)}
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
          <NotRun>Not run yet.</NotRun>
        )}
      </StageShell>

      <StageShell
        index={4}
        done={Boolean(report)}
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
        done={Boolean(porters)}
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
          <NotRun>Not run yet.</NotRun>
        )}
      </StageShell>

      <StageShell
        index={6}
        done={Boolean(sensitivity)}
        title="Sensitivity"
        subtitle="The minimum change in any single input that would flip the quadrant. Solved exactly rather than searched, because the attractiveness score is linear in its axes."
        action={<span className="text-xs text-slate-600">derived from the stored matrix</span>}
      >
        {sensitivity ? (
          <SensitivityPanel result={sensitivity} />
        ) : (
          <NotRun>
            {matrix ? "Re-run the matrix to refresh this." : "Blocked: needs a matrix result."}
          </NotRun>
        )}
      </StageShell>

      <StageShell
        index={7}
        done={Boolean(uncertainty)}
        title="Uncertainty"
        subtitle="Every input above is a point estimate. State a range for any of them and 10,000 seeded draws report how likely each quadrant is, with the Shannon entropy of that distribution as a single measure of how much the verdict survives."
        action={<span className="text-xs text-slate-600">needs a matrix result</span>}
      >
        {matrix ? (
          <UncertaintyPanel
            result={uncertainty}
            busy={busy === "uncertainty"}
            onRun={(inputs) => void runUncertainty(inputs)}
          />
        ) : (
          <NotRun>Blocked: the Monte Carlo resamples a stored placement.</NotRun>
        )}
      </StageShell>

      <StageShell
        index={8}
        done={scenarios.length > 0}
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
          <NotRun>Blocked: a scenario is a delta from a baseline placement.</NotRun>
        )}
      </StageShell>
    </div>
  );
}
