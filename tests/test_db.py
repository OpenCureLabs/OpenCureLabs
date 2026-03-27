"""
Tests for the DB CRUD layer — agent_runs, pipeline_runs, critique_log,
experiment_results, discovered_sources.

Runs against the local PostgreSQL instance on port 5433.
Each test cleans up after itself.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

# Ensure we have a working DB connection
try:
    from agentiq_labclaw.db.connection import get_connection
    _conn = get_connection()
    DB_AVAILABLE = not _conn.closed
except Exception:
    DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="PostgreSQL not available")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _cleanup():
    """Clean up test rows after each test."""
    yield
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM experiment_results WHERE result_type LIKE 'test_%%'")
        cur.execute("DELETE FROM critique_log WHERE reviewer LIKE 'test_%%'")
        cur.execute("DELETE FROM pipeline_runs WHERE pipeline_name LIKE 'test_%%'")
        cur.execute("DELETE FROM agent_runs WHERE agent_name LIKE 'test_%%'")
        cur.execute("DELETE FROM discovered_sources WHERE discovered_by = 'test_agent'")


# ---------------------------------------------------------------------------
# agent_runs
# ---------------------------------------------------------------------------


class TestAgentRuns:
    def test_start_run(self):
        from agentiq_labclaw.db.agent_runs import start_run
        run_id = start_run("test_agent_alpha")
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_complete_run(self):
        from agentiq_labclaw.db.agent_runs import complete_run, get_run, start_run
        run_id = start_run("test_agent_beta")
        complete_run(run_id, "completed", {"output": "ok"})
        row = get_run(run_id)
        assert row is not None
        assert row["status"] == "completed"
        assert row["completed_at"] is not None

    def test_get_run_not_found(self):
        from agentiq_labclaw.db.agent_runs import get_run
        assert get_run(999999999) is None


# ---------------------------------------------------------------------------
# pipeline_runs
# ---------------------------------------------------------------------------


class TestPipelineRuns:
    def test_start_pipeline(self):
        from agentiq_labclaw.db.pipeline_runs import start_pipeline
        run_id = start_pipeline("test_pipeline_a", {"vcf": "/tmp/t.vcf"})
        assert isinstance(run_id, int)

    def test_complete_pipeline(self):
        from agentiq_labclaw.db.pipeline_runs import complete_pipeline, start_pipeline
        run_id = start_pipeline("test_pipeline_b")
        complete_pipeline(run_id, "completed", "/tmp/out.pdf")
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT status, output_path FROM pipeline_runs WHERE id = %s", (run_id,))
            row = cur.fetchone()
        assert row[0] == "completed"
        assert row[1] == "/tmp/out.pdf"


# ---------------------------------------------------------------------------
# critique_log
# ---------------------------------------------------------------------------


class TestCritiqueLog:
    def test_log_and_retrieve(self):
        from agentiq_labclaw.db.critique_log import get_critiques_for_run, log_critique
        from agentiq_labclaw.db.pipeline_runs import start_pipeline

        run_id = start_pipeline("test_pipeline_crit")
        cid = log_critique(run_id, "test_claude", {"score": 8, "comment": "good"})
        assert isinstance(cid, int)

        critiques = get_critiques_for_run(run_id)
        assert len(critiques) >= 1
        assert critiques[0]["reviewer"] == "test_claude"
        assert critiques[0]["critique_json"]["score"] == 8


# ---------------------------------------------------------------------------
# experiment_results
# ---------------------------------------------------------------------------


class TestExperimentResults:
    def test_store_result(self):
        from agentiq_labclaw.db.experiment_results import store_result
        from agentiq_labclaw.db.pipeline_runs import start_pipeline

        run_id = start_pipeline("test_pipeline_exp")
        rid = store_result(run_id, "test_neoantigen", {"gene": "TP53"}, novel=True)
        assert isinstance(rid, int)

    def test_check_novelty_new(self):
        from agentiq_labclaw.db.experiment_results import check_novelty
        # Should be novel — unique data that doesn't exist
        assert check_novelty("test_unique_type", {"key": "abc123xyz"}) is True

    def test_check_novelty_existing(self):
        from agentiq_labclaw.db.experiment_results import check_novelty, store_result
        from agentiq_labclaw.db.pipeline_runs import start_pipeline

        run_id = start_pipeline("test_pipeline_nov")
        data = {"gene": "BRCA1_test_dup"}
        store_result(run_id, "test_dup_type", data, novel=False)
        # Now it's not novel
        assert check_novelty("test_dup_type", data) is False


# ---------------------------------------------------------------------------
# discovered_sources
# ---------------------------------------------------------------------------


class TestDiscoveredSources:
    def test_register_source(self):
        from agentiq_labclaw.db.discovered_sources import register_source
        sid = register_source("https://example.com/data", "genomics", "test_agent")
        assert isinstance(sid, int)

    def test_validate_source(self):
        from agentiq_labclaw.db.discovered_sources import register_source, validate_source
        sid = register_source("https://example.com/valid", "proteomics", "test_agent")
        validate_source(sid)
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT validated FROM discovered_sources WHERE id = %s", (sid,))
            assert cur.fetchone()[0] is True

    def test_list_unvalidated(self):
        from agentiq_labclaw.db.discovered_sources import list_unvalidated, register_source
        register_source("https://example.com/unval", "chembl", "test_agent")
        unval = list_unvalidated()
        urls = [s["url"] for s in unval]
        assert "https://example.com/unval" in urls


# ---------------------------------------------------------------------------
# Index verification
# ---------------------------------------------------------------------------


class TestIndexes:
    def test_indexes_exist(self):
        """Verify that performance indexes were created."""
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename IN "
                "('agent_runs', 'pipeline_runs', 'experiment_results', "
                "'critique_log', 'discovered_sources') "
                "AND indexname LIKE 'idx_%%'"
            )
            index_names = {r[0] for r in cur.fetchall()}

        expected = {
            "idx_agent_runs_status",
            "idx_agent_runs_started_at",
            "idx_pipeline_runs_status",
            "idx_pipeline_runs_started_at",
            "idx_experiment_results_novel",
            "idx_experiment_results_pipeline_run_id",
            "idx_experiment_results_timestamp",
            "idx_critique_log_run_id",
            "idx_critique_log_timestamp",
            "idx_discovered_sources_validated",
        }
        missing = expected - index_names
        assert not missing, f"Missing indexes: {missing}"
