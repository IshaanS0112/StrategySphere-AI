import type { SwotAnalysis, SwotFactor } from "../api/types";

const QUADRANTS: {
  key: keyof Pick<SwotAnalysis, "strengths" | "weaknesses" | "opportunities" | "threats">;
  title: string;
  tone: string;
}[] = [
  { key: "strengths", title: "Strengths", tone: "text-positive border-positive/30" },
  { key: "weaknesses", title: "Weaknesses", tone: "text-negative border-negative/30" },
  { key: "opportunities", title: "Opportunities", tone: "text-sky-400 border-sky-400/30" },
  { key: "threats", title: "Threats", tone: "text-caution border-caution/30" },
];

const SOURCE_LABEL: Record<string, string> = {
  computed_financial: "computed",
  computed_market: "computed",
  analyst_input: "analyst",
};

function ImpactBar({ score }: { score: number }) {
  return (
    <span className="flex gap-0.5" title={`Impact ${score}/5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span
          key={n}
          className={`h-1.5 w-3 rounded-sm ${n <= score ? "bg-accent" : "bg-edge"}`}
        />
      ))}
    </span>
  );
}

function FactorRow({ factor }: { factor: SwotFactor }) {
  const isAnalyst = factor.source === "analyst_input";
  return (
    <li className="border-t border-edge/60 py-2 first:border-t-0">
      <div className="flex items-start justify-between gap-3">
        <span className="text-sm font-medium text-slate-100">{factor.factor}</span>
        <ImpactBar score={factor.impact_score} />
      </div>
      <p className="mt-1 text-xs leading-relaxed text-slate-400">{factor.evidence}</p>
      <span
        className={`chip mt-1.5 ${
          isAnalyst
            ? "border-slate-600 text-slate-400"
            : "border-accent/40 text-accent"
        }`}
      >
        {SOURCE_LABEL[factor.source] ?? factor.source}
        {factor.benchmark_basis ? ` · ${factor.benchmark_basis.toLowerCase()}` : ""}
      </span>
    </li>
  );
}

export default function SWOTGrid({ analysis }: { analysis: SwotAnalysis }) {
  const basis = analysis.calculation_basis ?? {};

  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        {QUADRANTS.map(({ key, title, tone }) => {
          const factors = analysis[key] ?? [];
          return (
            <section key={key} className={`panel border-l-2 p-4 ${tone}`}>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider">
                {title}
                <span className="ml-2 text-slate-500">{factors.length}</span>
              </h3>
              {factors.length === 0 ? (
                <p className="text-xs text-slate-500">
                  No factor cleared the scoring threshold. That is an output, not a gap —
                  metrics inside the neutral band deliberately produce nothing.
                </p>
              ) : (
                <ul>
                  {factors.map((factor) => (
                    <FactorRow key={`${factor.factor}-${factor.metric ?? ""}`} factor={factor} />
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>

      <p className="text-xs text-slate-500">
        Benchmarked against{" "}
        <span className="text-slate-400">
          {basis.peers_reporting_financials ?? 0} peer(s) reporting financials
        </span>
        , minimum {basis.min_peers_for_peer_benchmark ?? "?"} for a peer-set median.
        Factors marked <span className="text-accent">computed</span> come from a
        benchmark comparison; <span className="text-slate-400">analyst</span> factors are
        human judgements carried through unchanged.
      </p>
    </div>
  );
}
