import type { AxisSensitivity, Sensitivity } from "../api/types";

/**
 * A tornado chart, plus the binding constraint called out separately.
 *
 * The separate callout is not decoration. A position can be FRAGILE with every
 * attractiveness axis unreachable, because the fragility lives on the strength
 * axis — which is not in the ranked list. Reading the top of the list in that
 * case reports an unreachable axis as "most fragile", exactly backwards. That
 * bug was live until an end-to-end run surfaced it.
 */

const VERDICT_STYLE: Record<string, string> = {
  ROBUST: "border-positive/40 text-positive",
  FRAGILE: "border-caution/40 text-caution",
  KNIFE_EDGE: "border-negative/40 text-negative",
};

const AXIS_LABEL: Record<string, string> = {
  market_growth: "Market growth",
  market_size: "Market size",
  industry_profitability: "Industry profitability",
  competitive_intensity: "Competitive intensity",
  competitive_strength: "Competitive strength",
};

const VERDICT_COPY: Record<string, string> = {
  ROBUST: "No single input flips the verdict with a small move. Treat the placement as a finding.",
  FRAGILE:
    "One input flips the verdict with a move smaller than half a band — well inside normal input error.",
  KNIFE_EDGE:
    "A trivial change flips the verdict. Do not present the quadrant as a conclusion.",
};

/** Widest reachable move on the chart, used to scale every bar consistently. */
function maxDelta(axes: AxisSensitivity[]): number {
  const reachable = axes
    .filter((a) => a.reachable && a.required_delta !== null)
    .map((a) => Math.abs(a.required_delta as number));
  return reachable.length ? Math.max(...reachable, 0.5) : 1;
}

function TornadoRow({ axis, scale }: { axis: AxisSensitivity; scale: number }) {
  const delta = axis.required_delta;
  const reachable = axis.reachable && delta !== null;
  const width = reachable ? (Math.abs(delta as number) / scale) * 50 : 0;
  const negative = reachable && (delta as number) < 0;

  return (
    <div className="py-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-xs text-slate-300">{AXIS_LABEL[axis.axis] ?? axis.axis}</span>
        <span className="font-mono text-xs text-slate-500">
          now {axis.current_value.toFixed(2)}
          {reachable && (
            <>
              {" → "}
              <span className="text-accent">{axis.required_value?.toFixed(2)}</span>
            </>
          )}
        </span>
      </div>

      {/* Centre line: bars grow left for a required decrease, right for an increase. */}
      <div className="relative mt-1.5 h-3">
        <div className="absolute left-1/2 top-0 h-3 w-px bg-edge" />
        {reachable ? (
          <div
            className="absolute top-0.5 h-2 rounded-sm bg-accent/70"
            style={
              negative
                ? { right: "50%", width: `${width}%` }
                : { left: "50%", width: `${width}%` }
            }
          />
        ) : (
          <span className="absolute left-1/2 top-0 -translate-x-1/2 text-[10px] text-slate-600">
            unreachable
          </span>
        )}
      </div>

      <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{axis.note}</p>
    </div>
  );
}

export default function SensitivityPanel({ result }: { result: Sensitivity }) {
  const scale = maxDelta([
    ...result.axes,
    ...(result.strength_sensitivity ? [result.strength_sensitivity] : []),
  ]);
  const binding = result.binding_constraint;

  return (
    <div className="space-y-3">
      <div className="panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <span className="label">Robustness of the placement</span>
            <span className={`chip ${VERDICT_STYLE[result.verdict]}`}>{result.verdict}</span>
          </div>
          <span className="font-mono text-xs text-slate-500">
            {result.baseline_quadrant.replace(/_/g, " ")} · A{" "}
            {result.baseline_attractiveness.toFixed(2)} · S{" "}
            {result.baseline_strength.toFixed(2)}
          </span>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-slate-400">
          {VERDICT_COPY[result.verdict]}
        </p>

        {binding && (
          <div className="mt-4 rounded-md border border-accent/30 bg-ink/60 p-3">
            <span className="label mb-0.5">Binding constraint</span>
            <p className="text-sm text-slate-100">
              {AXIS_LABEL[binding.axis] ?? binding.axis}
              {binding.required_delta !== null && (
                <>
                  {" "}
                  <span className="font-mono text-accent">
                    {binding.required_delta > 0 ? "+" : ""}
                    {binding.required_delta.toFixed(2)}
                  </span>{" "}
                  → {binding.resulting_quadrant?.replace(/_/g, " ")}
                </>
              )}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              This is the single input the verdict hangs on — not necessarily the top
              of the list below, which ranks the attractiveness axes only.
            </p>
          </div>
        )}
      </div>

      <div className="panel p-4">
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Attractiveness axes
        </h4>
        <p className="mb-2 text-[11px] text-slate-600">
          Minimum move on each 1–5 axis that changes the quadrant. Solved exactly, not
          searched: the score is linear in its axes, so the derivative is the weight.
        </p>
        <div className="divide-y divide-edge/50">
          {result.axes.map((axis) => (
            <TornadoRow key={axis.axis} axis={axis} scale={scale} />
          ))}
        </div>
      </div>

      {result.strength_sensitivity && (
        <div className="panel p-4">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            Competitive strength axis
          </h4>
          <TornadoRow axis={result.strength_sensitivity} scale={scale} />
        </div>
      )}

      <details className="panel p-4">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-slate-400">
          Method
        </summary>
        <p className="mt-2 text-xs leading-relaxed text-slate-400">
          {result.calculation_basis?.method}
        </p>
        <p className="mt-2 font-mono text-xs text-accent">
          {result.calculation_basis?.formula}
        </p>
        <p className="mt-2 text-xs leading-relaxed text-slate-500">
          {result.calculation_basis?.conjunctive_rule_note}
        </p>
      </details>
    </div>
  );
}
