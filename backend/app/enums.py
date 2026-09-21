"""Domain enumerations.

``str, Enum`` rather than ``StrEnum`` so the backend runs on Python 3.10 as
well as 3.11+. Values are always accessed via ``.value`` when serialising.
"""

from enum import Enum


class SwotCategory(str, Enum):
    STRENGTH = "STRENGTH"
    WEAKNESS = "WEAKNESS"
    OPPORTUNITY = "OPPORTUNITY"
    THREAT = "THREAT"


class Quadrant(str, Enum):
    """GE-McKinsey nine-box collapsed to the three standard investment verdicts."""

    INVEST_GROW = "INVEST_GROW"
    SELECTIVE_INVEST = "SELECTIVE_INVEST"
    HARVEST_DIVEST = "HARVEST_DIVEST"


class MarketConcentration(str, Enum):
    """DOJ/FTC 2023 Merger Guidelines concentration bands."""

    UNCONCENTRATED = "UNCONCENTRATED"
    MODERATELY_CONCENTRATED = "MODERATELY_CONCENTRATED"
    HIGHLY_CONCENTRATED = "HIGHLY_CONCENTRATED"


class MarginBasis(str, Enum):
    """How ``target_margin_pct`` is interpreted by the cost-plus anchor.

    MARGIN: price = cost / (1 - m)   -> the realised margin equals m.
    MARKUP: price = cost * (1 + m)   -> the realised margin is m / (1 + m).
    """

    MARGIN = "MARGIN"
    MARKUP = "MARKUP"


class BenchmarkBasis(str, Enum):
    """Where a SWOT metric's comparison point came from.

    The three V3 members exist because "industry table" stopped being one
    thing. A placeholder round number and the median of 148 real filers are
    both "the industry table" and a reader has to be able to tell them apart
    without opening the file.
    """

    PEER_SET = "PEER_SET"           # median of the competitors supplied
    INDUSTRY_TABLE = "INDUSTRY_TABLE"   # configured industry reference band
    UNAVAILABLE = "UNAVAILABLE"     # metric skipped, no benchmark to compare to

    # --- V3 -----------------------------------------------------------------
    # Median of the SIC-classified filers in this sector, from SEC XBRL data.
    EDGAR_SECTOR_MEDIAN = "EDGAR_SECTOR_MEDIAN"
    # Median across every filer that resolved the metric, used when a sector
    # has fewer than edgar_min_sector_n companies or no SIC classification.
    EDGAR_ALL_FILER_MEDIAN = "EDGAR_ALL_FILER_MEDIAN"


class NarrativeSource(str, Enum):
    LLM = "llm"
    TEMPLATE_FALLBACK = "template_fallback"


# --------------------------------------------------------------------------
# V2
# --------------------------------------------------------------------------

class PorterForce(str, Enum):
    """The five forces, named as Porter named them (Porter, 1979)."""

    COMPETITIVE_RIVALRY = "COMPETITIVE_RIVALRY"
    THREAT_OF_NEW_ENTRANTS = "THREAT_OF_NEW_ENTRANTS"
    THREAT_OF_SUBSTITUTES = "THREAT_OF_SUBSTITUTES"
    BUYER_POWER = "BUYER_POWER"
    SUPPLIER_POWER = "SUPPLIER_POWER"


class ForceSource(str, Enum):
    """Whether a force score was derived from data or supplied by a human.

    The whole point of separating these is that three of the five forces have
    no honest proxy in the data this system holds. Presenting an analyst's
    guess in the same typeface as a computed HHI would be the exact failure
    mode V1 was built to avoid.
    """

    COMPUTED = "COMPUTED"                # derived from stored quantitative data
    PARTIALLY_COMPUTED = "PARTIALLY_COMPUTED"   # data-derived base, analyst adjustment
    ANALYST_INPUT = "ANALYST_INPUT"      # supplied judgement, carried through untouched
    UNAVAILABLE = "UNAVAILABLE"          # neither available; force omitted, not guessed


class IndustryAttractiveness(str, Enum):
    """Porter's read: the weaker the five forces, the more profitable the industry."""

    ATTRACTIVE = "ATTRACTIVE"            # weak forces, structural profit available
    MODERATE = "MODERATE"
    UNATTRACTIVE = "UNATTRACTIVE"        # strong forces, profit competed away


class TrendDirection(str, Enum):
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    DETERIORATING = "DETERIORATING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class SensitivityVerdict(str, Enum):
    """How robust a quadrant placement is to a single-input change."""

    ROBUST = "ROBUST"                    # no single input flips it within its plausible range
    FRAGILE = "FRAGILE"                  # at least one input flips it with a modest change
    KNIFE_EDGE = "KNIFE_EDGE"            # already borderline, or flips on a trivial change


# --------------------------------------------------------------------------
# V3
# --------------------------------------------------------------------------


class VerdictStability(str, Enum):
    """How much of the sampled uncertainty the point verdict survives.

    Banded from the Shannon entropy of the quadrant probabilities, in bits.
    Zero means every draw agreed; log2(3) = 1.585 means a three-way coin flip.
    """

    DECISIVE = "DECISIVE"        # the draws overwhelmingly agree
    LEANING = "LEANING"          # a clear modal quadrant with real runner-up mass
    CONTESTED = "CONTESTED"      # the verdict is a coin flip; do not quote it alone


class AllocationOutcome(str, Enum):
    """What the budget-constrained allocator did with one business unit."""

    FUNDED = "FUNDED"                # received its full capital_requested
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"   # floor plus some, but short of the request
    FLOOR_ONLY = "FLOOR_ONLY"        # kept operating, received nothing discretionary
    UNFUNDED = "UNFUNDED"            # no floor and nothing discretionary
    CONTRIBUTOR = "CONTRIBUTOR"      # HARVEST_DIVEST: funds the pool rather than drawing


class MetricDerivation(str, Enum):
    """How a benchmark metric is obtained from XBRL facts."""

    DIRECT = "DIRECT"            # one concept, taken as reported
    RATIO = "RATIO"              # numerator / denominator x 100, same period and unit
    GROWTH = "GROWTH"            # (value_T / value_T-1 - 1) x 100
    NOT_DERIVABLE = "NOT_DERIVABLE"   # no honest XBRL proxy exists; declared, not faked
