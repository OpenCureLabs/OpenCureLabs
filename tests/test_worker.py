"""Tests for Worker — Vast.ai job execution loop."""

import json
import os
import sys
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

from agentiq_labclaw.compute.worker import Worker


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker init
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkerInit:
    def test_defaults(self):
        w = Worker(instance_id=1, ssh_host="1.2.3.4")
        assert w.instance_id == 1
        assert w.ssh_host == "1.2.3.4"
        assert w.ssh_port == 22
        assert w.idle_timeout == 0
        assert w.jobs_completed == 0
        assert w.jobs_failed == 0
        assert not w._stop.is_set()

    def test_custom_params(self):
        queue = MagicMock()
        pool = MagicMock()
        w = Worker(
            instance_id=42, ssh_host="10.0.0.1", ssh_port=12345,
            queue=queue, pool_manager=pool, batch_id="b1", idle_timeout=30,
        )
        assert w.ssh_port == 12345
        assert w._queue is queue
        assert w._pool is pool
        assert w.batch_id == "b1"
        assert w.idle_timeout == 30


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker.stop
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkerStop:
    def test_sets_stop_event(self):
        w = Worker(instance_id=1, ssh_host="1.2.3.4")
        assert not w._stop.is_set()
        w.stop()
        assert w._stop.is_set()


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker.run — empty queue
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkerRunEmpty:
    def test_stops_on_empty_queue(self):
        queue = MagicMock()
        queue.claim_job.return_value = None

        w = Worker(instance_id=1, ssh_host="1.2.3.4", queue=queue)
        w.run()

        assert w.jobs_completed == 0
        assert w.jobs_failed == 0
        queue.claim_job.assert_called_once_with(1, batch_id=None)

    def test_stops_on_empty_queue_with_batch_id(self):
        queue = MagicMock()
        queue.claim_job.return_value = None

        w = Worker(instance_id=1, ssh_host="1.2.3.4", queue=queue, batch_id="b1")
        w.run()

        queue.claim_job.assert_called_once_with(1, batch_id="b1")


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker.run — single job success
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkerRunSuccess:
    @patch("agentiq_labclaw.compute.worker.subprocess.run")
    def test_completes_one_job(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=json.dumps({"result": "ok"}), returncode=0,
        )

        queue = MagicMock()
        queue.claim_job.side_effect = [
            {"id": 10, "skill_name": "genomics", "input_data": {"gene": "TP53"}, "label": "tp53"},
            None,  # queue empty after first job
        ]

        w = Worker(instance_id=1, ssh_host="1.2.3.4", queue=queue)
        w.run()

        assert w.jobs_completed == 1
        assert w.jobs_failed == 0
        queue.complete_job.assert_called_once_with(10, {"result": "ok"})

    @patch("agentiq_labclaw.compute.worker.subprocess.run")
    def test_marks_pool_busy_and_ready(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=json.dumps({"done": True}), returncode=0,
        )

        queue = MagicMock()
        queue.claim_job.side_effect = [
            {"id": 1, "skill_name": "docking", "input_data": {}, "label": "dock"},
            None,
        ]
        pool = MagicMock()

        w = Worker(instance_id=5, ssh_host="1.2.3.4", queue=queue, pool_manager=pool)
        w.run()

        pool.mark_busy.assert_called_once_with(5)
        pool.mark_ready.assert_called_once_with(5)


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker.run — job failure
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkerRunFailure:
    @patch("agentiq_labclaw.compute.worker.subprocess.run")
    def test_fails_job_on_exception(self, mock_run):
        mock_run.side_effect = Exception("SSH connection refused")

        queue = MagicMock()
        queue.claim_job.side_effect = [
            {"id": 20, "skill_name": "qsar", "input_data": {}, "label": "qsar-run"},
            None,
        ]

        w = Worker(instance_id=1, ssh_host="1.2.3.4", queue=queue)
        w.run()

        assert w.jobs_completed == 0
        assert w.jobs_failed == 1
        queue.fail_job.assert_called_once()
        args = queue.fail_job.call_args[0]
        assert args[0] == 20
        assert "SSH connection refused" in args[1]

    @patch("agentiq_labclaw.compute.worker.subprocess.run")
    def test_error_message_truncated(self, mock_run):
        mock_run.side_effect = Exception("x" * 5000)

        queue = MagicMock()
        queue.claim_job.side_effect = [
            {"id": 30, "skill_name": "docking", "input_data": {}, "label": "dock"},
            None,
        ]

        w = Worker(instance_id=1, ssh_host="1.2.3.4", queue=queue)
        w.run()

        error_msg = queue.fail_job.call_args[0][1]
        assert len(error_msg) <= 2000


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker.run — multiple jobs
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkerRunMultiple:
    @patch("agentiq_labclaw.compute.worker.subprocess.run")
    def test_processes_multiple_jobs(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=json.dumps({"ok": True}), returncode=0,
        )

        queue = MagicMock()
        queue.claim_job.side_effect = [
            {"id": 1, "skill_name": "s1", "input_data": {}, "label": "j1"},
            {"id": 2, "skill_name": "s2", "input_data": {}, "label": "j2"},
            {"id": 3, "skill_name": "s3", "input_data": {}, "label": "j3"},
            None,
        ]

        w = Worker(instance_id=1, ssh_host="1.2.3.4", queue=queue)
        w.run()

        assert w.jobs_completed == 3
        assert queue.complete_job.call_count == 3

    @patch("agentiq_labclaw.compute.worker.subprocess.run")
    def test_stop_event_interrupts(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=json.dumps({"ok": True}), returncode=0,
        )

        queue = MagicMock()
        # Return jobs forever, but we'll stop after the first
        queue.claim_job.return_value = {"id": 1, "skill_name": "s", "input_data": {}, "label": "l"}

        w = Worker(instance_id=1, ssh_host="1.2.3.4", queue=queue)

        # Pre-set the stop event — worker should exit after check
        w.stop()
        w.run()

        assert w.jobs_completed == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker.run — idle timeout
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkerIdleTimeout:
    @patch("time.sleep")
    def test_idle_timeout_waits_then_stops(self, mock_sleep):
        queue = MagicMock()
        queue.claim_job.return_value = None  # always empty

        w = Worker(instance_id=1, ssh_host="1.2.3.4", queue=queue, idle_timeout=10)
        w.run()

        # Should have polled multiple times during idle wait
        assert queue.claim_job.call_count > 1
        assert w.jobs_completed == 0

    @patch("agentiq_labclaw.compute.worker.subprocess.run")
    @patch("time.sleep")
    def test_idle_timeout_resumes_on_new_job(self, mock_sleep, mock_subproc):
        mock_subproc.return_value = MagicMock(
            stdout=json.dumps({"ok": True}), returncode=0,
        )

        call_count = [0]

        def claim_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return None  # first call: empty
            if call_count[0] == 2:
                return None  # second call during idle: still empty
            if call_count[0] == 3:
                return {"id": 1, "skill_name": "s", "input_data": {}, "label": "l"}
            return None  # after job, empty again → idle → timeout

        queue = MagicMock()
        queue.claim_job.side_effect = claim_side_effect

        w = Worker(instance_id=1, ssh_host="1.2.3.4", queue=queue, idle_timeout=10)
        w.run()

        assert w.jobs_completed == 1


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker._execute_remote
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteRemote:
    @patch("agentiq_labclaw.compute.worker.subprocess.run")
    def test_ssh_command_structure(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=json.dumps({"result": "data"}), returncode=0,
        )

        w = Worker(instance_id=1, ssh_host="10.0.0.1", ssh_port=9999)
        result = w._execute_remote("genomics", {"gene": "BRCA1"})

        assert result == {"result": "data"}
        args = mock_run.call_args[0][0]
        assert "ssh" in args[0]
        assert "9999" in args
        assert "root@10.0.0.1" in args

    @patch("agentiq_labclaw.compute.worker.subprocess.run")
    def test_nonzero_exit_raises(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="", stderr="skill not found", returncode=1,
        )

        w = Worker(instance_id=1, ssh_host="1.2.3.4")
        with pytest.raises(RuntimeError, match="exit 1"):
            w._execute_remote("bad_skill", {})

    @patch("agentiq_labclaw.compute.worker.subprocess.run")
    def test_invalid_json_output_raises(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="not json at all", returncode=0,
        )

        w = Worker(instance_id=1, ssh_host="1.2.3.4")
        with pytest.raises((json.JSONDecodeError, RuntimeError)):
            w._execute_remote("skill", {})


# ═══════════════════════════════════════════════════════════════════════════════
#  Worker._touch_heartbeat
# ═══════════════════════════════════════════════════════════════════════════════


class TestTouchHeartbeat:
    @patch("agentiq_labclaw.compute.worker.subprocess.run")
    def test_ssh_touch_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        w = Worker(instance_id=1, ssh_host="1.2.3.4", ssh_port=22)
        w._touch_heartbeat()

        args = mock_run.call_args[0][0]
        assert "touch /tmp/labclaw_heartbeat" in " ".join(args)

    @patch("agentiq_labclaw.compute.worker.subprocess.run")
    def test_heartbeat_swallows_errors(self, mock_run):
        mock_run.side_effect = Exception("network down")

        w = Worker(instance_id=1, ssh_host="1.2.3.4")
        # Should not raise
        w._touch_heartbeat()
