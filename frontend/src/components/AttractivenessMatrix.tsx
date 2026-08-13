import type { MarketAttractiveness } from "../api/types";

/**
 * The GE-McKinsey grid, drawn to scale.
 *
 * Both axes run 1-5 and the boundary lines sit at the configured 2.5 / 3.5
 * thresholds, so the plotted point's position is the actual computed position
 * rather than a decorative marker dropped in the middle of a labelled box.
 */

const SIZE = 340;
const PAD = 44;
const MIN = 1;
const MAX = 5;

const LOW = 2.5;
const HIGH = 3.5;

const QUADRANT_COPY: Record<string, string> = {
  INVEST_GROW: "Attractive market, strong position — fund growth and defend share.",
  SELECTIVE_INVEST:
    "One axis is strong and the other is not — invest only where an advantage already exists.",
  HARVEST_DIVEST: "Weak position in an unattractive market — harvest cash, assess exit.",
};

const QUADRANT_TONE: Record<string, string> = {
  INVEST_GROW: "text-positive",
  SELECTIVE_INVEST: "text-caution",
  HARVEST_DIVEST: "text-negative",
};

function scaleX(value: number) {
  return PAD + ((value - MIN) / (MAX - MIN)) * (SIZE - 2 * PAD);
}

function scaleY(value: number) {
  // SVG y grows downward; attractiveness should grow upward.
  return SIZE - PAD - ((value - MIN) / (MAX - MIN)) * (SIZE - 2 * PAD);
}

function Axis() {
  const gridLines = [LOW, HIGH];
  return (
    <g>
      <rect
        x={PAD}
        y={PAD}
        width={SIZE - 2 * PAD}
        height={SIZE - 2 * PAD}
        fill="none"
        stroke="#232c42"
      />
      {gridLines.map((value) => (
        <g key={`v-${value}`}>
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
      {[MIN, LOW, HIGH, MAX].map((value) => (
        <g key={`t-${value}`}>
          <text
            x={scaleX(value)}
            y={SIZE - PAD + 14}
            fontSize="9"
            fill="#64748b"
            textAnchor="middle"
          >
            {value}
          </text>
          <text
            x={PAD - 8}
            y={scaleY(value) + 3}
            fontSize="9"
            fill="#64748b"
            textAnchor="end"
          >
            {value}
          </text>
        </g>
      ))}
      <text
        x={SIZE / 2}
        y={SIZE - 6}
        fontSize="10"
        fill="#94a3b8"
        textAnchor="middle"
      >
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
    </g>
  );
}

function ScoreRow({ label, value, note }: { label: string; value: number; note?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-t border-edge/60 py-1.5 first:border-t-0">
      <span className="text-xs text-slate-400">
        {label}
        {note ? <span className="ml-1.5 text-slate-600">{note}</span> : null}
      </span>
      <span className="font-mono text-sm text-slate-100">{value.toFixed(2)}</span>
    </div>
  );
}

export default function AttractivenessMatrix({ result }: { result: MarketAttractiveness }) {
  const x = scaleX(result.competitive_strength_score);
  const y = scaleY(result.overall_attractiveness_score);
  const structure = result.calculation_basis?.market_structure ?? {};
  const imputed: string[] = result.calculation_basis?.imputed_axes ?? [];

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="panel p-3">
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="w-full" role="img" aria-label="GE-McKinsey matrix">
          <Axis />
          <circle cx={x} cy={y} r="9" fill="#f0b429" fillOpacity="0.2" />
          <circle cx={x} cy={y} r="4.5" fill="#f0b429" />
          <text x={x + 10} y={y - 8} fontSize="10" fill="#f0b429" fontFamily="monospace">
            {result.overall_attractiveness_score.toFixed(2)} /{" "}
            {result.competitive_strength_score.toFixed(2)}
          </text>
        </svg>
      </div>

      <div className="space-y-3">
        <div className="panel p-4">
          <div className="flex items-center gap-2">
            <span
              className={`text-sm font-semibold tracking-wide ${
                QUADRANT_TONE[result.quadrant] ?? "text-slate-200"
              }`}
            >
              {result.quadrant.replace(/_/g, " ")}
            </span>
            {result.borderline && (
              <span className="chip border-caution/50 text-caution">borderline</span>
            )}
          </div>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
            {QUADRANT_COPY[result.quadrant]}
          </p>
          {result.borderline && (
            <p className="mt-2 text-xs leading-relaxed text-caution/90">
              {result.calculation_basis?.quadrant_placement?.borderline_note ??
                "The position sits close to a quadrant boundary; treat the verdict as provisional."}
            </p>
          )}
        </div>

        <div className="panel p-4">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            Axis inputs (1-5)
          </h4>
          <ScoreRow
            label="Market growth"
            value={result.market_growth_score}
            note={imputed.includes("market_growth") ? "imputed" : undefined}
          />
          <ScoreRow
            label="Market size"
            value={result.market_size_score}
            note={imputed.includes("market_size") ? "imputed" : undefined}
          />
          <ScoreRow
            label="Industry profitability"
            value={result.profitability_score}
            note={imputed.includes("industry_profitability") ? "imputed" : undefined}
          />
          <ScoreRow
            label="Competitive intensity"
            value={result.competitive_intensity_score}
            note={structure.hhi ? `HHI ${Math.round(structure.hhi)}` : "no shares"}
          />
        </div>

        {structure.concentration_band && (
          <p className="text-xs leading-relaxed text-slate-500">
            Market is <span className="text-slate-300">{structure.concentration_band}</span>{" "}
            (HHI {Math.round(structure.hhi)}) on DOJ/FTC 2023 Merger Guidelines bands.{" "}
            {structure.dispersion_note}. Unnamed residual share:{" "}
            {structure.residual_share_pct}%.
          </p>
        )}
      </div>
    </div>
  );
}
