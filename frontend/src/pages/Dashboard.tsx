import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { Company, Methodology } from "../api/types";
import { CASE_STUDIES } from "../data/caseStudies";

export default function Dashboard() {
  const navigate = useNavigate();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [methodology, setMethodology] = useState<Methodology | null>(null);
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
    <div className="space-y-6">
      <section className="panel p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Load an illustrative case
        </h2>
        <p className="mt-1 text-xs leading-relaxed text-slate-500">
          These are composites, not real companies — they exist to exercise the pipeline.
          Replace them with figures from an annual report or a published case study before
          drawing any conclusion.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {CASE_STUDIES.map((study) => (
            <button
              key={study.key}
              onClick={() => void loadCaseStudy(study.key)}
              disabled={seeding !== null}
              className="panel p-4 text-left transition hover:border-accent/50 disabled:opacity-40"
            >
              <span className="block text-sm font-medium text-slate-100">{study.label}</span>
              <span className="mt-1 block text-xs leading-relaxed text-slate-400">
                {study.summary}
              </span>
              {seeding === study.key && (
                <span className="mt-2 block text-xs text-accent">Loading…</span>
              )}
            </button>
          ))}
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
            Companies
          </h2>
          <Link to="/new" className="btn-primary">
            New company
          </Link>
        </div>

        {error && (
          <p className="panel mb-3 border-negative/40 p-3 text-xs text-negative">{error}</p>
        )}

        {companies.length === 0 ? (
          <p className="panel p-6 text-sm text-slate-500">
            Nothing analysed yet. Load a case above or enter a company by hand.
          </p>
        ) : (
          <ul className="space-y-2">
            {companies.map((company) => (
              <li key={company.id} className="panel flex items-center justify-between p-4">
                <Link to={`/companies/${company.id}`} className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-slate-100 hover:text-accent">
                    {company.name}
                  </span>
                  <span className="block truncate text-xs text-slate-500">
                    {company.industry ?? "industry unspecified"} · {company.data_source}
                  </span>
                </Link>
                <button
                  onClick={() => void remove(company.id)}
                  className="btn-ghost ml-4 shrink-0 text-xs"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {methodology && (
        <details className="panel p-5">
          <summary className="cursor-pointer text-sm font-semibold uppercase tracking-wider text-slate-300">
            Methodology in force
          </summary>
          <ul className="mt-3 space-y-1 text-xs text-slate-400">
            {methodology.frameworks.map((framework) => (
              <li key={framework}>· {framework}</li>
            ))}
          </ul>
          <p className="mt-3 text-xs leading-relaxed text-slate-500">
            {methodology.llm_role}
          </p>
          <p className="mt-2 text-xs leading-relaxed text-caution/80">
            {methodology.benchmark_provenance}
          </p>
        </details>
      )}
    </div>
  );
}
