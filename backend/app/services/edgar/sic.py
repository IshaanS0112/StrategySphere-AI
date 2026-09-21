"""SIC code to sector class, declared as a table rather than a chain of ifs.

SIC codes come from the submissions endpoint, which returns ``sic`` and
``sicDescription`` per company. The SEC still classifies every filer with the
Standard Industrial Classification, which the US census retired in 1997 in
favour of NAICS; EDGAR did not follow, so SIC is what the data actually has.

The sector names on the right of this table are the keys the benchmark table
already uses (``saas``, ``retail``, ``manufacturing``), extended where a range
plainly needed its own row. They are matched against ``Company.industry``
lowercased, so a company created with ``industry="SaaS"`` finds the ``saas``
row and one with ``industry="Fintech"`` falls through to ``_default`` — which
is the pre-existing behaviour of ``industry_benchmark()`` and needed no change.

**Ranges are half-open on the right and ordered most-specific-first.** 7372
(prepackaged software) must be tested before the 7000-8999 services block, or
every software company lands in ``services``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SicRange:
    low: int
    high: int            # inclusive
    sector: str
    description: str

    def contains(self, code: int) -> bool:
        return self.low <= code <= self.high


# Order matters: first match wins, so narrow ranges precede the blocks that
# contain them. Sources: SEC Division of Corporation Finance SIC code list.
SIC_RANGES: tuple[SicRange, ...] = (
    # --- narrow, must precede their parent blocks -------------------------
    SicRange(7372, 7372, "saas", "Prepackaged software"),
    SicRange(7370, 7379, "saas", "Computer programming, data processing, services"),
    SicRange(2833, 2836, "biotech", "Pharmaceutical and biological products"),
    SicRange(8731, 8731, "biotech", "Commercial physical and biological research"),
    SicRange(3674, 3674, "semiconductors", "Semiconductors and related devices"),
    # --- broad blocks -----------------------------------------------------
    SicRange(100, 999, "agriculture", "Agriculture, forestry and fishing"),
    SicRange(1000, 1119, "mining", "Metal mining"),
    SicRange(1200, 1399, "energy", "Coal, oil and gas extraction"),
    SicRange(1400, 1499, "mining", "Nonmetallic minerals"),
    SicRange(1500, 1799, "construction", "Construction"),
    SicRange(2000, 3999, "manufacturing", "Manufacturing"),
    SicRange(4000, 4799, "transport", "Transportation"),
    SicRange(4800, 4899, "telecom", "Communications"),
    SicRange(4900, 4999, "utilities", "Electric, gas and sanitary services"),
    SicRange(5000, 5199, "wholesale", "Wholesale trade"),
    SicRange(5200, 5999, "retail", "Retail trade"),
    SicRange(6000, 6499, "financials", "Depository and non-depository institutions, insurance"),
    SicRange(6500, 6599, "real_estate", "Real estate"),
    SicRange(6600, 6999, "financials", "Holding and other investment offices"),
    SicRange(7000, 7369, "services", "Hotels and business services"),
    SicRange(7380, 7999, "services", "Services, amusement and recreation"),
    SicRange(8000, 8099, "healthcare", "Health services"),
    SicRange(8100, 8999, "services", "Legal, educational and professional services"),
    SicRange(9100, 9999, "public_admin", "Public administration and non-classifiable"),
)

# Every sector this table can emit. Kept explicit so the builder can report the
# sectors that produced no companies at all, which is different from a sector
# that produced too few.
KNOWN_SECTORS: tuple[str, ...] = tuple(
    dict.fromkeys(entry.sector for entry in SIC_RANGES)
)

UNCLASSIFIED = "_unclassified"


def sector_for_sic(sic: int | str | None) -> str:
    """Map one SIC code onto a sector class.

    An absent, blank, or unrecognised code returns ``_unclassified`` rather
    than guessing a sector. Those companies still count toward the all-filer
    median — they are perfectly good data about filers in general, just not
    about any particular sector.
    """
    if sic is None:
        return UNCLASSIFIED
    try:
        code = int(str(sic).strip())
    except (TypeError, ValueError):
        return UNCLASSIFIED
    for entry in SIC_RANGES:
        if entry.contains(code):
            return entry.sector
    return UNCLASSIFIED


def describe_sic(sic: int | str | None) -> str:
    """Human-readable SIC block name, for the provenance trace."""
    if sic is None:
        return "no SIC reported"
    try:
        code = int(str(sic).strip())
    except (TypeError, ValueError):
        return f"unparseable SIC {sic!r}"
    for entry in SIC_RANGES:
        if entry.contains(code):
            return f"{code} {entry.description}"
    return f"{code} outside the mapped ranges"


def sic_from_submissions(payload: dict) -> tuple[str, str]:
    """Extract ``(sic, sicDescription)`` from a submissions payload, defensively."""
    sic = payload.get("sic")
    description = payload.get("sicDescription")
    return (
        str(sic).strip() if sic not in (None, "") else "",
        str(description).strip() if description else "",
    )
