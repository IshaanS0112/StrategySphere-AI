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
    """Where a SWOT metric's comparison point came from."""

    PEER_SET = "PEER_SET"           # median of the competitors supplied
    INDUSTRY_TABLE = "INDUSTRY_TABLE"   # configured industry reference band
    UNAVAILABLE = "UNAVAILABLE"     # metric skipped, no benchmark to compare to


class NarrativeSource(str, Enum):
    LLM = "llm"
    TEMPLATE_FALLBACK = "template_fallback"
