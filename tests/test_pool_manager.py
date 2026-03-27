"""Tests for PoolManager — Vast.ai instance fleet management."""

import os
import sys
from unittest.mock import MagicMock, patch, call

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))


# ═══════════════════════════════════════════════════════════════════════════════
#  Module-level helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestVastHeaders:
    def test_uses_env_key(self, monkeypatch):
        monkeypatch.setenv("VAST_AI_KEY", "my-api-key")
        from agentiq_labclaw.compute.pool_manager import _vast_headers

        headers = _vast_headers()
        assert headers["Authorization"] == "Bearer my-api-key"

    def test_empty_without_key(self, monkeypatch):
        monkeypatch.delenv("VAST_AI_KEY", raising=False)
        from agentiq_labclaw.compute.pool_manager import _vast_headers

        headers = _vast_headers()
        assert headers["Authorization"] == "Bearer "


class TestFindOffers:
    @patch("agentiq_labclaw.compute.pool_manager.requests.get")
    def test_returns_offers(self, mock_get, monkeypatch):
        monkeypatch.setenv("VAST_AI_KEY", "key")
        mock_get.return_value = MagicMock(
            json=lambda: {"offers": [{"id": 1, "dph_total": 0.25}]},
        )

        from agentiq_labclaw.compute.pool_manager import _find_offers

        offers = _find_offers(gpu_required=True, max_cost_hr=0.50, count=5)
        assert len(offers) == 1
        assert offers[0]["id"] == 1
        assert mock_get.call_count >= 1

    @patch("agentiq_labclaw.compute.pool_manager.requests.get")
    def test_relaxes_reliability(self, mock_get, monkeypatch):
        monkeypatch.setenv("VAST_AI_KEY", "key")
        # First call: few offers, second call: more offers
        mock_get.return_value = MagicMock(
            json=lambda: {"offers": [{"id": 1}]},
        )

        from agentiq_labclaw.compute.pool_manager import _find_offers

        # Request 5 but only 1 returned → should retry with relaxed reliability
        offers = _find_offers(gpu_required=False, max_cost_hr=1.0, count=5)
        assert mock_get.call_count == 2  # original + relaxed

    @patch("agentiq_labclaw.compute.pool_manager.requests.get")
    def test_api_error_raises(self, mock_get, monkeypatch):
        monkeypatch.setenv("VAST_AI_KEY", "key")
        mock_get.return_value.raise_for_status.side_effect = requests.HTTPError("500")

        from agentiq_labclaw.compute.pool_manager import _find_offers

        with pytest.raises(requests.HTTPError):
            _find_offers(gpu_required=True, max_cost_hr=0.50)


# ═══════════════════════════════════════════════════════════════════════════════
#  _destroy_instance
# ═══════════════════════════════════════════════════════════════════════════════


class TestDestroyInstance:
    @patch("agentiq_labclaw.compute.pool_manager.time.sleep")
    @patch("agentiq_labclaw.compute.pool_manager.requests.delete")
    def test_destroy_success(self, mock_delete, mock_sleep, monkeypatch):
        monkeypatch.setenv("VAST_AI_KEY", "key")
        mock_delete.return_value = MagicMock()

        from agentiq_labclaw.compute.pool_manager import _destroy_instance

        result = _destroy_instance(123)
        assert result is True
        mock_delete.assert_called_once()
        assert "123" in mock_delete.call_args[0][0]

    @patch("agentiq_labclaw.compute.pool_manager.time.sleep")
    @patch("agentiq_labclaw.compute.pool_manager.requests.delete")
    def test_destroy_retries(self, mock_delete, mock_sleep, monkeypatch):
        monkeypatch.setenv("VAST_AI_KEY", "key")
        mock_delete.side_effect = requests.RequestException("network error")

        from agentiq_labclaw.compute.pool_manager import _destroy_instance

        result = _destroy_instance(42, retries=3)
        assert result is False
        assert mock_delete.call_count == 3


# ═══════════════════════════════════════════════════════════════════════════════
#  _check_setup_ready
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckSetupReady:
    @patch("agentiq_labclaw.compute.pool_manager.subprocess.run")
    def test_ready(self, mock_run):
        mock_run.return_value = MagicMock(stdout="READY\n", returncode=0)

        from agentiq_labclaw.compute.pool_manager import _check_setup_ready

        assert _check_setup_ready("1.2.3.4", 22) is True

    @patch("agentiq_labclaw.compute.pool_manager.subprocess.run")
    def test_not_ready(self, mock_run):
        mock_run.return_value = MagicMock(stdout="WAIT\n", returncode=0)

        from agentiq_labclaw.compute.pool_manager import _check_setup_ready

        assert _check_setup_ready("1.2.3.4", 22) is False

    @patch("agentiq_labclaw.compute.pool_manager.subprocess.run")
    def test_ssh_failure(self, mock_run):
        mock_run.side_effect = Exception("Connection refused")

        from agentiq_labclaw.compute.pool_manager import _check_setup_ready

        assert _check_setup_ready("1.2.3.4", 22) is False


# ═══════════════════════════════════════════════════════════════════════════════
#  _check_ssh_alive
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckSSHAlive:
    @patch("agentiq_labclaw.compute.pool_manager.time.sleep")
    @patch("agentiq_labclaw.compute.pool_manager.subprocess.run")
    def test_alive(self, mock_run, mock_sleep):
        mock_run.return_value = MagicMock(stdout="alive\n", returncode=0)

        from agentiq_labclaw.compute.pool_manager import _check_ssh_alive

        assert _check_ssh_alive("1.2.3.4", 22) is True
        mock_sleep.assert_not_called()

    @patch("agentiq_labclaw.compute.pool_manager.time.sleep")
    @patch("agentiq_labclaw.compute.pool_manager.subprocess.run")
    def test_dead_after_retries(self, mock_run, mock_sleep):
        mock_run.return_value = MagicMock(stdout="", returncode=1)

        from agentiq_labclaw.compute.pool_manager import _check_ssh_alive

        assert _check_ssh_alive("1.2.3.4", 22, retries=3) is False
        assert mock_run.call_count == 3
        assert mock_sleep.call_count == 2  # retries-1 sleeps

    @patch("agentiq_labclaw.compute.pool_manager.time.sleep")
    @patch("agentiq_labclaw.compute.pool_manager.subprocess.run")
    def test_recovers_on_retry(self, mock_run, mock_sleep):
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=1),  # fail
            MagicMock(stdout="alive\n", returncode=0),  # succeed
        ]

        from agentiq_labclaw.compute.pool_manager import _check_ssh_alive

        assert _check_ssh_alive("1.2.3.4", 22, retries=3) is True


# ═══════════════════════════════════════════════════════════════════════════════
#  PoolInstance
# ═══════════════════════════════════════════════════════════════════════════════


class TestPoolInstance:
    def test_defaults(self):
        from agentiq_labclaw.compute.pool_manager import PoolInstance

        inst = PoolInstance(instance_id=42)
        assert inst.instance_id == 42
        assert inst.ssh_host is None
        assert inst.ssh_port == 22
        assert inst.status == "provisioning"
        assert inst.jobs_done == 0
        assert inst.cost_per_hr == 0.0

    def test_custom_fields(self):
        from agentiq_labclaw.compute.pool_manager import PoolInstance

        inst = PoolInstance(
            instance_id=99, ssh_host="10.0.0.1", ssh_port=12345,
            gpu_name="RTX 4090", cost_per_hr=0.35, status="ready",
        )
        assert inst.gpu_name == "RTX 4090"
        assert inst.cost_per_hr == 0.35
        assert inst.status == "ready"


# ═══════════════════════════════════════════════════════════════════════════════
#  PoolManager init
# ═══════════════════════════════════════════════════════════════════════════════


class TestPoolManagerInit:
    @patch("agentiq_labclaw.compute.pool_manager._poll_instance")
    @patch("agentiq_labclaw.compute.pool_manager._db_get_pool")
    def test_loads_from_db(self, mock_db_get, mock_poll):
        mock_db_get.return_value = [
            {"instance_id": 1, "ssh_host": "h1", "ssh_port": 22,
             "gpu_name": "A100", "cost_per_hr": 0.50, "status": "ready", "jobs_done": 5},
        ]
        mock_poll.return_value = {"actual_status": "running"}

        from agentiq_labclaw.compute.pool_manager import PoolManager

        pool = PoolManager(target_size=5)
        assert 1 in pool.instances
        assert pool.instances[1].ssh_host == "h1"
        assert pool.active_count == 1
        assert pool.ready_count == 1

    @patch("agentiq_labclaw.compute.pool_manager._poll_instance")
    @patch("agentiq_labclaw.compute.pool_manager._db_get_pool")
    def test_empty_pool(self, mock_db_get, mock_poll):
        mock_db_get.return_value = []

        from agentiq_labclaw.compute.pool_manager import PoolManager

        pool = PoolManager(target_size=3)
        assert pool.active_count == 0
        assert pool.ready_count == 0
        assert pool.get_ready_instances() == []

    @patch("agentiq_labclaw.compute.pool_manager._db_update_status")
    @patch("agentiq_labclaw.compute.pool_manager._poll_instance")
    @patch("agentiq_labclaw.compute.pool_manager._db_get_pool")
    def test_prunes_ghost_instances(self, mock_db_get, mock_poll, mock_db_update):
        mock_db_get.return_value = [
            {"instance_id": 1, "ssh_host": "h1", "ssh_port": 22,
             "gpu_name": "A100", "cost_per_hr": 0.50, "status": "ready", "jobs_done": 0},
        ]
        # Instance is gone from Vast.ai API
        mock_poll.side_effect = requests.RequestException("not found")

        from agentiq_labclaw.compute.pool_manager import PoolManager

        pool = PoolManager(target_size=5)
        assert pool.instances[1].status == "destroyed"
        mock_db_update.assert_called_with(1, "destroyed")


# ═══════════════════════════════════════════════════════════════════════════════
#  PoolManager properties
# ═══════════════════════════════════════════════════════════════════════════════


class TestPoolManagerProperties:
    @patch("agentiq_labclaw.compute.pool_manager._db_get_pool")
    def test_active_count_excludes_destroyed(self, mock_db_get):
        mock_db_get.return_value = []

        from agentiq_labclaw.compute.pool_manager import PoolManager, PoolInstance

        pool = PoolManager.__new__(PoolManager)
        pool.instances = {
            1: PoolInstance(1, status="ready"),
            2: PoolInstance(2, status="busy"),
            3: PoolInstance(3, status="destroyed"),
            4: PoolInstance(4, status="failed"),
        }
        assert pool.active_count == 2  # ready + busy

    @patch("agentiq_labclaw.compute.pool_manager._db_get_pool")
    def test_ready_count(self, mock_db_get):
        mock_db_get.return_value = []

        from agentiq_labclaw.compute.pool_manager import PoolManager, PoolInstance

        pool = PoolManager.__new__(PoolManager)
        pool.instances = {
            1: PoolInstance(1, status="ready"),
            2: PoolInstance(2, status="ready"),
            3: PoolInstance(3, status="busy"),
        }
        assert pool.ready_count == 2
        assert len(pool.get_ready_instances()) == 2


# ═══════════════════════════════════════════════════════════════════════════════
#  DB helpers (module-level functions)
# ═══════════════════════════════════════════════════════════════════════════════


class TestDBHelpers:
    @patch("agentiq_labclaw.compute.pool_manager._get_conn")
    def test_register_instance(self, mock_get_conn):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        from agentiq_labclaw.compute.pool_manager import PoolInstance, _db_register_instance

        inst = PoolInstance(instance_id=99, ssh_host="10.0.0.1", gpu_name="RTX 4090")
        _db_register_instance(inst)

        cursor.execute.assert_called_once()
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    @patch("agentiq_labclaw.compute.pool_manager._get_conn")
    def test_update_status_ready(self, mock_get_conn):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        from agentiq_labclaw.compute.pool_manager import _db_update_status

        _db_update_status(42, "ready", ssh_host="1.2.3.4", ssh_port=22)
        sql = cursor.execute.call_args[0][0]
        assert "ready_at" in sql

    @patch("agentiq_labclaw.compute.pool_manager._get_conn")
    def test_update_status_destroyed(self, mock_get_conn):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        from agentiq_labclaw.compute.pool_manager import _db_update_status

        _db_update_status(42, "destroyed")
        sql = cursor.execute.call_args[0][0]
        assert "destroyed_at" in sql

    @patch("agentiq_labclaw.compute.pool_manager._get_conn")
    def test_increment_jobs(self, mock_get_conn):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        from agentiq_labclaw.compute.pool_manager import _db_increment_jobs

        _db_increment_jobs(42)
        sql = cursor.execute.call_args[0][0]
        assert "jobs_done" in sql
