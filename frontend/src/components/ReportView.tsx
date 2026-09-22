import { useState } from "react";

import type { StrategyReport } from "../api/types";

/**
 * The pre-LLM context is deliberately one click away, not hidden.
 *
 * The claim this project makes is that every figure in the narrative existed
 * before any model was called. That claim is only worth anything if a reader
 * can check it, so the exact JSON that was sent to the model is rendered right
 * underneath the prose it produced.
 */
export default function ReportView({ report }: { report: StrategyReport }) {
  const [showContext, setShowContext] = useState(false);
  const narrative = report.ai_narrative;
  const isFallback = report.narrative_source === "template_fallback";

  if (!narrative) {
    return <p className="text-sm text-slate-400">No narrative has been generated yet.</p>;
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`chip ${
            isFallback ? "border-slate-600 text-slate-400" : "border-accent/40 text-accent"
          }`}
        >
          {isFallback ? "template fallback" : "LLM narrated"}
        </span>
        {narrative.dropped_citations ? (
          <span className="chip chip-negative">
            {narrative.dropped_citations} unsupported citation(s) dropped
          </span>
        ) : null}
      </div>

      {isFallback && narrative.fallback_reason && (
        <p className="text-xs leading-relaxed text-slate-500">
          Generated without a model call ({narrative.fallback_reason}). Every number below is
          the same as it would be with one — only the prose is templated.
        </p>
      )}

      <section className="panel p-5">
        <h4 className="label">Executive summary</h4>
        <p className="text-sm leading-relaxed text-slate-200">{narrative.executive_summary}</p>
      </section>

      <section className="panel p-5">
        <h4 className="label">Strategic position</h4>
        <p className="text-sm leading-relaxed text-slate-300">{narrative.strategic_position}</p>
      </section>

      {narrative.key_factors && narrative.key_factors.length > 0 && (
        <section className="panel p-5">
          <h4 className="label">Key factors</h4>
          <ul className="space-y-2.5">
            {narrative.key_factors.map((item, index) => (
              <li key={index} className="border-l-2 border-accent/40 pl-3">
                <span className="text-sm font-medium text-slate-100">{item.factor}</span>
                <p className="text-xs leading-relaxed text-slate-400">{item.implication}</p>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-slate-500">
            Every factor named here was matched against the SWOT grid in the structured
            context. Anything the model invented was discarded before this rendered.
          </p>
        </section>
      )}

      {narrative.pricing_rationale && (
        <section className="panel p-5">
          <h4 className="label">Pricing rationale</h4>
          <p className="text-sm leading-relaxed text-slate-300">{narrative.pricing_rationale}</p>
        </section>
      )}

      <section className="panel border-accent/30 p-5">
        <h4 className="label">Recommendation</h4>
        <p className="text-sm leading-relaxed text-slate-100">{narrative.recommendation}</p>
      </section>

      <div>
        <button className="btn-ghost" onClick={() => setShowContext((open) => !open)}>
          {showContext ? "Hide" : "Show"} structured context (pre-LLM)
        </button>
        {showContext && (
          <pre className="panel mt-2 max-h-96 overflow-auto p-4 num text-2xs leading-relaxed text-slate-400">
            {JSON.stringify(report.structured_context, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
