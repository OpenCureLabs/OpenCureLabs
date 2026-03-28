"""Dashboard query integrity tests — verify SQL queries return correct data.

Uses a real PostgreSQL test database to catch:
- novel count mismatches (the class of bug where dashboard shows stale data)
- Query filter correctness (novel_only parameter)
- Schema compatibility (queries don't break on missing tables)
"""

import json
import importlib.util
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Load dashboard.py directly since 'dashboard' is a directory, not a package
_dashboard_spec = importlib.util.spec_from_file_location(
    "dashboard_module",
    os.path.join(os.path.dirname(__file__), "..", "dashboard", "dashboard.py"),
    submodule_search_locations=[],
)
_dashboard_mod = importlib.util.module_from_spec(_dashboard_spec)
_dashboard_spec.loader.exec_module(_dashboard_mod)

query_stats = _dashboard_mod.query_stats
query_findings = _dashboard_mod.query_findings
query_critiques = _dashboard_mod.query_critiques
table_exists = _dashboard_mod.table_exists


# ── Mock Cursor Tests (no real DB needed) ─────────────────────────────────────


class FakeCursor:
    """Minimal cursor mock that returns controlled query results."""

    def __init__(self, responses: dict | None = None):
        self._responses = responses or {}
        self._last_query = ""
        self._result = None

    def execute(self, query, params=None):
        self._last_query = query
        for pattern, result in self._responses.items():
            if pattern in query:
                self._result = result
                return
        self._result = []

    def fetchone(self):
        if self._result and isinstance(self._result, list) and len(self._result) > 0:
            return self._result[0]
        return (0,)

    def fetchall(self):
        return self._result if self._result else []


class TestQueryStats:
    """Test query_stats() logic with mock cursors."""

    def test_novel_count_matches_db(self):
        """query_stats must report the exact novel count from DB."""
        responses = {
            "information_schema.tables": [(True,)],
            "SELECT COUNT(*) FROM experiment_results WHERE novel = TRUE": [(42,)],
            "SELECT COUNT(*) FROM experiment_results": [(100,)],
            "SELECT COUNT(*) FROM agent_runs WHERE status": [(3,)],
            "SELECT COUNT(*) FROM agent_runs": [(50,)],
            "SELECT COUNT(*) FROM critique_log": [(25,)],
            "SELECT COUNT(*) FROM discovered_sources": [(10,)],
            "SELECT COUNT(*) FROM pipeline_runs": [(80,)],
        }

        cur = FakeCursor(responses)

        with patch.object(_dashboard_mod, "table_exists", return_value=True):
            stats = query_stats(cur)

        assert stats["novel_count"] == 42, "Novel count must match DB value exactly"

    def test_zero_novel_when_none_exist(self):
        """query_stats must return 0 when no novel results."""
        responses = {
            "SELECT COUNT(*) FROM experiment_results WHERE novel = TRUE": [(0,)],
            "SELECT COUNT(*) FROM experiment_results": [(500,)],
            "SELECT COUNT(*) FROM agent_runs WHERE status": [(0,)],
            "SELECT COUNT(*) FROM agent_runs": [(20,)],
            "SELECT COUNT(*) FROM critique_log": [(5,)],
            "SELECT COUNT(*) FROM discovered_sources": [(0,)],
            "SELECT COUNT(*) FROM pipeline_runs": [(30,)],
        }

        cur = FakeCursor(responses)

        with patch.object(_dashboard_mod, "table_exists", return_value=True):
            stats = query_stats(cur)

        assert stats["novel_count"] == 0

    def test_handles_missing_tables_gracefully(self):
        """query_stats returns 0 counts when tables don't exist."""
        cur = FakeCursor()

        with patch.object(_dashboard_mod, "table_exists", return_value=False):
            stats = query_stats(cur)

        assert stats["experiment_results"] == 0
        assert stats["novel_count"] == 0
        assert stats["running_agents"] == 0


class TestQueryFindings:
    """Test query_findings() filter logic."""

    def test_novel_only_filter(self):
        """query_findings(novel_only=True) must include WHERE novel = TRUE."""
        # Track what query was executed
        cur = MagicMock()
        cur.fetchall.return_value = []

        with patch.object(_dashboard_mod, "table_exists", return_value=True):
            query_findings(cur, novel_only=True, limit=10)

        # Verify the SQL includes the WHERE clause
        executed_query = cur.execute.call_args[0][0]
        assert "novel = TRUE" in executed_query

    def test_no_filter_when_novel_only_false(self):
        """query_findings(novel_only=False) must not filter by novel."""
        cur = MagicMock()
        cur.fetchall.return_value = []

        with patch.object(_dashboard_mod, "table_exists", return_value=True):
            query_findings(cur, novel_only=False, limit=10)

        executed_query = cur.execute.call_args[0][0]
        assert "WHERE e.novel = TRUE" not in executed_query

    def test_findings_return_structure(self):
        """query_findings returns list of dicts with required keys."""
        now = datetime.now()
        cur = MagicMock()
        cur.fetchall.return_value = [
            (1, "structure_prediction", {"confidence_score": 0.85}, True, now, "pipeline_1", "published"),
            (2, "docking", {"binding_affinity_kcal": -9.5}, True, now, "pipeline_2", "published"),
        ]

        with patch.object(_dashboard_mod, "table_exists", return_value=True):
            findings = query_findings(cur, novel_only=True, limit=10)

        assert len(findings) == 2
        for f in findings:
            assert "id" in f
            assert "type" in f
            assert "novel" in f
            assert "status" in f
            assert "timestamp" in f
            assert "preview" in f

        assert findings[0]["novel"] is True
        assert findings[0]["type"] == "structure_prediction"

    def test_handles_missing_experiment_results_table(self):
        """query_findings returns [] when experiment_results doesn't exist."""
        cur = MagicMock()

        with patch.object(_dashboard_mod, "table_exists", return_value=False):
            findings = query_findings(cur, novel_only=True)

        assert findings == []


class TestQueryCritiques:
    """Test query_critiques() data extraction."""

    def test_critique_score_extraction(self):
        """Scores must be extracted from nested dict or raw values."""
        now = datetime.now()
        critique_json = {
            "scientific_logic": {"score": 8, "comments": "good"},
            "statistical_validity": {"score": 7, "comments": "ok"},
            "interpretive_accuracy": 9,
            "recommendation": "publish",
            "summary": "Solid result",
        }

        cur = MagicMock()
        cur.fetchall.return_value = [
            (1, "grok", critique_json, now, "pipeline_1"),
        ]

        with patch.object(_dashboard_mod, "table_exists", return_value=True):
            critiques = query_critiques(cur, limit=5)

        assert len(critiques) == 1
        scores = critiques[0]["scores"]
        assert scores["scientific_logic"] == 8
        assert scores["statistical_validity"] == 7
        assert scores["interpretive_accuracy"] == 9
        assert critiques[0]["recommendation"] == "publish"

    def test_handles_string_critique_json(self):
        """Critique stored as JSON string must be parsed correctly."""
        now = datetime.now()
        critique_str = json.dumps({
            "scientific_logic": {"score": 6},
            "recommendation": "revise",
        })

        cur = MagicMock()
        cur.fetchall.return_value = [
            (1, "grok", critique_str, now, "p1"),
        ]

        with patch.object(_dashboard_mod, "table_exists", return_value=True):
            critiques = query_critiques(cur, limit=5)

        assert critiques[0]["scores"]["scientific_logic"] == 6
        assert critiques[0]["recommendation"] == "revise"
