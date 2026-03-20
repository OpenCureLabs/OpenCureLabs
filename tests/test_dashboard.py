"""Tests for the OpenCure Labs dashboard — FastAPI routes and helpers."""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# Add dashboard to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dashboard"))

# Mock psycopg2 before importing dashboard to avoid needing a real DB
mock_psycopg2 = MagicMock()
mock_psycopg2_pool = MagicMock()
sys.modules["psycopg2"] = mock_psycopg2
sys.modules["psycopg2.pool"] = mock_psycopg2_pool


# ── Import after mocking ─────────────────────────────────────────────────────

from fastapi.testclient import TestClient


def _make_client():
    """Create a test client with mocked DB connections."""
    # Re-import to get fresh module with mocked psycopg2
    import importlib
    if "dashboard" in sys.modules:
        del sys.modules["dashboard"]

    import dashboard as dash

    # Mock get_conn to return a mock connection
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    # table_exists returns True for all tables
    mock_cursor.fetchone.return_value = (True,)
    # Default: return 0 for counts
    mock_cursor.fetchall.return_value = []

    dash.get_conn = lambda: mock_conn
    return TestClient(dash.app), dash, mock_cursor


# ═══════════════════════════════════════════════════════════════════════════
#  Health endpoint
# ═══════════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    """Test /health endpoint."""

    def test_health_ok(self):
        client, dash, _ = _make_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    def test_health_db_down(self):
        client, dash, _ = _make_client()
        dash.get_conn = MagicMock(side_effect=Exception("connection refused"))
        resp = client.get("/health")
        assert resp.status_code == 503
        assert resp.json()["status"] == "unhealthy"


# ═══════════════════════════════════════════════════════════════════════════
#  API endpoints
# ═══════════════════════════════════════════════════════════════════════════

class TestAPIEndpoints:
    """Test /api/* endpoints."""

    def test_api_stats(self):
        client, dash, mock_cursor = _make_client()
        # query_stats does multiple fetchone calls, all return counts
        mock_cursor.fetchone.return_value = (0,)
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_api_findings(self):
        client, dash, mock_cursor = _make_client()
        mock_cursor.fetchall.return_value = []
        resp = client.get("/api/findings")
        assert resp.status_code == 200

    def test_api_findings_with_novel_filter(self):
        client, dash, mock_cursor = _make_client()
        mock_cursor.fetchall.return_value = []
        resp = client.get("/api/findings?novel_only=true")
        assert resp.status_code == 200

    def test_api_runs(self):
        client, dash, mock_cursor = _make_client()
        mock_cursor.fetchall.return_value = []
        resp = client.get("/api/runs")
        assert resp.status_code == 200

    def test_api_critiques(self):
        client, dash, mock_cursor = _make_client()
        mock_cursor.fetchall.return_value = []
        resp = client.get("/api/critiques")
        assert resp.status_code == 200

    def test_api_sources(self):
        client, dash, mock_cursor = _make_client()
        mock_cursor.fetchall.return_value = []
        resp = client.get("/api/sources")
        assert resp.status_code == 200

    def test_api_limit_capped_at_200(self):
        client, dash, mock_cursor = _make_client()
        mock_cursor.fetchall.return_value = []
        resp = client.get("/api/runs?limit=500")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
#  Dashboard HTML
# ═══════════════════════════════════════════════════════════════════════════

class TestDashboardHTML:
    """Test the main dashboard page."""

    def test_dashboard_returns_html(self):
        client, dash, mock_cursor = _make_client()
        mock_cursor.fetchone.return_value = (0,)
        mock_cursor.fetchall.return_value = []
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "OpenCure" in resp.text


# ═══════════════════════════════════════════════════════════════════════════
#  CORS
# ═══════════════════════════════════════════════════════════════════════════

class TestCORS:
    """Test CORS middleware."""

    def test_cors_headers_present(self):
        client, _, mock_cursor = _make_client()
        mock_cursor.fetchone.return_value = (0,)
        resp = client.get("/api/stats", headers={"Origin": "https://example.com"})
        assert "access-control-allow-origin" in resp.headers


# ═══════════════════════════════════════════════════════════════════════════
#  Logo
# ═══════════════════════════════════════════════════════════════════════════

class TestLogo:
    """Test logo endpoint."""

    def test_logo_404_when_missing(self):
        client, _, _ = _make_client()
        with patch("os.path.exists", return_value=False):
            resp = client.get("/logo-v2.png")
            assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
#  query helpers (unit tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestQueryHelpers:
    """Test dashboard query functions in isolation."""

    def test_table_exists_true(self):
        _, dash, mock_cursor = _make_client()
        mock_cursor.fetchone.return_value = (True,)
        assert dash.table_exists(mock_cursor, "agent_runs") is True

    def test_table_exists_false(self):
        _, dash, mock_cursor = _make_client()
        mock_cursor.fetchone.return_value = (False,)
        assert dash.table_exists(mock_cursor, "nonexistent") is False

    def test_query_stats_all_empty(self):
        _, dash, mock_cursor = _make_client()
        mock_cursor.fetchone.return_value = (0,)
        stats = dash.query_stats(mock_cursor)
        assert stats["agent_runs"] == 0
        assert stats["novel_count"] == 0
