"""us-gaap candidate tags per metric, and the rules that turn facts into ratios.

**XBRL tags are not uniform across filers.** The same economic quantity appears
under different ``us-gaap`` tags depending on the filer, its industry and the
year it adopted a standard. Revenue is the worst of them: a company on the
post-ASC-606 tag reports ``RevenueFromContractWithCustomerExcludingAssessedTax``,
an older or simpler filer reports ``Revenues``, and a third reports
``SalesRevenueNet``. All three mean revenue. None of them is present for
everybody.

So every metric carries an **ordered candidate list**. The builder tries the
tags in order, takes the first that resolves for a given company, and records
*which tag it was*. A company where no candidate resolves is dropped and
counted — never imputed, never filled with a sector average, never quietly
skipped. That is the V1 SWOT discipline ("the trace for every metric, including
the ones that were skipped and why") applied to real-world messy data, and the
coverage rate it produces is meaningfully below 100%. Reporting that number is
the work.

**Two metrics in METRIC_RULES have no honest XBRL proxy at all.** Market share
needs a market definition that no filing contains, and customer retention is
not a US-GAAP concept. They are declared ``NOT_DERIVABLE`` here rather than
approximated, and the built table simply has no row for them — which makes the
SWOT engine fall through to whatever other benchmark basis it has, exactly as
it does today for any metric the table does not cover.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.enums import MetricDerivation

# --------------------------------------------------------------------------
# Candidate tag lists, in resolution order
# --------------------------------------------------------------------------

REVENUE_TAGS: tuple[str, ...] = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
GROSS_PROFIT_TAGS: tuple[str, ...] = ("GrossProfit",)
OPERATING_INCOME_TAGS: tuple[str, ...] = ("OperatingIncomeLoss",)
NET_INCOME_TAGS: tuple[str, ...] = ("NetIncomeLoss",)
ASSETS_TAGS: tuple[str, ...] = ("Assets",)
CURRENT_LIABILITIES_TAGS: tuple[str, ...] = ("LiabilitiesCurrent",)
LIABILITIES_TAGS: tuple[str, ...] = ("Liabilities",)
EQUITY_TAGS: tuple[str, ...] = (
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
)
RND_TAGS: tuple[str, ...] = ("ResearchAndDevelopmentExpense",)


@dataclass(frozen=True)
class MetricSpec:
    """How one benchmark-table metric is built out of XBRL facts.

    ``key`` matches a key in ``benchmarks.METRIC_RULES`` exactly. A spec whose
    key is not in that table would build a column the SWOT engine never reads.
    """

    key: str
    label: str
    derivation: MetricDerivation
    numerator: tuple[str, ...] = ()
    denominator: tuple[str, ...] = ()
    # Ratios are reported in percentage points; debt-to-equity is a bare
    # multiple and must not be scaled.
    scale: float = 100.0
    note: str = ""
    # Sanity bounds. A filer reporting a 40,000% operating margin has a unit
    # error or a near-zero denominator, and one such row moves a mean but not a
    # median - which is exactly why the table publishes medians. The bounds
    # exist so the *coverage* count is not inflated by nonsense.
    plausible_range: tuple[float, float] = (-1e6, 1e6)
    concepts_used: tuple[str, ...] = field(default=())

    def all_tags(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.numerator + self.denominator))


METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec(
        key="revenue_growth_pct",
        label="Revenue growth",
        derivation=MetricDerivation.GROWTH,
        numerator=REVENUE_TAGS,
        note=(
            "Revenue for period T over revenue for T-1, both resolved through the "
            "same ordered candidate list. A company that resolved one period and "
            "not the other is dropped: comparing a post-606 revenue tag in T "
            "against a legacy tag in T-1 compares two different definitions."
        ),
        plausible_range=(-100.0, 1000.0),
    ),
    MetricSpec(
        key="gross_margin_pct",
        label="Gross margin",
        derivation=MetricDerivation.RATIO,
        numerator=GROSS_PROFIT_TAGS,
        denominator=REVENUE_TAGS,
        plausible_range=(-500.0, 100.0),
    ),
    MetricSpec(
        key="operating_margin_pct",
        label="Operating margin",
        derivation=MetricDerivation.RATIO,
        numerator=OPERATING_INCOME_TAGS,
        denominator=REVENUE_TAGS,
        plausible_range=(-1000.0, 100.0),
    ),
    MetricSpec(
        key="net_margin_pct",
        label="Net margin",
        derivation=MetricDerivation.RATIO,
        numerator=NET_INCOME_TAGS,
        denominator=REVENUE_TAGS,
        plausible_range=(-1000.0, 100.0),
    ),
    MetricSpec(
        key="return_on_capital_pct",
        label="Return on capital employed",
        derivation=MetricDerivation.RATIO,
        numerator=OPERATING_INCOME_TAGS,
        denominator=ASSETS_TAGS,
        note=(
            "EBIT over total assets, not the textbook EBIT / (assets - current "
            "liabilities). LiabilitiesCurrent is materially less widely tagged "
            "than Assets, and the textbook denominator would have cost roughly a "
            "third of the coverage for a refinement smaller than the spread "
            "between filers. The deviation is stated rather than hidden, and the "
            "resulting figure is systematically LOWER than a true ROCE."
        ),
        plausible_range=(-500.0, 200.0),
    ),
    MetricSpec(
        key="rnd_intensity_pct",
        label="R&D intensity",
        derivation=MetricDerivation.RATIO,
        numerator=RND_TAGS,
        denominator=REVENUE_TAGS,
        note=(
            "Only filers that tag an R&D expense resolve this, which is a "
            "selection effect and not a coverage failure: a company with no R&D "
            "line generally has no R&D. The sector median is therefore the median "
            "AMONG SPENDERS and reads high. Stated in the provenance block."
        ),
        plausible_range=(0.0, 1000.0),
    ),
    MetricSpec(
        key="debt_to_equity",
        label="Debt-to-equity",
        derivation=MetricDerivation.RATIO,
        numerator=LIABILITIES_TAGS,
        denominator=EQUITY_TAGS,
        scale=1.0,
        note=(
            "Total liabilities over book equity: a solvency ratio, not a "
            "financial-debt ratio. Interest-bearing debt is tagged too "
            "inconsistently across filers to resolve through a candidate list. "
            "Companies with negative book equity are dropped rather than "
            "reported as a negative leverage multiple, which reads as the "
            "opposite of what it means."
        ),
        plausible_range=(0.0, 100.0),
    ),
)

METRIC_SPEC_BY_KEY: dict[str, MetricSpec] = {spec.key: spec for spec in METRIC_SPECS}

# Declared, not faked. These are in benchmarks.METRIC_RULES and the SWOT engine
# scores them happily when a peer set supplies them - they simply cannot be
# sourced from XBRL, so an EDGAR-built table has no row for them.
NOT_DERIVABLE: dict[str, str] = {
    "market_share_pct": (
        "Market share requires a market definition. No filing contains one, and "
        "the denominator a filer would use is not comparable to the one a rival "
        "would use. Inventing it would be the exact failure this project exists "
        "to avoid."
    ),
    "customer_retention_pct": (
        "Not a US-GAAP concept. Some SaaS filers disclose net revenue retention "
        "in prose or in a custom extension taxonomy; neither is queryable "
        "through the standardised frames API, and a median built from the "
        "handful that do would describe those filers only."
    ),
}


def resolve_first(
    facts_by_tag: dict[str, float], candidates: tuple[str, ...]
) -> tuple[str, float] | None:
    """First candidate tag present, with its value. ``None`` if none resolves.

    Order is the whole point: the candidate list is a preference ranking, so a
    company reporting both ``Revenues`` and the ASC-606 tag is read through the
    606 tag on every metric, and never mixes the two between numerator and
    denominator of one ratio.
    """
    for tag in candidates:
        value = facts_by_tag.get(tag)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return tag, float(value)
    return None
