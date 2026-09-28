"""The read layer, and a guard against the N+1 coming back.

These tests count SQL statements. That is the only way to test this: the point
of the change is that ``company.swot_analyses[-1]`` and
``queries.latest_swot()`` return the same object while asking the database for
very different amounts of work, and a test that only checks the return value
would pass on either implementation.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest

from app.db import queries
from app.models import Company, MarketAttractiveness, SwotAnalysis, UncertaintyAnalysis


@contextmanager
def counting(engine):
    from sqlalchemy import event

    seen: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", before)


@pytest.fixture
def seeded(db_session):
    """One entity, three periods, five stored runs each."""
    db, engine = db_session
    ids = []
    for index in range(3):
        company = Company(
            name=f"Period {index}",
            industry="saas",
            financial_data={},
            market_data={},
            feature_scores={},
            qualitative_inputs=[],
            data_source="test fixture",
            entity_key="acme",
            period_label=f"FY202{index}",
        )
        db.add(company)
        db.flush()
        ids.append(company.id)
        for run in range(5):
            db.add(
                SwotAnalysis(
                    company_id=company.id,
                    strengths=[{"factor": f"run-{run}"}],
                    weaknesses=[],
                    opportunities=[],
                    threats=[],
                    calculation_basis={"run": run},
                )
            )
            db.add(
                MarketAttractiveness(
                    company_id=company.id,
                    market_growth_score=4.0,
                    market_size_score=4.0,
                    profitability_score=4.0,
                    competitive_intensity_score=3.0,
                    overall_attractiveness_score=3.0 + run / 10,
                    competitive_strength_score=3.0,
                    quadrant="SELECTIVE_INVEST",
                    borderline=False,
                    calculation_basis={"run": run},
                )
            )
    db.commit()
    return db, engine, ids


class TestLatest:
    def test_it_returns_the_most_recent_row(self, seeded):
        db, _engine, ids = seeded
        row = queries.latest_swot(db, ids[0])
        assert row is not None
        assert row.strengths[0]["factor"] == "run-4"

    def test_it_agrees_with_the_relationship_it_replaces(self, seeded):
        db, _engine, ids = seeded
        company = db.get(Company, ids[0])
        assert queries.latest_swot(db, ids[0]).id == company.swot_analyses[-1].id
        assert queries.latest_matrix(db, ids[0]).id == company.attractiveness_results[-1].id

    def test_a_company_with_no_runs_returns_none(self, db_session):
        db, _engine = db_session
        assert queries.latest_swot(db, uuid.uuid4()) is None

    def test_it_reads_one_row_not_the_collection(self, seeded):
        db, engine, ids = seeded
        db.expunge_all()
        with counting(engine) as statements:
            queries.latest_swot(db, ids[0])
        assert len(statements) == 1
        # The guard that matters: without LIMIT this is a full collection read
        # again, and nothing else in the suite would notice.
        assert "LIMIT" in statements[0].upper()

    def test_ties_break_deterministically(self, db_session):
        # Two rows written in the same microsecond must still order stably, or
        # "the latest result" becomes whichever the database felt like.
        from datetime import datetime, timezone

        db, _engine = db_session
        company = Company(
            name="Tied",
            financial_data={},
            market_data={},
            feature_scores={},
            qualitative_inputs=[],
            data_source="test",
        )
        db.add(company)
        db.flush()
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for _ in range(5):
            db.add(
                SwotAnalysis(
                    company_id=company.id,
                    strengths=[],
                    weaknesses=[],
                    opportunities=[],
                    threats=[],
                    calculation_basis={},
                    generated_at=stamp,
                )
            )
        db.commit()
        first = queries.latest_swot(db, company.id).id
        for _ in range(5):
            db.expunge_all()
            assert queries.latest_swot(db, company.id).id == first


class TestLatestForMany:
    def test_one_query_regardless_of_company_count(self, seeded):
        db, engine, ids = seeded
        db.expunge_all()
        with counting(engine) as statements:
            result = queries.latest_for_many(db, MarketAttractiveness, ids)
        assert set(result) == set(ids)
        # A windowed selection plus one IN re-fetch. The number that matters is
        # that it does not grow with the number of companies.
        assert len(statements) <= 2

    def test_it_scales_flat(self, db_session):
        db, engine = db_session
        ids = []
        for index in range(12):
            company = Company(
                name=f"C{index}",
                financial_data={},
                market_data={},
                feature_scores={},
                qualitative_inputs=[],
                data_source="test",
            )
            db.add(company)
            db.flush()
            ids.append(company.id)
            db.add(
                MarketAttractiveness(
                    company_id=company.id,
                    market_growth_score=3,
                    market_size_score=3,
                    profitability_score=3,
                    competitive_intensity_score=3,
                    overall_attractiveness_score=3,
                    competitive_strength_score=3,
                    quadrant="SELECTIVE_INVEST",
                    borderline=False,
                    calculation_basis={},
                )
            )
        db.commit()
        db.expunge_all()
        with counting(engine) as statements:
            queries.latest_for_many(db, MarketAttractiveness, ids)
        assert len(statements) <= 2, "query count must not grow with the number of companies"

    def test_it_picks_the_latest_per_company(self, seeded):
        db, _engine, ids = seeded
        result = queries.latest_for_many(db, MarketAttractiveness, ids)
        for company_id in ids:
            assert result[company_id].overall_attractiveness_score == pytest.approx(3.4)

    def test_an_empty_list_asks_nothing(self, seeded):
        db, engine, _ids = seeded
        with counting(engine) as statements:
            assert queries.latest_for_many(db, MarketAttractiveness, []) == {}
        assert statements == []

    def test_companies_without_rows_are_simply_absent(self, seeded):
        db, _engine, ids = seeded
        missing = uuid.uuid4()
        result = queries.latest_for_many(db, UncertaintyAnalysis, ids + [missing])
        assert missing not in result


class TestEntityOrdering:
    def test_periods_come_back_in_timeline_order(self, seeded):
        db, _engine, _ids = seeded
        companies = queries.companies_for_entity(db, "acme")
        assert [c.period_label for c in companies] == ["FY2020", "FY2021", "FY2022"]
