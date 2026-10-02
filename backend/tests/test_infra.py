"""Errors, caching, observability and pagination."""

from __future__ import annotations

import json
import time
import uuid

import pytest

from app import errors
from app.db.pagination import InvalidCursor, clamp_limit, decode_cursor, encode_cursor
from app.obs import JsonFormatter, Metrics, new_request_id
from app.services.cache import TTLCache, benchmark_table, etag_for, invalidate_benchmark_table


class TestErrorTaxonomy:
    def test_every_kind_has_a_distinct_code(self):
        kinds = [v for v in vars(errors).values() if isinstance(v, errors.ErrorKind)]
        codes = [k.code for k in kinds]
        assert len(codes) == len(set(codes))
        assert len(codes) >= 10

    def test_a_problem_document_has_the_rfc_fields(self):
        problem = errors.stage_order("run the matrix first", needs="matrix").to_problem(
            "/companies/x/uncertainty", "abc123"
        )
        for field in ("type", "title", "status", "code", "detail", "instance", "request_id"):
            assert field in problem
        assert problem["status"] == 409
        assert problem["missing_stage"] == "matrix"

    def test_detail_survives_so_existing_clients_keep_working(self, client):
        company = client.post(
            "/companies",
            json={
                "name": "Empty Co",
                "data_source": "test fixture with nothing in it",
                "financial_data": {},
                "market_data": {},
            },
        ).json()["id"]
        response = client.post(f"/companies/{company}/market-attractiveness")
        assert response.status_code == 409
        body = response.json()
        # The frontend reads `detail`; the machine code is additive.
        assert "Run the SWOT analysis first" in body["detail"]
        assert body["code"] == "STAGE_ORDER"
        assert body["missing_stage"] == "swot"

    def test_the_media_type_is_problem_json(self, client):
        response = client.get(f"/companies/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")

    def test_validation_failures_use_the_same_shape(self, client):
        response = client.post("/companies", json={"name": ""})
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "INVALID_INPUT"
        # FastAPI's per-field detail is kept, because it is genuinely useful.
        assert isinstance(body["errors"], list)
        assert body["errors"][0]["field"]

    def test_the_request_id_is_echoed_into_the_problem(self, client):
        response = client.get(f"/companies/{uuid.uuid4()}", headers={"X-Request-ID": "trace-me"})
        assert response.json()["request_id"] == "trace-me"
        assert response.headers["X-Request-ID"] == "trace-me"


class TestCache:
    def test_a_hit_does_not_call_the_factory_again(self):
        cache = TTLCache("t", ttl_seconds=60)
        calls = []
        for _ in range(3):
            cache.get_or_set("k", lambda: calls.append(1) or "v")
        assert len(calls) == 1
        assert cache.stats.hits == 2
        assert cache.stats.hit_rate == pytest.approx(2 / 3, abs=1e-4)

    def test_entries_expire(self):
        cache = TTLCache("t", ttl_seconds=0.01)
        cache.get_or_set("k", lambda: "first")
        time.sleep(0.02)
        assert cache.get_or_set("k", lambda: "second") == "second"

    def test_it_is_bounded(self):
        cache = TTLCache("t", maxsize=3, ttl_seconds=60)
        for index in range(10):
            cache.get_or_set(index, lambda: index)
        assert len(cache) == 3
        assert cache.stats.evictions == 7

    def test_invalidate_clears(self):
        cache = TTLCache("t", ttl_seconds=60)
        cache.get_or_set("k", lambda: 1)
        cache.invalidate()
        assert cache.get_or_set("k", lambda: 2) == 2

    def test_the_benchmark_table_is_parsed_once(self, tmp_path):
        path = tmp_path / "bench.json"
        path.write_text(json.dumps({"saas": {"gross_margin_pct": 70.0}}))
        invalidate_benchmark_table()
        first = benchmark_table(str(path))
        second = benchmark_table(str(path))
        assert first is second

    def test_editing_the_file_invalidates_it_without_a_restart(self, tmp_path):
        # The reason this is keyed on (path, mtime, size) rather than a TTL: an
        # operator who rebuilds the table should not wait out a clock.
        path = tmp_path / "bench.json"
        path.write_text(json.dumps({"saas": {"gross_margin_pct": 70.0}}))
        invalidate_benchmark_table()
        first = benchmark_table(str(path))
        time.sleep(0.01)
        path.write_text(json.dumps({"saas": {"gross_margin_pct": 44.0}}))
        second = benchmark_table(str(path))
        assert second is not first
        assert second.rows["saas"]["gross_margin_pct"] == 44.0

    def test_a_missing_file_does_not_wedge_the_cache(self, tmp_path):
        invalidate_benchmark_table()
        table = benchmark_table(str(tmp_path / "nope.json"))
        assert table.rows, "should fall back to the built-in table"

    def test_etags_are_stable_and_content_sensitive(self):
        assert etag_for({"a": 1, "b": 2}) == etag_for({"b": 2, "a": 1})
        assert etag_for({"a": 1}) != etag_for({"a": 2})


class TestMetrics:
    def test_counters_and_labels_render(self):
        metrics = Metrics()
        metrics.inc("http_requests_total", {"route": "/x", "status": "200"})
        metrics.inc("http_requests_total", {"route": "/x", "status": "200"})
        rendered = metrics.render()
        assert '# TYPE http_requests_total counter' in rendered
        assert 'http_requests_total{route="/x",status="200"} 2' in rendered

    def test_histograms_are_cumulative(self):
        metrics = Metrics(buckets=(0.1, 1.0))
        for value in (0.05, 0.5, 5.0):
            metrics.observe("d", value)
        rendered = metrics.render()
        assert 'd_bucket{le="0.1"} 1' in rendered
        assert 'd_bucket{le="1.0"} 2' in rendered
        assert 'd_bucket{le="+Inf"} 3' in rendered
        assert "d_count 3" in rendered

    def test_label_values_are_escaped(self):
        metrics = Metrics()
        metrics.inc("c", {"route": 'a"b'})
        assert '\\"' in metrics.render()

    def test_the_endpoint_serves_prometheus_text(self, client):
        client.get("/health")
        response = client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert "http_requests_total" in response.text
        assert "app_uptime_seconds" in response.text

    def test_routes_are_labelled_by_template_not_path(self, client):
        # A label per company id is an unbounded cardinality explosion - the
        # classic way to take down a metrics backend with your own telemetry.
        client.get(f"/companies/{uuid.uuid4()}")
        text = client.get("/metrics").text
        assert "{company_id}" in text


class TestRequestIds:
    def test_one_is_generated_when_absent(self, client):
        value = client.get("/health").headers["X-Request-ID"]
        assert value and len(value) == 16

    def test_an_inbound_one_is_honoured(self, client):
        response = client.get("/health", headers={"X-Request-ID": "upstream-123"})
        assert response.headers["X-Request-ID"] == "upstream-123"

    def test_two_requests_get_different_ids(self, client):
        assert client.get("/health").headers["X-Request-ID"] != (
            client.get("/health").headers["X-Request-ID"]
        )

    def test_server_timing_is_reported(self, client):
        assert client.get("/health").headers["Server-Timing"].startswith("app;dur=")

    def test_the_json_formatter_folds_in_context(self):
        import logging

        record = logging.LogRecord("t", logging.INFO, "f", 1, "hello", None, None)
        record.ctx_status = 200
        payload = json.loads(JsonFormatter().format(record))
        assert payload["msg"] == "hello"
        assert payload["status"] == 200
        assert "request_id" in payload

    def test_ids_are_unique(self):
        assert len({new_request_id() for _ in range(1000)}) == 1000


class TestPaginationPrimitives:
    def test_a_cursor_round_trips(self):
        from datetime import datetime, timezone

        stamp = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
        identifier = uuid.uuid4()
        assert decode_cursor(encode_cursor(stamp, identifier)) == (stamp, identifier)

    @pytest.mark.parametrize("bad", ["", "!!!", "YWJj", "not-base64-at-all~~"])
    def test_a_forged_cursor_is_rejected_with_advice(self, bad):
        with pytest.raises(InvalidCursor) as exc:
            decode_cursor(bad)
        assert "start from the first page" in str(exc.value)

    def test_the_limit_is_clamped(self):
        assert clamp_limit(None, 25, 200) == 25
        assert clamp_limit(5000, 25, 200) == 200
        assert clamp_limit(0, 25, 200) == 1
