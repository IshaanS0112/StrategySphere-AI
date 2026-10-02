import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Timeline, TimelinePoint } from "../api/types";

/** Quadrant migration across reporting periods. */

const SIZE = 340;
const PAD = 44;
const MIN = 1;
const MAX = 5;
const LOW = 2.5;
const HIGH = 3.5;

const TREND_TONE: Record<string, string> = {
  IMPROVING: "text-positive",
  STABLE: "text-slate-400",
  DETERIORATING: "text-negative",
  INSUFFICIENT_DATA: "text-slate-600",
};

const scaleX = (v: number) => PAD + ((v - MIN) / (MAX - MIN)) * (SIZE - 2 * PAD);
const scaleY = (v: number) => SIZE - PAD - ((v - MIN) / (MAX - MIN)) * (SIZE - 2 * PAD);

function MigrationPlot({ points }: { points: TimelinePoint[] }) {
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${scaleX(p.strength)} ${scaleY(p.attractiveness)}`)
    .join(" ");

  return (
    <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="w-full" role="img" aria-label="Quadrant migration">
      <rect x={PAD} y={PAD} width={SIZE - 2 * PAD} height={SIZE - 2 * PAD} fill="none" stroke="#232c42" />
      {[LOW, HIGH].map((v) => (
        <g key={v}>
          <line x1={scaleX(v)} y1={PAD} x2={scaleX(v)} y2={SIZE - PAD} stroke="#232c42" strokeDasharray="3 3" />
          <line x1={PAD} y1={scaleY(v)} x2={SIZE - PAD} y2={scaleY(v)} stroke="#232c42" strokeDasharray="3 3" />
        </g>
      ))}
      {[MIN, LOW, HIGH, MAX].map((v) => (
        <g key={`t${v}`}>
          <text x={scaleX(v)} y={SIZE - PAD + 14} fontSize="9" fill="#64748b" textAnchor="middle">{v}</text>
          <text x={PAD - 8} y={scaleY(v) + 3} fontSize="9" fill="#64748b" textAnchor="end">{v}</text>
        </g>
      ))}
      <text x={SIZE / 2} y={SIZE - 6} fontSize="10" fill="#94a3b8" textAnchor="middle">
        Competitive strength →
      </text>
      <text
        x={12}
        y={SIZE / 2}
        fontSize="10"
        fill="#94a3b8"
        textAnchor="middle"
        transform={`rotate(-90 12 ${SIZE / 2})`}
      >
        Market attractiveness →
      </text>

      <path d={path} fill="none" stroke="#f0b429" strokeWidth="1.5" strokeOpacity="0.5" />
      {points.map((p, i) => {
        const last = i === points.length - 1;
        return (
          <g key={p.company_id}>
            <circle
              cx={scaleX(p.strength)}
              cy={scaleY(p.attractiveness)}
              r={last ? 5 : 3.5}
              fill={last ? "#f0b429" : "#f0b429"}
              fillOpacity={last ? 1 : 0.35}
              stroke={p.borderline ? "#fbbf24" : "none"}
              strokeWidth={p.borderline ? 1.5 : 0}
            />
            <text
              x={scaleX(p.strength) + 8}
              y={scaleY(p.attractiveness) - 6}
              fontSize="9"
              fill="#94a3b8"
              fontFamily="monospace"
            >
              {p.period_label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function TimelineView() {
  const { entityKey = "" } = useParams();
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTimeline(await api.getTimeline(entityKey));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [entityKey]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!timeline) {
    return (
      <p className="panel p-6 text-sm text-slate-400">
        {error ?? "Loading…"}{" "}
        <Link to="/" className="text-accent">
          Back
        </Link>
      </p>
    );
  }

  const basis = timeline.calculation_basis ?? {};

  return (
    <div className="space-y-5">
      <header className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-100">{timeline.entity_key}</h1>
            <p className="text-xs text-slate-500">{timeline.points.length} scored period(s)</p>
          </div>
          <Link to="/" className="btn-ghost">
            All companies
          </Link>
        </div>
        <p className="mt-3 border-t border-edge pt-3 text-sm text-slate-300">
          {timeline.summary}
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="panel p-3">
          {timeline.points.length >= 2 ? (
            <MigrationPlot points={timeline.points} />
          ) : (
            <p className="p-6 text-sm text-slate-500">
              A migration path needs at least two scored periods.
            </p>
          )}
        </div>

        <div className="space-y-3">
          <div className="panel p-4">
            <h4 className="label">
              Trend
            </h4>
            <div className="flex items-baseline justify-between border-t border-edge/60 py-1.5">
              <span className="text-xs text-slate-400">Market attractiveness</span>
              <span className={`text-sm ${TREND_TONE[timeline.attractiveness_trend]}`}>
                {timeline.attractiveness_trend.replace(/_/g, " ").toLowerCase()}{" "}
                <span className="num text-xs text-slate-500">
                  {basis.attractiveness_delta > 0 ? "+" : ""}
                  {basis.attractiveness_delta}
                </span>
              </span>
            </div>
            <div className="flex items-baseline justify-between border-t border-edge/60 py-1.5">
              <span className="text-xs text-slate-400">Competitive strength</span>
              <span className={`text-sm ${TREND_TONE[timeline.strength_trend]}`}>
                {timeline.strength_trend.replace(/_/g, " ").toLowerCase()}{" "}
                <span className="num text-xs text-slate-500">
                  {basis.strength_delta > 0 ? "+" : ""}
                  {basis.strength_delta}
                </span>
              </span>
            </div>
            <p className="mt-2 text-2xs leading-relaxed text-slate-600">
              Moves smaller than {basis.material_delta_threshold} on a 1–5 axis are
              reported as stable rather than as a trend.
            </p>
          </div>

          {timeline.quadrant_changes.length > 0 && (
            <div className="panel p-4">
              <h4 className="label">
                Quadrant changes
              </h4>
              {timeline.quadrant_changes.map((change, i) => (
                <div key={i} className="border-t border-edge/60 py-2 first:border-t-0">
                  <span className="text-sm text-slate-200">
                    {change.from_period} → {change.to_period}
                  </span>
                  <p className="text-xs text-slate-400">
                    {change.from_quadrant?.replace(/_/g, " ")} →{" "}
                    {change.to_quadrant?.replace(/_/g, " ")}
                  </p>
                  {change.either_side_borderline && (
                    <span className="chip mt-1 border-caution/50 text-caution">
                      a period was borderline
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {timeline.excluded.length > 0 && (
            <div className="panel border-caution/30 p-4">
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-caution">
                Excluded periods
              </h4>
              {timeline.excluded.map((entry, i) => (
                <p key={i} className="py-1 text-xs leading-relaxed text-slate-400">
                  <span className="text-slate-300">{entry.period_label ?? "unlabelled"}</span>
                  {" — "}
                  {entry.reason}
                </p>
              ))}
            </div>
          )}
        </div>
      </div>

      <p className="text-xs leading-relaxed text-slate-500">
        {basis.trend_method} {basis.borderline_caveat}
      </p>
    </div>
  );
}
