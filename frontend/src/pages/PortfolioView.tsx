import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { AllocationRun, Company, Portfolio } from "../api/types";
import PortfolioGrid from "../components/PortfolioGrid";

/** Build a portfolio from scored company-periods, then allocate a budget over it. */

interface Draft {
  company_id: string;
  revenue: string;
  capital_requested: string;
  capital_floor: string;
}

function Builder({ onCreated }: { onCreated: (portfolio: Portfolio) => void }) {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [name, setName] = useState("");
  const [budget, setBudget] = useState("");
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .listCompanies({ limit: 200 })
      .then((page) => setCompanies(page.items))
      .catch(() => setCompanies([]));
  }, []);

  function toggle(company: Company) {
    setDrafts((prev) => {
      const next = { ...prev };
      if (next[company.id]) delete next[company.id];
      else
        next[company.id] = {
          company_id: company.id,
          revenue: "",
          capital_requested: "",
          capital_floor: "0",
        };
      return next;
    });
  }

  function patch(id: string, field: keyof Draft, value: string) {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], [field]: value } }));
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const portfolio = await api.createPortfolio({
        name,
        budget: Number(budget),
        members: Object.values(drafts).map((draft) => ({
          company_id: draft.company_id,
          revenue: draft.revenue === "" ? null : Number(draft.revenue),
          capital_requested: Number(draft.capital_requested || 0),
          capital_floor: Number(draft.capital_floor || 0),
        })),
      });
      onCreated(portfolio);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const selected = Object.keys(drafts).length;

  return (
    <div className="panel p-5">
      <h2 className="text-sm font-semibold text-slate-100">New portfolio</h2>
      <p className="mt-1 text-xs leading-relaxed text-slate-500">
        GE-McKinsey was built by McKinsey for General Electric to allocate capital
        across business units. Two or more units, because a portfolio of one is the
        single-company view every other page already gives you.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        <input
          className="field max-w-xs"
          placeholder="Portfolio name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          className="field max-w-[10rem]"
          placeholder="Budget"
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
        />
      </div>

      <div className="mt-4 max-h-80 overflow-y-auto rounded-md border border-edge">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-panel text-slate-500">
            <tr>
              <th className="p-2 font-normal">Unit</th>
              <th className="p-2 font-normal">Revenue</th>
              <th className="p-2 font-normal">Requested</th>
              <th className="p-2 font-normal">Floor</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-edge/40">
            {companies.map((company) => {
              const draft = drafts[company.id];
              return (
                <tr key={company.id}>
                  <td className="p-2">
                    <label className="flex cursor-pointer items-center gap-2">
                      <input
                        type="checkbox"
                        checked={Boolean(draft)}
                        onChange={() => toggle(company)}
                      />
                      <span className="text-slate-200">{company.name}</span>
                      {company.period_label && (
                        <span className="text-2xs text-slate-600">
                          {company.period_label}
                        </span>
                      )}
                    </label>
                  </td>
                  {(["revenue", "capital_requested", "capital_floor"] as const).map((field) => (
                    <td key={field} className="p-2">
                      <input
                        className="field w-24 py-1"
                        disabled={!draft}
                        value={draft?.[field] ?? ""}
                        onChange={(e) => patch(company.id, field, e.target.value)}
                      />
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {error && <p className="mt-3 text-xs text-negative">{error}</p>}

      <button
        className="btn-primary mt-4"
        disabled={busy || selected < 2 || !name || !budget}
        onClick={() => void submit()}
      >
        {busy ? "Creating…" : `Create portfolio (${selected} units)`}
      </button>
      {selected === 1 && (
        <span className="ml-2 text-2xs text-slate-600">Select at least two units.</span>
      )}
    </div>
  );
}

export default function PortfolioView() {
  const { portfolioId } = useParams();
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [active, setActive] = useState<Portfolio | null>(null);
  const [runs, setRuns] = useState<AllocationRun[]>([]);
  const [budgetOverride, setBudgetOverride] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const all = await api.listPortfolios().catch(() => []);
    setPortfolios(all);
    const chosen = portfolioId
      ? all.find((p) => p.id === portfolioId) ?? null
      : all[all.length - 1] ?? null;
    setActive(chosen);
    setRuns(chosen ? await api.listAllocations(chosen.id).catch(() => []) : []);
  }, [portfolioId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function allocate() {
    if (!active) return;
    setBusy(true);
    setError(null);
    try {
      const run = await api.allocate(active.id, {
        budget: budgetOverride === "" ? undefined : Number(budgetOverride),
      });
      setRuns((prev) => [...prev, run]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const latest = runs.length ? runs[runs.length - 1] : null;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Portfolio allocation</h1>
          <p className="text-xs text-slate-500">
            N business units on one grid, competing for one budget.
          </p>
        </div>
        <Link to="/" className="btn-ghost">
          All companies
        </Link>
      </header>

      {portfolios.length > 0 && (
        <div className="panel flex flex-wrap items-center gap-2 p-4">
          <span className="label mb-0">Portfolio</span>
          <select
            className="field max-w-xs"
            value={active?.id ?? ""}
            onChange={(e) => {
              const chosen = portfolios.find((p) => p.id === e.target.value) ?? null;
              setActive(chosen);
              setRuns([]);
              if (chosen) void api.listAllocations(chosen.id).then(setRuns).catch(() => setRuns([]));
            }}
          >
            {portfolios.map((portfolio) => (
              <option key={portfolio.id} value={portfolio.id}>
                {portfolio.name} ({portfolio.members.length} units, budget {portfolio.budget})
              </option>
            ))}
          </select>
          <input
            className="field w-32"
            placeholder={active ? `${active.budget}` : "budget"}
            value={budgetOverride}
            onChange={(e) => setBudgetOverride(e.target.value)}
          />
          <button className="btn-primary" disabled={busy || !active} onClick={() => void allocate()}>
            {busy ? "Allocating…" : "Allocate"}
          </button>
          <span className="text-2xs text-slate-600">
            {runs.length === 1 ? "1 stored run" : `${runs.length} stored runs`}. A blank
            budget uses the portfolio&rsquo;s own.
          </span>
        </div>
      )}

      {error && <p className="panel border-negative/40 p-3 text-xs text-negative">{error}</p>}

      {latest ? (
        <PortfolioGrid run={latest} />
      ) : (
        active && (
          <p className="panel p-5 text-sm text-slate-500">
            No allocation run yet. Every member needs a market attractiveness result
            first — an unscored unit has no position to rank.
          </p>
        )
      )}

      <Builder
        onCreated={(portfolio) => {
          setPortfolios((prev) => [...prev, portfolio]);
          setActive(portfolio);
          setRuns([]);
        }}
      />
    </div>
  );
}
