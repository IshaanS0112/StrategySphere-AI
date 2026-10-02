import { useState } from "react";

import type { Scenario } from "../api/types";

/** Build a what-if, then read the delta against the stored baseline. */

const MARKET_FIELDS: { key: string; label: string }[] = [
  { key: "market_growth_pct", label: "Market growth %" },
  { key: "market_size_usd_bn", label: "Market size $bn" },
  { key: "industry_operating_margin_pct", label: "Industry margin %" },
];

interface Props {
  scenarios: Scenario[];
  busy: boolean;
  onCreate: (body: {
    name: string;
    description?: string;
    overrides: Record<string, unknown>;
  }) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

function DeltaRow({
  field,
  entry,
}: {
  field: string;
  entry: { baseline: any; scenario: any; delta?: number };
}) {
  const numeric = typeof entry.delta === "number";
  const worse = numeric && (entry.delta as number) < 0;
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-xs text-slate-400">{field.replace(/_/g, " ")}</span>
      <span className="num text-xs">
        <span className="text-slate-500">{String(entry.baseline)}</span>
        <span className="mx-1.5 text-slate-600">→</span>
        <span className="text-slate-200">{String(entry.scenario)}</span>
        {numeric && (
          <span className={`ml-2 ${worse ? "text-negative" : "text-positive"}`}>
            {(entry.delta as number) > 0 ? "+" : ""}
            {(entry.delta as number).toFixed(2)}
          </span>
        )}
      </span>
    </div>
  );
}

export default function ScenarioPanel({ scenarios, busy, onCreate, onDelete }: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [market, setMarket] = useState<Record<string, string>>({});
  const [entrantShare, setEntrantShare] = useState("");
  const [removeName, setRemoveName] = useState("");

  function buildOverrides(): Record<string, unknown> {
    const marketData: Record<string, number> = {};
    for (const [key, raw] of Object.entries(market)) {
      const value = Number(raw.trim());
      if (raw.trim() !== "" && Number.isFinite(value)) marketData[key] = value;
    }
    const competitors: Record<string, unknown>[] = [];
    const share = Number(entrantShare.trim());
    if (entrantShare.trim() !== "" && Number.isFinite(share)) {
      competitors.push({
        op: "add",
        competitor_name: "Scenario entrant",
        market_share_pct: share,
      });
    }
    if (removeName.trim()) {
      competitors.push({ op: "remove", competitor_name: removeName.trim() });
    }

    const overrides: Record<string, unknown> = {};
    if (Object.keys(marketData).length) overrides.market_data = marketData;
    if (competitors.length) overrides.competitors = competitors;
    return overrides;
  }

  const overrides = buildOverrides();
  const canSubmit = name.trim().length > 0 && Object.keys(overrides).length > 0 && !busy;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    await onCreate({
      name: name.trim(),
      description: description.trim() || undefined,
      overrides,
    });
    setName("");
    setDescription("");
    setMarket({});
    setEntrantShare("");
    setRemoveName("");
  }

  return (
    <div className="space-y-3">
      <form onSubmit={submit} className="panel space-y-4 p-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="scenario-name">
              Scenario name
            </label>
            <input
              id="scenario-name"
              className="field"
              placeholder="Market cools and a funded entrant arrives"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="scenario-desc">
              Description
            </label>
            <input
              id="scenario-desc"
              className="field"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        </div>

        <div>
          <span className="label">Market overrides</span>
          <div className="grid gap-3 sm:grid-cols-3">
            {MARKET_FIELDS.map((field) => (
              <div key={field.key}>
                <input
                  className="field font-mono"
                  inputMode="decimal"
                  placeholder={field.label}
                  value={market[field.key] ?? ""}
                  onChange={(e) =>
                    setMarket((prev) => ({ ...prev, [field.key]: e.target.value }))
                  }
                />
              </div>
            ))}
          </div>
          <p className="mt-1 text-xs text-slate-600">
            Leave blank to keep the baseline value.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="entrant">
              Add an entrant at % share
            </label>
            <input
              id="entrant"
              className="field font-mono"
              inputMode="decimal"
              placeholder="15"
              value={entrantShare}
              onChange={(e) => setEntrantShare(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="remove">
              Remove a competitor by name
            </label>
            <input
              id="remove"
              className="field"
              placeholder="Rival A"
              value={removeName}
              onChange={(e) => setRemoveName(e.target.value)}
            />
          </div>
        </div>

        <button className="btn-primary" disabled={!canSubmit}>
          {busy ? "Running…" : "Run scenario"}
        </button>
      </form>

      {scenarios.length === 0 ? (
        <p className="panel p-5 text-sm text-slate-500">No scenarios run yet.</p>
      ) : (
        scenarios
          .slice()
          .reverse()
          .map((scenario) => (
            <section key={scenario.id} className="panel p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h4 className="text-sm font-medium text-slate-100">{scenario.name}</h4>
                  {scenario.description && (
                    <p className="text-xs text-slate-500">{scenario.description}</p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span
                    className={`chip ${
                      scenario.quadrant_changed
                        ? "border-caution/50 text-caution"
                        : "border-edge text-slate-500"
                    }`}
                  >
                    {scenario.quadrant_changed ? "quadrant moved" : "quadrant held"}
                  </span>
                  <button
                    onClick={() => void onDelete(scenario.id)}
                    className="btn-ghost text-xs"
                  >
                    Delete
                  </button>
                </div>
              </div>

              <p className="mt-2 text-sm text-slate-300">
                {scenario.scenario_result?.narrative}
              </p>

              {Object.keys(scenario.delta).length > 0 ? (
                <div className="mt-3 divide-y divide-edge/40 border-t border-edge pt-2">
                  {Object.entries(scenario.delta).map(([field, entry]) => (
                    <DeltaRow key={field} field={field} entry={entry} />
                  ))}
                </div>
              ) : (
                <p className="mt-3 border-t border-edge pt-3 text-xs text-caution/90">
                  Nothing moved. Only fields that actually changed are listed, so an
                  empty delta means the overrides had no effect on any scored output.
                </p>
              )}

              {(scenario.scenario_result?.warnings ?? []).length > 0 && (
                <ul className="mt-3 space-y-1 border-t border-edge pt-3">
                  {scenario.scenario_result.warnings.map((w: string, i: number) => (
                    <li key={i} className="text-xs leading-relaxed text-caution/90">
                      {w}
                    </li>
                  ))}
                </ul>
              )}

              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-slate-500">
                  Overrides applied
                </summary>
                <pre className="mt-2 overflow-auto rounded bg-ink p-3 num text-2xs text-slate-400">
                  {JSON.stringify(scenario.overrides, null, 2)}
                </pre>
              </details>
            </section>
          ))
      )}
    </div>
  );
}
