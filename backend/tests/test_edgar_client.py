"""The client's three load-bearing behaviours: identity, rate, and cache.

None of these tests touch the network. The transport is injected; the one test
that cares about the real one asserts it is never reached.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from app.services.edgar.client import (
    ALLOWED_HOSTS,
    EdgarClient,
    EdgarConfigError,
    EdgarFetchError,
    EdgarOfflineError,
    TokenBucket,
    validate_user_agent,
)


class TestUserAgentEnforcement:
    """SEC guidance requires a declared requester. There is no default."""

    @pytest.mark.parametrize("raw", ["", "   ", None])
    def test_missing_user_agent_raises_on_construction(self, raw, tmp_path):
        with pytest.raises(EdgarConfigError) as exc:
            EdgarClient(user_agent=raw, cache_dir=tmp_path)
        assert "EDGAR_USER_AGENT" in str(exc.value)

    def test_user_agent_without_contact_details_is_rejected(self, tmp_path):
        # The real failure mode is somebody pasting a product name and believing
        # they have complied.
        with pytest.raises(EdgarConfigError) as exc:
            EdgarClient(user_agent="StrategySphere", cache_dir=tmp_path)
        assert "contact" in str(exc.value).lower()

    def test_a_name_and_an_email_is_accepted(self):
        assert validate_user_agent("Jane Doe jane@example.com") == "Jane Doe jane@example.com"

    def test_the_declared_agent_is_sent_on_every_request(self, edgar_client, recorded_transport):
        edgar_client.frames("GrossProfit", period="CY2024")
        assert recorded_transport.headers["User-Agent"] == (
            "StrategySphere Tests tests@example.com"
        )

    def test_offline_mode_needs_no_user_agent(self, tmp_path):
        # Offline never reaches the network, and CI has no contact details to
        # supply. Demanding one would make the fixtures unusable.
        client = EdgarClient(user_agent=None, cache_dir=tmp_path, offline=True)
        assert client.user_agent == ""


class TestRateLimiting:
    def test_a_burst_is_capped_at_the_configured_rate(self):
        now = [0.0]
        slept: list[float] = []

        def clock() -> float:
            return now[0]

        def sleep(seconds: float) -> None:
            slept.append(seconds)
            now[0] += seconds

        bucket = TokenBucket(5.0, clock=clock, sleep=sleep)
        # The first five are free (full bucket); the sixth must wait.
        for _ in range(5):
            assert bucket.take() == 0.0
        assert bucket.take() == pytest.approx(0.2, abs=1e-9)
        assert slept == [pytest.approx(0.2)]

    def test_tokens_refill_with_elapsed_time(self):
        now = [0.0]

        def clock() -> float:
            return now[0]

        bucket = TokenBucket(5.0, clock=clock, sleep=lambda s: None)
        for _ in range(5):
            bucket.take()
        now[0] += 1.0          # a full second buys the whole bucket back
        assert bucket.take() == 0.0

    def test_a_non_positive_rate_is_refused(self):
        with pytest.raises(EdgarConfigError):
            TokenBucket(0.0)

    def test_settings_refuse_a_rate_above_the_published_ceiling(self):
        from app.config import Settings

        with pytest.raises(ValueError) as exc:
            Settings(_env_file=None, edgar_requests_per_second=25.0)
        assert "10" in str(exc.value)

    def test_the_client_rate_limits_its_fetches(self, tmp_path, recorded_transport):
        now = [0.0]

        def clock() -> float:
            return now[0]

        def sleep(seconds: float) -> None:
            now[0] += seconds

        client = EdgarClient(
            user_agent="Jane Doe jane@example.com",
            cache_dir=tmp_path,
            requests_per_second=2.0,
            transport=recorded_transport,
            clock=clock,
            sleep=sleep,
        )
        for concept in ("GrossProfit", "Revenues", "NetIncomeLoss", "OperatingIncomeLoss"):
            client.frames(concept, period="CY2024")
        # Capacity 2, so two free and two waits of half a second each.
        assert client.stats.seconds_waiting == pytest.approx(1.0)


class TestDiskCache:
    def test_a_second_call_is_served_from_disk(self, edgar_client, recorded_transport):
        edgar_client.frames("GrossProfit", period="CY2024")
        edgar_client.frames("GrossProfit", period="CY2024")
        assert len(recorded_transport.calls) == 1
        assert edgar_client.stats.cache_hits == 1
        assert edgar_client.stats.requests_made == 1

    def test_the_cache_key_is_the_url(self, edgar_client):
        a = edgar_client.cache_path("https://data.sec.gov/api/xbrl/frames/us-gaap/A/USD/CY2024.json")
        b = edgar_client.cache_path("https://data.sec.gov/api/xbrl/frames/us-gaap/B/USD/CY2024.json")
        assert a != b
        assert a == edgar_client.cache_path(
            "https://data.sec.gov/api/xbrl/frames/us-gaap/A/USD/CY2024.json"
        )

    def test_a_corrupt_cache_entry_is_discarded_rather_than_served(
        self, edgar_client, recorded_transport
    ):
        url = "https://data.sec.gov/api/xbrl/frames/us-gaap/GrossProfit/USD/CY2024.json"
        edgar_client.get_json(url)
        edgar_client.cache_path(url).write_text("{ truncated")
        payload = edgar_client.get_json(url)
        assert payload["tag"] == "GrossProfit"
        assert len(recorded_transport.calls) == 2

    def test_offline_serves_the_cache_and_never_fetches(self, tmp_path, recorded_transport):
        url = "https://data.sec.gov/api/xbrl/frames/us-gaap/GrossProfit/USD/CY2024.json"
        warm = EdgarClient(
            user_agent="Jane Doe jane@example.com",
            cache_dir=tmp_path,
            transport=recorded_transport,
        )
        warm.get_json(url)

        def exploding_transport(*_args, **_kwargs):
            raise AssertionError("offline mode reached the network")

        offline = EdgarClient(
            user_agent=None, cache_dir=tmp_path, offline=True, transport=exploding_transport
        )
        assert offline.get_json(url)["tag"] == "GrossProfit"

    def test_offline_fails_loudly_on_a_miss(self, tmp_path):
        offline = EdgarClient(user_agent=None, cache_dir=tmp_path, offline=True)
        with pytest.raises(EdgarOfflineError) as exc:
            offline.frames("Assets", period="CY1999")
        # The message has to name the URL and the expected cache path, or the
        # only way to fix a miss is to read the source.
        assert "CY1999" in str(exc.value)
        assert str(tmp_path) in str(exc.value)


class TestScopeAndFailures:
    def test_it_refuses_any_host_outside_sec_gov(self, edgar_client):
        with pytest.raises(EdgarConfigError) as exc:
            edgar_client.get_json("https://example.com/prices.json")
        assert all(host in str(exc.value) for host in ALLOWED_HOSTS)

    def test_an_http_error_becomes_a_fetch_error(self, tmp_path):
        def failing(url, headers, timeout):
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)

        client = EdgarClient(
            user_agent="Jane Doe jane@example.com", cache_dir=tmp_path, transport=failing
        )
        with pytest.raises(EdgarFetchError) as exc:
            client.frames("Assets", period="CY2024")
        assert "429" in str(exc.value)
        assert client.stats.failures == 1

    def test_a_non_json_body_becomes_a_fetch_error(self, tmp_path):
        client = EdgarClient(
            user_agent="Jane Doe jane@example.com",
            cache_dir=tmp_path,
            transport=lambda *_a, **_k: b"<html>maintenance</html>",
        )
        with pytest.raises(EdgarFetchError):
            client.frames("Assets", period="CY2024")
        # Nothing unparseable is ever written to the cache.
        assert not list((client.cache_dir).glob("*.json"))

    def test_a_failed_fetch_is_not_cached(self, tmp_path, recorded_transport):
        client = EdgarClient(
            user_agent="Jane Doe jane@example.com",
            cache_dir=tmp_path,
            transport=recorded_transport,
        )
        with pytest.raises(EdgarFetchError):
            client.frames("NoSuchConcept", period="CY2024")
        assert client.stats.cache_writes == 0


class TestEndpointUrls:
    def test_cik_is_zero_padded_to_ten_digits(self, edgar_client, recorded_transport):
        edgar_client.submissions(1000)
        assert recorded_transport.calls[-1].endswith("CIK0000001000.json")

    def test_frames_url_shape(self, edgar_client, recorded_transport):
        edgar_client.frames("GrossProfit", unit="USD", period="CY2024")
        assert recorded_transport.calls[-1] == (
            "https://data.sec.gov/api/xbrl/frames/us-gaap/GrossProfit/USD/CY2024.json"
        )

    def test_cached_payload_round_trips(self, edgar_client):
        payload = edgar_client.frames("GrossProfit", period="CY2024")
        on_disk = json.loads(
            edgar_client.cache_path(
                "https://data.sec.gov/api/xbrl/frames/us-gaap/GrossProfit/USD/CY2024.json"
            ).read_text()
        )
        assert on_disk == payload
