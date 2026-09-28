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

    # --- V2: Porter's Five Forces ------------------------------------------
    # Porter does not weight the forces - the framework is qualitative and the
    # five are meant to be read individually. The composite below exists only
    # so the forces can be summarised in one number for the UI, and it is
    # labelled a project-defined composite everywhere it appears. Equal weights
    # because there is no published basis for any other choice.
    porter_composite_equal_weights: bool = True
    # A force is only reported when at least this fraction of its inputs are
    # present. Below it the force comes back UNAVAILABLE rather than guessed.
    porter_min_input_coverage: float = 0.5

    # Industry attractiveness bands on the mean-force scale (1-5, higher =
    # stronger force = worse for incumbents).
    porter_attractive_below: float = 2.5
    porter_unattractive_above: float = 3.5

    # --- V2: Sensitivity ----------------------------------------------------
    # Each axis is scored 1-5, so the largest possible single-axis move is 4.0.
    # A flip that needs more than this is not reachable at all.
    sensitivity_axis_span: float = 4.0
    # A flip requiring less than this much movement on a 1-5 axis marks the
    # placement FRAGILE. 0.5 is half a band - well inside normal input error.
    sensitivity_fragile_threshold: float = 0.5
    sensitivity_knife_edge_threshold: float = 0.15

    # --- V2: Multi-period ---------------------------------------------------
    # Change in a 1-5 score below this is noise, not a trend.
    trend_material_delta: float = 0.25

    # --- V2: Validation harness --------------------------------------------
    # Permutation test iterations for the quadrant-separation null.
    validation_permutations: int = 2000
    validation_random_seed: int = 20260908

    # --- V3: SEC EDGAR benchmark sourcing ----------------------------------
    # The SEC's developer guidance requires automated access to declare a
    # User-Agent identifying the requester with contact details. There is
    # deliberately NO usable default here: the empty string means "not
    # configured", the app still starts (the no-API-key promise extends to the
    # no-EDGAR-credentials case), and EdgarClient raises on construction rather
    # than letting an anonymous request reach SEC infrastructure.
    edgar_user_agent: str = ""
    # Published guidance caps automated access at 10 requests/second. Five is
    # deliberately half of that; the invariant check below refuses anything
    # above the published ceiling, because a rate limiter you can misconfigure
    # past the limit is not a rate limiter.
    edgar_requests_per_second: float = 5.0
    edgar_timeout_seconds: float = 30.0
    # Every response is cached to disk keyed by URL. Historical period data does
    # not change, so a rebuild must not re-hit the API.
    edgar_cache_dir: str = "data/edgar_cache"
    # Serve from cache only. A miss is a loud failure, never a silent fetch.
    edgar_offline: bool = False
    # A sector median is only published at or above this many resolved
    # companies. Below it the sector is omitted and the lookup falls back to
    # the all-filer median, which the output states explicitly. A median of
    # four companies is not an industry benchmark.
    edgar_min_sector_n: int = 20
    # SIC codes come from the per-company submissions endpoint, which is one
    # request per company. The all-filer median uses every filer that resolved
    # a metric (no SIC needed); sector medians can only cover the companies we
    # actually classified. This caps that classification pass.
    edgar_sic_lookup_limit: int = 600

    # --- V3: Uncertainty propagation ---------------------------------------
    uncertainty_draws: int = 10000
    uncertainty_seed: int = 20260921
    # PERT weights the mode more heavily than a triangular distribution and,
    # unlike uniform, does not throw the mode away. Both alternatives remain
    # selectable, and the choice is recorded in calculation_basis.
    uncertainty_distribution: str = "PERT"     # PERT | TRIANGULAR | UNIFORM
    uncertainty_pert_lambda: float = 4.0
    uncertainty_credible_interval_pct: float = 90.0
    # Shannon entropy over the three quadrant probabilities, in bits. The
    # maximum for three outcomes is log2(3) = 1.585.
    uncertainty_decisive_below: float = 0.25
    uncertainty_contested_at_or_above: float = 0.85

    # --- V3.1: Observability ------------------------------------------------
    log_level: str = "INFO"
    # json for anything that ships logs somewhere; text for a human terminal.
    log_format: str = "json"                   # json | text
    # A request slower than this is logged at WARNING with slow=true. One
    # second is generous for this workload: the only endpoints that legitimately
    # exceed it are the Monte Carlo and an LLM narration.
    slow_request_seconds: float = 1.0
    metrics_enabled: bool = True

    # --- V3.1: Pagination ---------------------------------------------------
    page_size_default: int = 25
    page_size_max: int = 200

    # --- V3.1: Background jobs ----------------------------------------------
    # Worker threads for long-running work (an EDGAR rebuild, a panel build).
    # These are I/O-bound and rate-limited by the SEC bucket, so threads are
    # the right primitive and the GIL is not the constraint.
    job_workers: int = 2
    # A job that has not heartbeated for this long is presumed dead and marked
    # FAILED, so a crashed worker cannot leave a job RUNNING forever.
    job_heartbeat_timeout_seconds: float = 120.0
    job_retention_days: int = 30

    # --- V3.1: EDGAR concurrency --------------------------------------------
    # Parallel in-flight requests to data.sec.gov. The TOKEN BUCKET still caps
    # the rate; this only overlaps network latency, so the published limit is
    # respected no matter what this is set to.
    edgar_concurrency: int = 4

    # --- V3: Portfolio capital allocation ----------------------------------
    # PROJECT-DEFINED ALLOCATION RULE. GE-McKinsey positions business units; it
    # prescribes no allocation arithmetic at all. Everything in this block is
    # mine and is labelled as mine in every payload that uses it.
    harvest_contribution_rate: float = 0.10
    # priority_score = attractiveness * strength * (1 - entropy_bits / this).
    # log2(3): the entropy of a three-way coin flip, i.e. total indecision.
    max_entropy_bits: float = 1.584962500721156

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

        if self.porter_attractive_below >= self.porter_unattractive_above:
            raise ValueError(
                "porter_attractive_below must sit under porter_unattractive_above"
            )

        if not 0.0 < self.porter_min_input_coverage <= 1.0:
            raise ValueError("porter_min_input_coverage must be in (0, 1]")

        # SEC published guidance is 10 requests/second for automated access.
        # Refusing to start above it is the only way the limit is a limit
        # rather than a suggestion in a comment.
        if not 0.0 < self.edgar_requests_per_second <= 10.0:
            raise ValueError(
                f"edgar_requests_per_second must be in (0, 10]; got "
                f"{self.edgar_requests_per_second}. The SEC publishes 10 req/s as the "
                "ceiling for automated access to data.sec.gov."
            )

        if self.edgar_min_sector_n < 2:
            raise ValueError(
                "edgar_min_sector_n must be at least 2; a 'median' of one company is "
                "that company's number wearing a benchmark's clothes."
            )

        if self.uncertainty_distribution not in {"PERT", "TRIANGULAR", "UNIFORM"}:
            raise ValueError(
                "uncertainty_distribution must be PERT, TRIANGULAR or UNIFORM"
            )

        if self.uncertainty_draws < 100:
            raise ValueError(
                f"uncertainty_draws = {self.uncertainty_draws} is too few to estimate a "
                "probability worth quoting. Use at least 100."
            )

        if not 50.0 <= self.uncertainty_credible_interval_pct < 100.0:
            raise ValueError("uncertainty_credible_interval_pct must be in [50, 100)")

        if self.uncertainty_decisive_below >= self.uncertainty_contested_at_or_above:
            raise ValueError(
                "uncertainty_decisive_below must sit under "
                "uncertainty_contested_at_or_above"
            )

        if not 0.0 <= self.harvest_contribution_rate <= 1.0:
            raise ValueError("harvest_contribution_rate must be a fraction in [0, 1]")

        if self.log_format not in {"json", "text"}:
            raise ValueError("log_format must be json or text")

        if self.page_size_default > self.page_size_max:
            raise ValueError("page_size_default cannot exceed page_size_max")

        if self.job_workers < 1:
            raise ValueError("job_workers must be at least 1")

        # Concurrency cannot outrun the rate limiter, but a pool far larger
        # than the rate simply parks threads on the bucket, which looks like a
        # hang. Cap it at something the limiter can actually feed.
        if not 1 <= self.edgar_concurrency <= 16:
            raise ValueError("edgar_concurrency must be in [1, 16]")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
