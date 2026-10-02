import type { MarketAttractiveness } from "../api/types";

/** The GE-McKinsey grid, drawn to scale. */

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

const INK = "#1D2536";
const TICK = "#475569";
const AXIS_TEXT = "#94A3B8";

/** Background wash per quadrant band, so the three verdicts read at a glance. */
const BANDS = [
  // [x0, x1, y0, y1, fill] in axis units. HARVEST lower-left, INVEST upper-right.
  [MIN, LOW, MIN, LOW, "rgba(251,113,133,0.05)"],
  [HIGH, MAX, HIGH, MAX, "rgba(52,211,153,0.06)"],
] as const;

function Axis() {
  return (
    <g>
      {BANDS.map(([x0, x1, y0, y1, fill]) => (
        <rect
          key={fill}
          x={scaleX(x0)}
          y={scaleY(y1)}
          width={scaleX(x1) - scaleX(x0)}
          height={scaleY(y0) - scaleY(y1)}
          fill={fill}
        />
      ))}

      <rect
        x={PAD}
        y={PAD}
        width={SIZE - 2 * PAD}
        height={SIZE - 2 * PAD}
        fill="none"
        stroke={INK}
      />

      {/* Threshold lines are solid and brighter than the frame: they are the
          rule the verdict comes from, not decoration. */}
      {[LOW, HIGH].map((value) => (
        <g key={value}>
          <line
            x1={scaleX(value)}
            y1={PAD}
            x2={scaleX(value)}
            y2={SIZE - PAD}
            stroke="#334155"
            strokeDasharray="2 4"
          />
          <line
            x1={PAD}
            y1={scaleY(value)}
            x2={SIZE - PAD}
            y2={scaleY(value)}
            stroke="#334155"
            strokeDasharray="2 4"
          />
        </g>
      ))}

      {[MIN, LOW, HIGH, MAX].map((value) => (
        <g key={`t-${value}`}>
          <text
            x={scaleX(value)}
            y={SIZE - PAD + 16}
            fontSize="9"
            fill={TICK}
            textAnchor="middle"
            fontFamily="JetBrains Mono, monospace"
          >
            {value}
          </text>
          <text
            x={PAD - 9}
            y={scaleY(value) + 3}
            fontSize="9"
            fill={TICK}
            textAnchor="end"
            fontFamily="JetBrains Mono, monospace"
          >
            {value}
          </text>
        </g>
      ))}

      {/* Corner labels rather than a legend: the reader is already looking at
          the grid, and a detached legend is one more eye trip. */}
      <text x={PAD + 6} y={PAD + 14} fontSize="8.5" fill="#64748B" letterSpacing="1">
        SELECTIVE
      </text>
      <text
        x={SIZE - PAD - 6}
        y={PAD + 14}
        fontSize="8.5"
        fill="#34D399"
        opacity="0.75"
        textAnchor="end"
        letterSpacing="1"
      >
        INVEST / GROW
      </text>
      <text x={PAD + 6} y={SIZE - PAD - 7} fontSize="8.5" fill="#FB7185" opacity="0.75" letterSpacing="1">
        HARVEST / DIVEST
      </text>

      <text
        x={SIZE / 2}
        y={SIZE - 4}
        fontSize="9.5"
        fill={AXIS_TEXT}
        textAnchor="middle"
        letterSpacing="0.5"
      >
        Competitive strength →
      </text>
      <text
        x={11}
        y={SIZE / 2}
        fontSize="9.5"
        fill={AXIS_TEXT}
        textAnchor="middle"
        letterSpacing="0.5"
        transform={`rotate(-90 11 ${SIZE / 2})`}
      >
        Market attractiveness →
      </text>
    </g>
  );
}

function ScoreRow({ label, value, note }: { label: string; value: number; note?: string }) {
  // A 1-5 score is easier to compare as a filled track than as four decimals
  // in a column, so the number and the bar are shown together.
  const pct = ((value - 1) / 4) * 100;
  return (
    <div className="border-t border-edge/50 py-2 first:border-t-0">
      <div className="flex items-baseline justify-between gap-4">
        <span className="text-xs text-slate-400">
          {label}
          {note ? <span className="ml-1.5 text-2xs text-slate-600">{note}</span> : null}
        </span>
        <span className="num text-sm font-semibold text-slate-100">{value.toFixed(2)}</span>
      </div>
      <div className="meter mt-1.5">
        <div className="meter-fill bg-accent/60" style={{ width: `${pct}%` }} />
      </div>
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
      <div className="panel flex items-center justify-center p-4">
        {/* Capped, and centred. A square viewBox stretched to a wide column
            renders a 700px-tall chart that pushes the rest of the page off
            screen - and scales every label up with it. */}
        <svg
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          className="mx-auto block w-full max-w-[360px]"
          role="img"
          aria-label={`GE-McKinsey matrix: attractiveness ${result.overall_attractiveness_score.toFixed(2)}, competitive strength ${result.competitive_strength_score.toFixed(2)}, ${result.quadrant.replace(/_/g, " ")}`}
        >
          <defs>
            <radialGradient id="pointGlow">
              <stop offset="0%" stopColor="#F0B429" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#F0B429" stopOpacity="0" />
            </radialGradient>
          </defs>
          <Axis />

          {/* Guide lines down to each axis: the point's coordinates are the
              output, so make them readable off the axes directly. */}
          <line x1={x} y1={y} x2={x} y2={SIZE - PAD} stroke="#F0B429" strokeOpacity="0.3" strokeDasharray="2 3" />
          <line x1={PAD} y1={y} x2={x} y2={y} stroke="#F0B429" strokeOpacity="0.3" strokeDasharray="2 3" />

          <circle cx={x} cy={y} r="22" fill="url(#pointGlow)" />
          <circle cx={x} cy={y} r="7" fill="#F0B429" fillOpacity="0.25" />
          <circle cx={x} cy={y} r="4" fill="#FFCF5C" stroke="#070A12" strokeWidth="1.2" />
          <text
            x={x + 11}
            y={y - 9}
            fontSize="10"
            fill="#FFCF5C"
            fontFamily="JetBrains Mono, monospace"
            fontWeight="600"
          >
            {result.overall_attractiveness_score.toFixed(2)} /{" "}
            {result.competitive_strength_score.toFixed(2)}
          </text>
        </svg>
      </div>

      <div className="space-y-3">
        <div className="panel p-4">
          <span className="label">Verdict</span>
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`text-lg font-semibold tracking-tight ${
                QUADRANT_TONE[result.quadrant] ?? "text-slate-200"
              }`}
            >
              {result.quadrant.replace(/_/g, " ")}
            </span>
            {result.borderline && <span className="chip chip-caution">borderline</span>}
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
          <h4 className="label">Axis inputs · 1–5</h4>
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
