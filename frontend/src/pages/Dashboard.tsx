import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { BenchmarkProvenance, Company, Methodology } from "../api/types";
import { CASE_STUDIES } from "../data/caseStudies";

/**
 * The landing screen answers two questions before anything else: what is
 * loaded, and where do the benchmarks come from.
 *
 * The second one is deliberately given a whole strip at the top. "Are these
 * numbers real" is the first thing anyone should ask of a tool like this, and
 * it is now answerable at a glance rather than by reading a caveats section.
 */

function ProvenanceStrip({ provenance }: { provenance: BenchmarkProvenance | null }) {
  if (!provenance) return null;
  const detail = provenance.detail;
  const real = provenance.is_edgar_sourced;

  return (
    <section className="panel overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-edge/70 px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span className={`chip ${real ? "chip-positive" : "chip-caution"}`}>
            {real ? "Sourced" : "Placeholder"}
          </span>
          <span className="text-sm font-medium text-slate-100">
            {real ? "Benchmarks from SEC XBRL filings" : "Benchmarks are illustrative bands"}
          </span>
        </div>
        <code className="text-2xs text-slate-600">GET /benchmarks/provenance</code>
      </div>

      {real && detail ? (
        <dl className="grid grid-cols-2 divide-x divide-edge/50 sm:grid-cols-4">
          {[
            ["Period", String(detail.period ?? "—")],
            ["Filers considered", Number(detail.companies_considered ?? 0).toLocaleString()],
            ["Sectors published", String(provenance.sector_count)],
            ["Minimum sample", `n ≥ ${detail.min_sector_n ?? "?"}`],
          ].map(([label, value]) => (
            <div key={label} className="px-5 py-3">
              <dt className="label mb-1">{label}</dt>
              <dd className="num text-sm font-semibold text-slate-100">{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="px-5 py-3 text-xs leading-relaxed text-slate-500">
          {provenance.provenance}
        </p>
      )}
    </section>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [methodology, setMethodology] = useState<Methodology | null>(null);
  const [provenance, setProvenance] = useState<BenchmarkProvenance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seeding, setSeeding] = useState<string | null>(null);

  async function refresh() {
    try {
      setCompanies(await api.listCompanies());
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    void refresh();
    api.methodology().then(setMethodology).catch(() => undefined);
    api.benchmarkProvenance().then(setProvenance).catch(() => undefined);
  }, []);

  async function loadCaseStudy(key: string) {
    const study = CASE_STUDIES.find((c) => c.key === key);
    if (!study) return;
    setSeeding(key);
    setError(null);
    try {
      const company = await api.createCompany(study.company);
      for (const competitor of study.competitors) {
        await api.addCompetitor(company.id, competitor);
      }
      navigate(`/companies/${company.id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSeeding(null);
    }
  }

  async function remove(id: string) {
    try {
      await api.deleteCompany(id);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="animate-fade-up space-y-7">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-50">
          Executive decision intelligence
        </h1>
        <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-slate-400">
          A SWOT grid computed from benchmarks, a GE-McKinsey placement with its
          uncertainty, and a portfolio allocation you can audit line by line. The model
          narrates; it does not decide.
        </p>
      </div>

      <ProvenanceStrip provenance={provenance} />

      {error && (
        <p className="panel border-negative/40 bg-negative/5 p-3 text-xs text-negative">
          {error}
        </p>
      )}

      <section>
        <div className="mb-3 flex items-baseline justify-between gap-4">
          <h2 className="section-title">Load an illustrative case</h2>
          <p className="text-2xs text-slate-600">composites, not real companies</p>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {CASE_STUDIES.map((study) => (
            <button
              key={study.key}
              onClick={() => void loadCaseStudy(study.key)}
              disabled={seeding !== null}
              className="panel card-interactive group p-4 text-left disabled:opacity-40"
            >
              <span className="flex items-start justify-between gap-2">
                <span className="text-sm font-semibold text-slate-100">{study.label}</span>
                <span
                  aria-hidden="true"
                  className="text-slate-700 transition-colors duration-200 group-hover:text-accent"
                >
                  →
                </span>
              </span>
              <span className="mt-1.5 block text-xs leading-relaxed text-slate-500">
                {study.summary}
              </span>
              {seeding === study.key && (
                <span className="mt-2 block text-2xs font-semibold uppercase tracking-label text-accent">
                  Loading…
                </span>
              )}
            </button>
          ))}
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between gap-4">
          <h2 className="section-title">
            Companies
            <span className="num ml-2 text-xs font-normal text-slate-600">
              {companies.length}
            </span>
          </h2>
          <div className="flex gap-2">
            {companies.length >= 2 && (
              <Link to="/portfolios" className="btn-ghost">
                Build a portfolio
              </Link>
            )}
            <Link to="/new" className="btn-primary">
              New company
            </Link>
          </div>
        </div>

        {companies.length === 0 ? (
          <div className="panel p-10 text-center">
            <p className="text-sm text-slate-300">Nothing analysed yet.</p>
            <p className="mx-auto mt-1 max-w-sm text-xs leading-relaxed text-slate-500">
              Load one of the cases above to exercise the whole pipeline in a click, or
              enter a company from a filing by hand.
            </p>
          </div>
        ) : (
          <ul className="panel divide-y divide-edge/60 overflow-hidden">
            {companies.map((company) => (
              <li
                key={company.id}
                className="group flex items-center gap-4 px-4 py-3 transition-colors duration-150 hover:bg-panel-2/70"
              >
                <Link to={`/companies/${company.id}`} className="min-w-0 flex-1 rounded-md">
                  <span className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium text-slate-100 transition-colors group-hover:text-accent">
                      {company.name}
                    </span>
                    {company.industry && (
                      <span className="chip chip-neutral shrink-0">{company.industry}</span>
                    )}
                    {company.period_label && (
                      <span className="num shrink-0 text-2xs text-slate-600">
                        {company.period_label}
                      </span>
                    )}
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-slate-600">
                    {company.data_source}
                  </span>
                </Link>
                <button
                  onClick={() => void remove(company.id)}
                  className="btn-danger shrink-0 opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100"
                  aria-label={`Delete ${company.name}`}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {methodology && (
        <details className="panel group px-5 py-4">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
            <span className="section-title">Methodology in force</span>
            <span className="text-2xs text-slate-600 transition-transform duration-200 group-open:rotate-90">
              ▸
            </span>
          </summary>
          <ul className="mt-4 grid gap-1.5 sm:grid-cols-2">
            {methodology.frameworks.map((framework) => (
              <li key={framework} className="flex gap-2 text-xs text-slate-400">
                <span className="text-accent/60">—</span>
                {framework}
              </li>
            ))}
          </ul>
          <p className="mt-4 border-t border-edge/60 pt-3 text-xs leading-relaxed text-slate-500">
            {methodology.llm_role}
          </p>
        </details>
      )}
    </div>
  );
}
