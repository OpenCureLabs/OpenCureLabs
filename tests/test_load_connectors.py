"""Load tests for connector resilient HTTP sessions.

Verifies that:
1. Retries fire on 429/500/502/503/504 with exponential backoff
2. Retry-After headers are respected
3. Concurrent requests don't cause cascading failures
4. Successful responses still work normally under load
"""

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))


# ── Mock HTTP Server ─────────────────────────────────────────────────────────


class _RequestTracker:
    """Thread-safe request counter for the mock server."""

    def __init__(self):
        self.lock = threading.Lock()
        self.requests: list[dict] = []
        self.fail_count = 0  # number of 429s to return before succeeding
        self.retry_after = None  # Retry-After header value
        self.response_body = json.dumps({"status": "ok"})
        self.fail_status = 429

    def record(self, path: str, status: int):
        with self.lock:
            self.requests.append({"path": path, "status": status, "time": time.time()})

    def should_fail(self) -> bool:
        with self.lock:
            count = sum(1 for r in self.requests if r["status"] >= 400)
            return count < self.fail_count


tracker = _RequestTracker()


class MockHandler(BaseHTTPRequestHandler):
    """HTTP handler that returns configurable 429/5xx responses."""

    def do_GET(self):
        if tracker.should_fail():
            status = tracker.fail_status
            tracker.record(self.path, status)
            self.send_response(status)
            if tracker.retry_after is not None:
                self.send_header("Retry-After", str(tracker.retry_after))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "rate limited"}).encode())
        else:
            tracker.record(self.path, 200)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(tracker.response_body.encode())

    def log_message(self, format, *args):
        pass  # Suppress server logs during tests


@pytest.fixture(scope="module")
def mock_server():
    """Start a mock HTTP server on a random port for the test module."""
    server = HTTPServer(("127.0.0.1", 0), MockHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture(autouse=True)
def reset_tracker():
    """Reset the request tracker between tests."""
    tracker.requests.clear()
    tracker.fail_count = 0
    tracker.retry_after = None
    tracker.response_body = json.dumps({"status": "ok"})
    tracker.fail_status = 429


# ── Tests ────────────────────────────────────────────────────────────────────


class TestRetryOn429:
    """Verify retry behavior when APIs return 429 Too Many Requests."""

    def test_retries_on_429_then_succeeds(self, mock_server):
        """Session should retry on 429 and eventually succeed."""
        from agentiq_labclaw.connectors._http import resilient_session

        tracker.fail_count = 2  # fail twice, then succeed
        session = resilient_session(timeout=10, backoff_factor=0.1)

        resp = session.get(f"{mock_server}/test")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        # Should have seen 2 failures + 1 success = 3 requests
        assert len(tracker.requests) == 3
        statuses = [r["status"] for r in tracker.requests]
        assert statuses == [429, 429, 200]

    def test_exhausts_retries_on_persistent_429(self, mock_server):
        """If all retries fail, session returns the last 429 response."""
        from agentiq_labclaw.connectors._http import resilient_session

        tracker.fail_count = 100  # never succeed
        session = resilient_session(timeout=10, max_retries=2, backoff_factor=0.1)

        resp = session.get(f"{mock_server}/test")
        # raise_on_status=False, so we get the response
        assert resp.status_code == 429

        # Should have the initial request + 2 retries = 3 total
        assert len(tracker.requests) == 3
        assert all(r["status"] == 429 for r in tracker.requests)


class TestRetryOnServerErrors:
    """Verify retry on 500/502/503/504."""

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_retries_on_server_error(self, mock_server, status):
        """Session retries on 5xx server errors."""
        from agentiq_labclaw.connectors._http import resilient_session

        tracker.fail_count = 1
        tracker.fail_status = status
        session = resilient_session(timeout=10, backoff_factor=0.1)

        resp = session.get(f"{mock_server}/test")
        assert resp.status_code == 200

        statuses = [r["status"] for r in tracker.requests]
        assert statuses == [status, 200]


class TestRetryAfterHeader:
    """Verify Retry-After header is respected."""

    def test_respects_retry_after(self, mock_server):
        """Session should wait at least Retry-After seconds before retrying."""
        from agentiq_labclaw.connectors._http import resilient_session

        tracker.fail_count = 1
        tracker.retry_after = 1  # 1 second
        session = resilient_session(timeout=10, backoff_factor=0.01)

        start = time.time()
        resp = session.get(f"{mock_server}/test")
        elapsed = time.time() - start

        assert resp.status_code == 200
        # Should have waited at least ~1 second (Retry-After)
        assert elapsed >= 0.9, f"Expected ≥0.9s delay, got {elapsed:.2f}s"


class TestExponentialBackoff:
    """Verify exponential backoff timing."""

    def test_backoff_increases(self, mock_server):
        """Delay between retries should increase exponentially."""
        from agentiq_labclaw.connectors._http import resilient_session

        tracker.fail_count = 2  # fail twice
        session = resilient_session(timeout=10, backoff_factor=0.5)

        resp = session.get(f"{mock_server}/test")
        assert resp.status_code == 200
        assert len(tracker.requests) == 3

        # Check that second gap is longer than first
        times = [r["time"] for r in tracker.requests]
        gap1 = times[1] - times[0]
        gap2 = times[2] - times[1]
        # backoff_factor=0.5 → delays of 0.5s, 1.0s (with jitter)
        # Second gap should be noticeably larger
        assert gap2 > gap1 * 1.2, f"Expected increasing gaps: {gap1:.3f}s then {gap2:.3f}s"


class TestConcurrentRequests:
    """Verify connectors handle concurrent requests without cascading failures."""

    def test_concurrent_successful_requests(self, mock_server):
        """Multiple threads making requests simultaneously should all succeed."""
        from agentiq_labclaw.connectors._http import resilient_session

        session = resilient_session(timeout=10)
        results = []

        def make_request(i):
            resp = session.get(f"{mock_server}/concurrent/{i}")
            return resp.status_code

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(make_request, i) for i in range(20)]
            results = [f.result() for f in as_completed(futures)]

        assert all(s == 200 for s in results)
        assert len(tracker.requests) == 20

    def test_concurrent_with_retries(self, mock_server):
        """Concurrent requests with some 429s should all eventually succeed."""
        from agentiq_labclaw.connectors._http import resilient_session

        tracker.fail_count = 5  # first 5 requests get 429
        session = resilient_session(timeout=10, backoff_factor=0.1)
        results = []

        def make_request(i):
            resp = session.get(f"{mock_server}/concurrent/{i}")
            return resp.status_code

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(make_request, i) for i in range(10)]
            results = [f.result() for f in as_completed(futures)]

        # All requests should eventually succeed
        assert all(s == 200 for s in results)
        # Total requests should be > 10 (some had retries)
        assert len(tracker.requests) > 10


class TestConnectorIntegration:
    """Test actual connector classes against the mock server."""

    def test_chembl_connector_retries(self, mock_server):
        """ChEMBL connector should retry on 429."""
        from agentiq_labclaw.connectors.chembl import ChEMBLConnector

        tracker.fail_count = 1
        tracker.response_body = json.dumps({"molecules": []})

        connector = ChEMBLConnector(timeout=10)
        # Point the connector at our mock server
        connector._session = __import__(
            "agentiq_labclaw.connectors._http", fromlist=["resilient_session"]
        ).resilient_session(timeout=10, backoff_factor=0.1)
        connector.BASE_URL = mock_server

        result = connector.search_compound("CCO", similarity=70)
        assert result == []

        statuses = [r["status"] for r in tracker.requests]
        assert statuses == [429, 200]

    def test_clinvar_connector_retries(self, mock_server):
        """ClinVar connector should retry on 429."""
        from agentiq_labclaw.connectors.clinvar import ClinVarConnector

        tracker.fail_count = 1
        tracker.response_body = json.dumps({
            "esearchresult": {"idlist": ["12345"]},
        })

        connector = ClinVarConnector(timeout=10)
        connector._session = __import__(
            "agentiq_labclaw.connectors._http", fromlist=["resilient_session"]
        ).resilient_session(timeout=10, backoff_factor=0.1)
        connector.EUTILS_BASE = mock_server

        # Will make 2 API calls (esearch + esummary), first esearch gets 429
        result = connector.lookup_variant("rs123")
        # The search succeeds on retry, then esummary follows
        assert len(tracker.requests) >= 2

    def test_tcga_connector_retries(self, mock_server):
        """TCGA connector should retry on 429."""
        from agentiq_labclaw.connectors.tcga import TCGAConnector

        tracker.fail_count = 1
        tracker.response_body = json.dumps({
            "data": {"hits": [], "pagination": {"count": 0}},
        })

        connector = TCGAConnector(timeout=10)
        connector._session = __import__(
            "agentiq_labclaw.connectors._http", fromlist=["resilient_session"]
        ).resilient_session(timeout=10, backoff_factor=0.1)
        connector.GDC_BASE = mock_server

        result = connector.query_cases("TCGA-BRCA", size=5)
        assert isinstance(result, list)

        statuses = [r["status"] for r in tracker.requests]
        assert statuses == [429, 200]
