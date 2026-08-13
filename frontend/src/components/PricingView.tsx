import type { PricingRecommendation } from "../api/types";

const CONFIDENCE_TONE: Record<string, string> = {
  HIGH: "border-positive/40 text-positive",
  MEDIUM: "border-caution/40 text-caution",
  LOW: "border-negative/40 text-negative",
};

function money(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Where the recommendation sits inside its own range, as a 0-1 position. */
function rangePosition(min: number, optimal: number, max: number) {
  if (max <= min) return 0.5;
  return (optimal - min) / (max - min);
}

export default function PricingView({ result }: { result: PricingRecommendation }) {
  const band = result.recommended_price_range;
  const confidence = result.reasoning?.confidence ?? "UNKNOWN";
  const warnings = result.reasoning?.warnings ?? [];
  const steps = result.reasoning?.steps ?? [];
  const impliedMargin = result.calculation_basis?.implied_margin_pct;
  const position = rangePosition(band.min, band.optimal, band.max);

  return (
    <div className="space-y-3">
      <div className="panel p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <span className="label">Recommended price</span>
            <span className="font-mono text-3xl text-accent">{money(band.optimal)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`chip ${CONFIDENCE_TONE[confidence] ?? "border-edge text-slate-400"}`}>
              confidence {confidence}
            </span>
            <span className="chip border-edge text-slate-400">{result.margin_basis} basis</span>
          </div>
        </div>

        <div className="mt-5">
          <div className="relative h-1.5 rounded-full bg-edge">
            <div
              className="absolute top-1/2 h-3 w-3 -translate-y-1/2 rounded-full bg-accent"
              style={{ left: `calc(${position * 100}% - 6px)` }}
            />
          </div>
          <div className="mt-1.5 flex justify-between font-mono text-xs text-slate-500">
            <span>{money(band.min)}</span>
            <span>{money(band.max)}</span>
          </div>
        </div>

        <div className="mt-5 grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <span className="label">Cost base</span>
            <span className="font-mono">{money(result.cost_base)}</span>
          </div>
          <div>
            <span className="label">Competitor mean</span>
            <span className="font-mono">{money(result.competitor_avg_price)}</span>
          </div>
          <div>
            <span className="label">Implied margin</span>
            <span className="font-mono">
              {impliedMargin !== undefined ? `${impliedMargin.toFixed(2)}%` : "—"}
            </span>
          </div>
        </div>
      </div>

      {warnings.length > 0 && (
        <ul className="panel space-y-2 border-caution/30 p-4">
          {warnings.map((warning, index) => (
            <li key={index} className="text-xs leading-relaxed text-caution/90">
              {warning}
            </li>
          ))}
        </ul>
      )}

      <details className="panel p-4">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-slate-400">
          Derivation
        </summary>
        <ol className="mt-3 space-y-1.5 font-mono text-xs text-slate-400">
          {steps.map((step, index) => (
            <li key={index}>
              <span className="mr-2 text-slate-600">{index + 1}.</span>
              {step}
            </li>
          ))}
        </ol>
        {result.reasoning?.margin_basis_note && (
          <p className="mt-3 border-t border-edge pt-3 text-xs leading-relaxed text-slate-500">
            {result.reasoning.margin_basis_note}
          </p>
        )}
      </details>
    </div>
  );
}
