import type { AllocationEntry, AllocationRun } from "../api/types";

/**
 * Every business unit on one GE-McKinsey grid, sized by revenue, filled by
 * what the allocator did with it.
 *
 * This is the framework used for the job McKinsey built it for: GE had roughly
 * forty business units and needed to decide which to feed. Scoring one company
 * is the degenerate case, and this is the screen a capital committee actually
 * looks at.
 *
 * Bubble **area** is proportional to revenue, not radius. Mapping revenue to
 * radius exaggerates every difference by squaring it, which is the oldest way
 * to make a chart lie without writing a false number on it.
 */

const SIZE = 420;
const PAD = 46;
const MIN = 1;
const MAX = 5;
const LOW = 2.5;
const HIGH = 3.5;

const OUTCOME_FILL: Record<string, string> = {
  FUNDED: "#4ade80",
  PARTIALLY_FUNDED: "#fbbf24",
  FLOOR_ONLY: "#f97316",
  UNFUNDED: "#f87171",
  CONTRIBUTOR: "#60a5fa",
};

const OUTCOME_COPY: Record<string, string> = {
  FUNDED: "received its full request",
  PARTIALLY_FUNDED: "the budget ran out inside this unit",
  FLOOR_ONLY: "kept operating, nothing discretionary",
  UNFUNDED: "nothing available by the time priority reached it",
  CONTRIBUTOR: "HARVEST_DIVEST — funds the pool rather than drawing from it",
};

function scaleX(value: number) {
  return PAD + ((value - MIN) / (MAX - MIN)) * (SIZE - 2 * PAD);
}

function scaleY(value: number) {
  // SVG y grows downward; attractiveness should grow upward.
  return SIZE - PAD - ((value - MIN) / (MAX - MIN)) * (SIZE - 2 * PAD);
}

/** Radius from revenue, with AREA proportional to revenue. */
function radiusFor(revenue: number | null, maxRevenue: number): number {
  const MIN_R = 6;
  const MAX_R = 26;
  if (!revenue || revenue <= 0 || maxRevenue <= 0) return MIN_R;
  return MIN_R + (MAX_R - MIN_R) * Math.sqrt(revenue / maxRevenue);
}

function money(value: number): string {
  if (Math.abs(value) >= 1e9) return `${(value / 1e9).toFixed(2)}bn`;
  if (Math.abs(value) >= 1e6) return `${(value / 1e6).toFixed(1)}m`;
  if (Math.abs(value) >= 1e3) return `${(value / 1e3).toFixed(1)}k`;
  return value.toFixed(0);
}

function Bubble({ entry, maxRevenue }: { entry: AllocationEntry; maxRevenue: number }) {
  const fill = OUTCOME_FILL[entry.outcome] ?? "#94a3b8";
  const cx = scaleX(entry.strength);
  const cy = scaleY(entry.attractiveness);
  const r = radiusFor(entry.revenue, maxRevenue);
  const label = entry.name.length > 22 ? `${entry.name.slice(0, 21)}…` : entry.name;

  // A unit at the floor of either axis sits on the plot edge, and a centred
  // label there runs off the chart - which clipped the name of the one unit a
  // reader most wants to identify, the one being harvested.
  const EDGE = 70;
  const anchor = cx < PAD + EDGE ? "start" : cx > SIZE - PAD - EDGE ? "end" : "middle";
  const labelX = anchor === "start" ? PAD + 2 : anchor === "end" ? SIZE - PAD - 2 : cx;
  // Flip the label under the bubble when it would collide with the top frame.
  const above = cy - r - 4 > PAD + 8;

  return (
    <g>
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill={fill}
        fillOpacity={0.24}
        stroke={fill}
        strokeWidth={1.4}
      />
      <text
        x={labelX}
        y={above ? cy - r - 4 : cy + r + 11}
        textAnchor={anchor}
        fontSize={9}
        fill="#94a3b8"
      >
        {label}
      </text>
    </g>
  );
}

export default function PortfolioGrid({ run }: { run: AllocationRun }) {
  const maxRevenue = Math.max(...run.allocations.map((a) => a.revenue ?? 0), 0);
  const basis = run.calculation_basis ?? {};
  const pool = basis.pool ?? {};
  const noRevenue = run.allocations.filter((a) => !a.revenue).length;

  return (
    <div className="space-y-3">
      <div className="panel p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <span className="label">Budget-constrained allocation</span>
            <p className="font-mono text-sm text-slate-200">
              budget {money(run.budget)}
              {run.harvest_contribution > 0 && (
                <>
                  {" + "}
                  <span className="text-[#60a5fa]">
                    {money(run.harvest_contribution)} harvest
                  </span>
                </>
              )}
              {" = pool "}
              {money(pool.pool ?? run.budget + run.harvest_contribution)}
            </p>
          </div>
          <p className="font-mono text-xs text-slate-500">
            floors {money(pool.floors_total ?? 0)} · discretionary{" "}
            {money(pool.discretionary_allocated ?? 0)} · unallocated{" "}
            {money(pool.unallocated ?? 0)}
          </p>
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">{basis.status}</p>
      </div>

      <div className="panel p-4">
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="mx-auto w-full max-w-lg">
          <rect
            x={PAD}
            y={PAD}
            width={SIZE - 2 * PAD}
            height={SIZE - 2 * PAD}
            fill="none"
            stroke="#232c42"
          />
          {[LOW, HIGH].map((value) => (
            <g key={value}>
              <line
                x1={scaleX(value)}
                y1={PAD}
                x2={scaleX(value)}
                y2={SIZE - PAD}
                stroke="#232c42"
                strokeDasharray="3 3"
              />
              <line
                x1={PAD}
                y1={scaleY(value)}
                x2={SIZE - PAD}
                y2={scaleY(value)}
                stroke="#232c42"
                strokeDasharray="3 3"
              />
            </g>
          ))}
          <text x={SIZE / 2} y={SIZE - 12} textAnchor="middle" fontSize={10} fill="#64748b">
            Competitive strength →
          </text>
          <text
            x={-SIZE / 2}
            y={14}
            transform="rotate(-90)"
            textAnchor="middle"
            fontSize={10}
            fill="#64748b"
          >
            Market attractiveness →
          </text>
          {run.allocations.map((entry) => (
            <Bubble key={entry.entity_key} entry={entry} maxRevenue={maxRevenue} />
          ))}
        </svg>

        <div className="mt-2 flex flex-wrap justify-center gap-3 text-[11px] text-slate-500">
          {Object.entries(OUTCOME_FILL).map(([outcome, colour]) => (
            <span key={outcome} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: colour, opacity: 0.6 }}
              />
              {outcome.replace(/_/g, " ").toLowerCase()}
            </span>
          ))}
        </div>
        <p className="mt-2 text-center text-[11px] text-slate-600">
          Bubble area is proportional to revenue.
          {noRevenue > 0 &&
            ` ${noRevenue} unit(s) reported no revenue and are drawn at the minimum size.`}
        </p>
      </div>

      {run.marginal_unit && (
        <div className="panel border-caution/40 p-4">
          <span className="label mb-0.5 text-caution">The marginal unit</span>
          <p className="text-sm text-slate-100">
            {run.marginal_unit.name}{" "}
            <span className="font-mono text-xs text-slate-400">
              rank {run.marginal_unit.rank} · short by{" "}
              {money(Number(run.marginal_unit.shortfall ?? 0))}
            </span>
          </p>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">
            {run.marginal_unit.note}
          </p>
        </div>
      )}

      <div className="panel overflow-x-auto p-4">
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Priority order
        </h4>
        <table className="w-full text-left text-xs">
          <thead className="text-slate-500">
            <tr>
              <th className="py-1 pr-3 font-normal">#</th>
              <th className="py-1 pr-3 font-normal">Unit</th>
              <th className="py-1 pr-3 text-right font-normal">A × S</th>
              <th className="py-1 pr-3 text-right font-normal">entropy ×</th>
              <th className="py-1 pr-3 text-right font-normal">priority</th>
              <th className="py-1 pr-3 text-right font-normal">requested</th>
              <th className="py-1 pr-3 text-right font-normal">allocated</th>
              <th className="py-1 font-normal">outcome</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-edge/50">
            {run.allocations.map((entry) => (
              <tr key={entry.entity_key} className="align-top">
                <td className="py-1.5 pr-3 font-mono text-slate-600">{entry.rank}</td>
                <td className="py-1.5 pr-3">
                  <span className="text-slate-200">{entry.name}</span>
                  <span className="ml-1.5 text-[10px] text-slate-600">
                    {entry.quadrant.replace(/_/g, " ")}
                  </span>
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-slate-400">
                  {entry.attractiveness.toFixed(2)} × {entry.strength.toFixed(2)}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-slate-400">
                  {entry.entropy_bits === null ? (
                    <span className="text-slate-600" title="no uncertainty run; not discounted">
                      —
                    </span>
                  ) : (
                    entry.entropy_discount.toFixed(3)
                  )}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-accent">
                  {entry.priority_score.toFixed(2)}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-slate-400">
                  {money(entry.capital_requested)}
                  {entry.capital_floor > 0 && (
                    <span className="text-slate-600"> ({money(entry.capital_floor)} floor)</span>
                  )}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-slate-200">
                  {money(entry.allocated)}
                  {entry.contributed > 0 && (
                    <span className="text-[#60a5fa]"> −{money(entry.contributed)}</span>
                  )}
                </td>
                <td className="py-1.5">
                  <span
                    className="chip border-transparent"
                    style={{ color: OUTCOME_FILL[entry.outcome] }}
                    title={OUTCOME_COPY[entry.outcome]}
                  >
                    {entry.outcome.replace(/_/g, " ")}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <details className="panel p-4">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-slate-400">
          The allocation rule, and whose it is
        </summary>
        <p className="mt-2 text-xs leading-relaxed text-slate-400">{basis.framework_note}</p>
        <p className="mt-2 font-mono text-[11px] text-accent">{basis.priority_formula}</p>
        <ol className="mt-2 list-decimal space-y-1 pl-4 text-xs leading-relaxed text-slate-500">
          {(basis.allocation_order ?? []).map((step: string) => (
            <li key={step}>{step.replace(/^\d\.\s*/, "")}</li>
          ))}
        </ol>
        <p className="mt-2 text-xs leading-relaxed text-slate-500">{basis.greedy_note}</p>
        {(basis.warnings ?? []).map((warning: string) => (
          <p key={warning} className="mt-2 text-xs leading-relaxed text-caution">
            {warning}
          </p>
        ))}
      </details>
    </div>
  );
}
