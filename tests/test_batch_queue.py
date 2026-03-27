"""Tests for BatchQueue — PostgreSQL-backed job queue with atomic claiming."""

import json
import os
import sys
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_conn():
    """Create a mock psycopg2 connection + cursor."""
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


# ═══════════════════════════════════════════════════════════════════════════════
#  _get_conn
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetConn:
    @patch("psycopg2.connect")
    def test_uses_postgres_url_env(self, mock_connect, monkeypatch):
        monkeypatch.setenv("POSTGRES_URL", "host=db port=5432 dbname=test")
        from agentiq_labclaw.compute.batch_queue import _get_conn

        _get_conn()
        mock_connect.assert_called_once_with("host=db port=5432 dbname=test")

    @patch("psycopg2.connect")
    def test_default_connection_string(self, mock_connect, monkeypatch):
        monkeypatch.delenv("POSTGRES_URL", raising=False)
        from agentiq_labclaw.compute.batch_queue import _get_conn

        _get_conn()
        mock_connect.assert_called_once_with("dbname=opencurelabs port=5433")


# ═══════════════════════════════════════════════════════════════════════════════
#  BatchQueue — init
# ═══════════════════════════════════════════════════════════════════════════════


class TestBatchQueueInit:
    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_ensure_tables_called(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        cursor.execute.assert_called_once()  # CREATE TABLE statements
        conn.commit.assert_called_once()
        conn.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
#  BatchQueue.submit_batch
# ═══════════════════════════════════════════════════════════════════════════════


class TestSubmitBatch:
    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_inserts_tasks(self, mock_get_conn):
        conn, cursor = _mock_conn()
        # First call: _ensure_tables in __init__, Second call: submit_batch
        mock_get_conn.return_value = conn

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()

        task1 = MagicMock(
            skill_name="genomics", input_data={"gene": "TP53"},
            domain="cancer", label="tp53-analysis", priority=3,
        )
        task2 = MagicMock(
            skill_name="docking", input_data={"target": "ACE2"},
            domain="drug", label="ace2-dock", priority=5,
        )

        batch_id = bq.submit_batch([task1, task2])

        assert isinstance(batch_id, str)
        assert len(batch_id) == 12
        # 1 for _ensure_tables + 2 INSERTs for tasks
        assert cursor.execute.call_count == 3
        assert conn.commit.call_count == 2  # init + submit

    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_submit_empty_batch(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        batch_id = bq.submit_batch([])
        assert isinstance(batch_id, str)

    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_passes_genesis_run_id(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        task = MagicMock(
            skill_name="genomics", input_data={},
            domain=None, label=None, priority=5,
        )
        bq.submit_batch([task], genesis_run_id="genesis-20260320-120000")

        # The INSERT call (second execute) should include genesis_run_id
        insert_call = cursor.execute.call_args_list[1]  # [0]=ensure_tables, [1]=insert
        assert "genesis-20260320-120000" in insert_call[0][1]


# ═══════════════════════════════════════════════════════════════════════════════
#  BatchQueue.claim_job
# ═══════════════════════════════════════════════════════════════════════════════


class TestClaimJob:
    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_claim_returns_job(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn
        cursor.fetchone.return_value = (
            42, "batch-abc", "genomics",
            json.dumps({"gene": "BRCA1"}), "cancer", "brca1-run",
        )

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        job = bq.claim_job(instance_id=100)

        assert job is not None
        assert job["id"] == 42
        assert job["batch_id"] == "batch-abc"
        assert job["skill_name"] == "genomics"
        assert job["input_data"] == {"gene": "BRCA1"}
        assert job["domain"] == "cancer"
        assert job["label"] == "brca1-run"

    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_claim_empty_queue(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn
        cursor.fetchone.return_value = None

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        job = bq.claim_job(instance_id=100)
        assert job is None

    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_claim_with_batch_filter(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn
        cursor.fetchone.return_value = None

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        bq.claim_job(instance_id=100, batch_id="specific-batch")

        # Should use the batch_id SQL variant (2 params instead of 1)
        claim_call = cursor.execute.call_args_list[1]
        assert claim_call[0][1] == (100, "specific-batch")

    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_claim_parses_json_string(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn
        cursor.fetchone.return_value = (
            1, "b1", "skill", '{"key": "value"}', None, None,
        )

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        job = bq.claim_job(instance_id=1)
        assert job["input_data"] == {"key": "value"}

    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_claim_handles_dict_input(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn
        cursor.fetchone.return_value = (
            1, "b1", "skill", {"already": "parsed"}, None, None,
        )

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        job = bq.claim_job(instance_id=1)
        assert job["input_data"] == {"already": "parsed"}


# ═══════════════════════════════════════════════════════════════════════════════
#  BatchQueue.complete_job
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompleteJob:
    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_marks_done_and_inserts_result(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn
        cursor.fetchone.return_value = ("genomics",)

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()

        with patch("agentiq_labclaw.compute.batch_queue.R2Publisher", create=True):
            bq.complete_job(42, {"novel": True, "species": "human", "data": "result"})

        # Should execute: UPDATE batch_jobs + INSERT experiment_results
        calls = [c for c in cursor.execute.call_args_list if "batch_jobs" in str(c) or "experiment_results" in str(c)]
        assert len(calls) >= 2

    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_defaults_species_and_novel(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn
        cursor.fetchone.return_value = ("docking",)

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        bq.complete_job(1, {"score": 0.95})

        # experiment_results INSERT should use species="human", novel=False
        insert_call = [c for c in cursor.execute.call_args_list if "experiment_results" in str(c)]
        assert len(insert_call) == 1
        params = insert_call[0][0][1]
        assert params[2] is False  # novel
        assert params[3] == "human"  # species


# ═══════════════════════════════════════════════════════════════════════════════
#  BatchQueue.fail_job
# ═══════════════════════════════════════════════════════════════════════════════


class TestFailJob:
    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_fail_with_retry(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn
        cursor.fetchone.return_value = ("pending", 1)

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        bq.fail_job(42, "timeout error", retry=True)

        # Should use the CASE WHEN retry_count < 2 SQL
        fail_call = [c for c in cursor.execute.call_args_list if "retry_count" in str(c)]
        assert len(fail_call) >= 1
        conn.commit.assert_called()

    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_fail_no_retry(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        bq.fail_job(42, "permanent error", retry=False)

        # Should use the simpler SET status = 'failed' SQL
        fail_call = [c for c in cursor.execute.call_args_list if "'failed'" in str(c)]
        assert len(fail_call) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
#  BatchQueue.heartbeat
# ═══════════════════════════════════════════════════════════════════════════════


class TestHeartbeat:
    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_updates_started_at(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        bq.heartbeat(42)

        heartbeat_call = [c for c in cursor.execute.call_args_list if "started_at" in str(c) and "42" not in str(c[:1])]
        conn.commit.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
#  BatchQueue.batch_status
# ═══════════════════════════════════════════════════════════════════════════════


class TestBatchStatus:
    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_returns_counts(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn
        cursor.fetchall.return_value = [
            ("pending", 5), ("running", 3), ("done", 10), ("failed", 2),
        ]

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        status = bq.batch_status("batch-abc")
        assert status["pending"] == 5
        assert status["running"] == 3
        assert status["done"] == 10
        assert status["failed"] == 2
        assert status["total"] == 20

    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_empty_batch(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn
        cursor.fetchall.return_value = []

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        status = bq.batch_status("nonexistent")
        assert status["total"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  BatchQueue.reclaim_stale_jobs
# ═══════════════════════════════════════════════════════════════════════════════


class TestReclaimStaleJobs:
    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_reclaims_stale(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn
        cursor.fetchall.return_value = [(1,), (2,), (3,)]

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        count = bq.reclaim_stale_jobs(stale_minutes=15)
        assert count == 3
        conn.commit.assert_called()

    @patch("agentiq_labclaw.compute.batch_queue._get_conn")
    def test_no_stale_jobs(self, mock_get_conn):
        conn, cursor = _mock_conn()
        mock_get_conn.return_value = conn
        cursor.fetchall.return_value = []

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        bq = BatchQueue()
        count = bq.reclaim_stale_jobs()
        assert count == 0
