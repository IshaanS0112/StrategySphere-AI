"""Application configuration.

Every weight, threshold, and coefficient used by the strategy engines lives
here. Nothing in the SWOT / attractiveness / pricing math reads a magic number
that is not declared in this file, and the resolved values are written into the
``calculation_basis`` of every stored result. That is what makes a score
reproducible six months later: the inputs are in the database and so is the
parameter set that turned them into a number.
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Infrastructure -----------------------------------------------------
    database_url: str = "postgresql+psycopg2://strategy:strategy@localhost:5432/strategysphere"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # --- LLM ----------------------------------------------------------------
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    llm_timeout_seconds: float = 30.0
    llm_max_tokens: int = 1600

    # --- SWOT scoring -------------------------------------------------------
    # A metric is only called a strength or a weakness once it clears a
    # relative band around its benchmark. Without a dead zone every company is
    # simultaneously strong and weak at everything by a rounding error.
    swot_neutral_band_pct: float = 5.0     # +/- this % of benchmark = not a factor
    swot_score_2_pct: float = 10.0         # relative deviation for impact_score 2
    swot_score_3_pct: float = 25.0
    swot_score_4_pct: float = 50.0
    swot_score_5_pct: float = 100.0        # >= this deviation -> impact_score 5

    # Peer-derived benchmarks need enough peers to mean anything. Below this
    # count the engine falls back to the industry benchmark table and records
    # which basis it used.
    swot_min_peers_for_benchmark: int = 3

    # Optional path to a JSON table of your own sourced industry benchmarks.
    # Empty means use the built-in illustrative bands; see benchmarks.py.
    industry_benchmarks_path: str = ""

    # --- Market concentration (HHI) ----------------------------------------
    # Herfindahl-Hirschman Index bands from the US DOJ/FTC 2023 Merger
    # Guidelines: unconcentrated < 1000, moderately concentrated 1000-1800,
    # highly concentrated > 1800. Used to derive competitive intensity from the
    # competitor set rather than asking the analyst to guess a 1-5 number.
    hhi_unconcentrated_max: float = 1000.0
    hhi_highly_concentrated_min: float = 1800.0

    # --- GE-McKinsey market attractiveness ---------------------------------
    # Weights must sum to 1.0; enforced below. Defaults are the ones documented
    # in the original design note.
    attractiveness_w_growth: float = 0.3
    attractiveness_w_size: float = 0.2
    attractiveness_w_profitability: float = 0.3
    attractiveness_w_intensity: float = 0.2

    quadrant_high_threshold: float = 3.5
    quadrant_low_threshold: float = 2.5
    # A company landing at 3.51 is not meaningfully different from one at 3.49.
    # Results within this distance of a boundary are flagged as borderline
    # instead of being reported as a confident quadrant placement.
    quadrant_borderline_margin: float = 0.15

    # Competitive strength: the original design used the mean of SWOT strength
    # impact scores. That formula ignores weaknesses entirely, so a company
    # with one excellent margin and four structural problems scores as strong.
    # The penalty term below corrects for that. Setting it to 0.0 reproduces
    # the original formula exactly; see docs/architecture.md.
    swot_weakness_penalty: float = 0.5
    swot_neutral_impact: float = 3.0       # weakness level at which no penalty applies

    # --- Pricing ------------------------------------------------------------
    # "target_margin_pct" is ambiguous shorthand: cost x (1 + m) is a MARKUP,
    # not a margin. At m = 0.40 on a cost of 100 it yields 140, which is a
    # 28.6% margin, not 40%. MARGIN basis (cost / (1 - m)) yields 166.67, which
    # actually delivers 40%. Default is the correct reading; MARKUP remains
    # available per-request. Documented in docs/architecture.md.
    pricing_default_margin_basis: str = "MARGIN"     # MARGIN | MARKUP

    pricing_w_cost_plus: float = 0.5       # weight on the cost-plus anchor
    pricing_w_competitor: float = 0.5      # weight on the competitor benchmark
    pricing_value_coefficient: float = 0.10   # k in 1 + k*(feature delta)
    pricing_value_adjustment_cap: float = 0.30  # clamp adjustment to +/- 30%
    pricing_range_spread: float = 0.10     # +/- 10% band around the point estimate

    # Competitor prices that disagree wildly make the benchmark meaningless.
    # Above this coefficient of variation the result is flagged low-confidence.
    pricing_dispersion_warning_cv: float = 0.35

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def attractiveness_weights(self) -> dict[str, float]:
        return {
            "market_growth": self.attractiveness_w_growth,
            "market_size": self.attractiveness_w_size,
            "profitability": self.attractiveness_w_profitability,
            "competitive_intensity": self.attractiveness_w_intensity,
        }

    @model_validator(mode="after")
    def _check_invariants(self) -> "Settings":
        weight_sum = (
            self.attractiveness_w_growth
            + self.attractiveness_w_size
            + self.attractiveness_w_profitability
            + self.attractiveness_w_intensity
        )
        if abs(weight_sum - 1.0) > 1e-6:
            raise ValueError(
                f"GE-McKinsey attractiveness weights must sum to 1.0, got {weight_sum:.4f}. "
                "An unnormalised weight vector silently rescales every score."
            )

        pricing_sum = self.pricing_w_cost_plus + self.pricing_w_competitor
        if abs(pricing_sum - 1.0) > 1e-6:
            raise ValueError(
                f"Pricing anchor weights must sum to 1.0, got {pricing_sum:.4f}."
            )

        if self.quadrant_low_threshold >= self.quadrant_high_threshold:
            raise ValueError("quadrant_low_threshold must be below quadrant_high_threshold")

        if self.pricing_default_margin_basis not in {"MARGIN", "MARKUP"}:
            raise ValueError("pricing_default_margin_basis must be MARGIN or MARKUP")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
