import type { ForceSource, PortersAnalysis } from "../api/types";

/**
 * The source badge is the point of this component.
 *
 * Two of the five forces have no proxy in the data this system stores and are
 * analyst judgement or nothing. Rendering a typed-in buyer-power score in the
 * same style as an HHI-derived rivalry score would undo the discipline the rest
 * of the project is built on, so every bar carries where its number came from.
 */

const SOURCE_STYLE: Record<ForceSource, string> = {
  COMPUTED: "border-accent/40 text-accent",
  PARTIALLY_COMPUTED: "border-sky-400/40 text-sky-400",
  ANALYST_INPUT: "border-slate-600 text-slate-400",
  UNAVAILABLE: "border-negative/40 text-negative",
};

const SOURCE_LABEL: Record<ForceSource, string> = {
  COMPUTED: "computed",
  PARTIALLY_COMPUTED: "part computed",
  ANALYST_INPUT: "analyst",
  UNAVAILABLE: "not scored",
};

const ATTRACTIVENESS_TONE: Record<string, string> = {
  ATTRACTIVE: "text-positive",
  MODERATE: "text-caution",
  UNATTRACTIVE: "text-negative",
};

function ForceBar({ score }: { score: number | null }) {
  if (score === null) {
    return <span className="text-xs text-slate-600">—</span>;
  }
  // Stronger force = worse for incumbents, so the bar reddens as it fills.
  const pct = ((score - 1) / 4) * 100;
  const tone = score >= 4 ? "bg-negative" : score >= 3 ? "bg-caution" : "bg-positive";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 rounded-full bg-edge">
        <div className={`h-1.5 rounded-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="num text-xs text-slate-300">{score.toFixed(2)}</span>
    </div>
  );
}

export default function PortersView({ analysis }: { analysis: PortersAnalysis }) {
  const basis = analysis.calculation_basis ?? {};

  return (
    <div className="space-y-3">
      <div className="panel p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <span className="label">Composite (project-defined)</span>
            <span className="font-mono text-3xl text-slate-100">
              {analysis.composite_score?.toFixed(2) ?? "—"}
            </span>
          </div>
          <div className="text-right">
            <span
              className={`text-sm font-semibold tracking-wide ${
                ATTRACTIVENESS_TONE[analysis.industry_attractiveness ?? ""] ?? "text-slate-400"
              }`}
            >
              {analysis.industry_attractiveness ?? "NOT SCORED"}
            </span>
            <span className="mt-0.5 block text-xs text-slate-500">
              {analysis.forces_scored} of 5 forces scored
            </span>
          </div>
        </div>
        <p className="mt-3 border-t border-edge pt-3 text-xs leading-relaxed text-caution/90">
          {basis.composite_status}
        </p>
      </div>

      <div className="panel divide-y divide-edge/60">
        {analysis.forces.map((force) => (
          <div key={force.force} className="p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium text-slate-100">
                {force.force.replace(/_/g, " ").toLowerCase()}
              </span>
              <div className="flex items-center gap-3">
                <ForceBar score={force.score} />
                <span className={`chip ${SOURCE_STYLE[force.source]}`}>
                  {SOURCE_LABEL[force.source]}
                </span>
              </div>
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{force.evidence}</p>
            {force.inputs_missing.length > 0 && (
              <p className="mt-1 text-xs text-slate-600">
                missing: {force.inputs_missing.join(", ")}
              </p>
            )}
          </div>
        ))}
      </div>

      <p className="text-xs leading-relaxed text-slate-500">
        Scale runs 1–5 where <span className="text-slate-300">higher means a stronger
        force</span>, i.e. worse for incumbents — the opposite direction to the
        GE-McKinsey attractiveness axis above. {basis.note}
      </p>
    </div>
  );
}
