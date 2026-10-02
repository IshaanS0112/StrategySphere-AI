"""Shared fixtures."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Must happen before app.config is imported anywhere: get_settings is cached,
# so the first read of DATABASE_URL is the one that sticks.
_TMP_DB = Path(tempfile.mkdtemp(prefix="strategysphere-tests-")) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ.setdefault("ANTHROPIC_API_KEY", "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.services.market_structure import assess_market_structure  # noqa: E402


@pytest.fixture
def settings() -> Settings:
    """Default parameter set, isolated from any .env on the developer's machine."""
    return Settings(_env_file=None)


@pytest.fixture
def strong_financials() -> dict:
    """A company comfortably ahead of the default industry bands on every axis."""
    return {
        "revenue_growth_pct": 22.0,      # vs 8.0 default -> +175%
        "gross_margin_pct": 62.0,        # vs 40.0        -> +55%
        "operating_margin_pct": 21.0,    # vs 12.0        -> +75%
        "net_margin_pct": 14.0,          # vs 8.0         -> +75%
        "market_share_pct": 28.0,        # vs 10.0        -> +180%
        "debt_to_equity": 0.4,           # vs 1.0, lower is better -> +60%
    }


@pytest.fixture
def weak_financials() -> dict:
    """The mirror image: behind the bands everywhere."""
    return {
        "revenue_growth_pct": 1.0,
        "gross_margin_pct": 18.0,
        "operating_margin_pct": 3.0,
        "net_margin_pct": 1.0,
        "market_share_pct": 3.0,
        "debt_to_equity": 2.6,
    }


@pytest.fixture
def growth_market() -> dict:
    return {
        "market_growth_pct": 18.0,
        "market_size_usd_bn": 40.0,
        "industry_operating_margin_pct": 20.0,
    }


@pytest.fixture
def declining_market() -> dict:
    return {
        "market_growth_pct": 1.0,
        "market_size_usd_bn": 0.5,
        "industry_operating_margin_pct": 3.0,
    }


@pytest.fixture
def competitors() -> list[dict]:
    """Four rivals with prices, shares, features, and financials."""
    return [
        {
            "competitor_name": "Rival A",
            "price_point": 100.0,
            "market_share_pct": 20.0,
            "feature_scores": {"speed": 3, "support": 4, "uptime": 3},
            "financial_data": {"operating_margin_pct": 10.0, "gross_margin_pct": 38.0},
        },
        {
            "competitor_name": "Rival B",
            "price_point": 110.0,
            "market_share_pct": 15.0,
            "feature_scores": {"speed": 2, "support": 3, "uptime": 4},
            "financial_data": {"operating_margin_pct": 12.0, "gross_margin_pct": 42.0},
        },
        {
            "competitor_name": "Rival C",
            "price_point": 95.0,
            "market_share_pct": 12.0,
            "feature_scores": {"speed": 4, "support": 2, "uptime": 3},
            "financial_data": {"operating_margin_pct": 8.0, "gross_margin_pct": 35.0},
        },
        {
            "competitor_name": "Rival D",
            "price_point": 105.0,
            "market_share_pct": 8.0,
            "feature_scores": {"speed": 3, "support": 3, "uptime": 2},
            "financial_data": {"operating_margin_pct": 14.0, "gross_margin_pct": 45.0},
        },
    ]


@pytest.fixture
def neutral_concentration(settings: Settings):
    """Market structure with no shares supplied -> neutral 3.0 intensity."""
    return assess_market_structure(
        company_market_share_pct=None,
        competitors=[],
        analyst_intensity_override=None,
        settings=settings,
    )


@pytest.fixture
def client():
    """FastAPI TestClient over a fresh SQLite schema."""
    from fastapi.testclient import TestClient

    from app.db.session import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


# --------------------------------------------------------------------------
# V3: EDGAR fixtures Every EDGAR test runs against recorded-shape JSON on disk
# through the real EdgarClient.

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "edgar"


def fixture_name_for(url: str) -> str:
    """Map a data.sec.gov URL onto a fixture filename."""
    trimmed = url.removesuffix(".json")
    if "/frames/" in url:
        # .../frames/us-gaap/{concept}/{unit}/{period}.json
        parts = trimmed.split("/")
        concept, _unit, period = parts[-3], parts[-2], parts[-1]
        return f"frames-{concept}-{period}"
    if "/submissions/" in url:
        return f"submissions-{trimmed.split('/')[-1]}"
    raise AssertionError(f"no fixture mapping for {url}")


class RecordedTransport:
    """Serves fixture files and records every URL it was asked for."""

    def __init__(self, missing_ok: bool = False) -> None:
        self.calls: list[str] = []
        self.missing_ok = missing_ok

    def __call__(self, url: str, headers: dict, timeout: float) -> bytes:
        self.calls.append(url)
        self.headers = headers
        name = fixture_name_for(url)
        path = FIXTURE_DIR / f"{name}.json"
        if not path.is_file():
            if self.missing_ok:
                import urllib.error

                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            raise AssertionError(f"fixture {path} missing")
        return path.read_bytes()


@pytest.fixture
def recorded_transport() -> "RecordedTransport":
    # missing_ok: a concept with no frame for a period 404s in real life too,
    # and the candidate resolver has to survive it.
    return RecordedTransport(missing_ok=True)


@pytest.fixture
def edgar_client(tmp_path, recorded_transport):
    """A real EdgarClient wired to fixtures, a temp cache, and a fake clock."""
    from app.services.edgar.client import EdgarClient

    now = [0.0]

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    client = EdgarClient(
        user_agent="StrategySphere Tests tests@example.com",
        cache_dir=tmp_path / "edgar-cache",
        requests_per_second=1000.0,   # the limiter has its own tests
        transport=recorded_transport,
        clock=clock,
        sleep=sleep,
    )
    client.test_clock = now      # type: ignore[attr-defined]
    return client


@pytest.fixture
def db_session():
    """A real session against a fresh schema, plus the engine for query counting."""
    from app.db.session import Base, SessionLocal, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session, engine
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
