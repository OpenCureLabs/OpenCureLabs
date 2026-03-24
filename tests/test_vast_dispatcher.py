"""Tests for Vast.ai GPU dispatcher — VastInstance, offer search, provisioning."""

import json
import os
import sys
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

from agentiq_labclaw.compute.vast_dispatcher import (
    VastInstance,
    _find_cheapest_offer,
    _find_reusable_instance,
    _claim_pool_instance,
    _register_pool_instance,
    _release_pool_instance,
    teardown_all_instances,
    _create_instance,
    _run_remote,
    dispatch,
    VAST_API,
)


# ═══════════════════════════════════════════════════════════════════════════
#  VastInstance
# ═══════════════════════════════════════════════════════════════════════════

class TestVastInstance:
    """Test VastInstance lifecycle management."""

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_info_returns_json(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {"id": 123, "actual_status": "running"},
        )
        inst = VastInstance("test-key", 123)
        info = inst.info
        assert info["id"] == 123
        mock_get.assert_called_once()

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_info_api_error(self, mock_get):
        mock_get.return_value.raise_for_status.side_effect = requests.HTTPError("404")
        inst = VastInstance("test-key", 999)
        with pytest.raises(requests.HTTPError):
            _ = inst.info

    @patch("agentiq_labclaw.compute.vast_dispatcher.time.sleep")
    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_wait_until_ready_immediate(self, mock_get, mock_sleep):
        mock_get.return_value = MagicMock(
            json=lambda: {"id": 1, "actual_status": "running"},
        )
        inst = VastInstance("key", 1)
        info = inst.wait_until_ready(timeout=30)
        assert info["actual_status"] == "running"
        mock_sleep.assert_not_called()

    @patch("agentiq_labclaw.compute.vast_dispatcher.time.sleep")
    @patch("agentiq_labclaw.compute.vast_dispatcher.time.monotonic")
    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_wait_until_ready_timeout(self, mock_get, mock_mono, mock_sleep):
        mock_get.return_value = MagicMock(
            json=lambda: {"id": 1, "actual_status": "loading"},
        )
        # Simulate time passing beyond timeout
        mock_mono.side_effect = [0, 0, 301]
        inst = VastInstance("key", 1)
        with pytest.raises(TimeoutError, match="did not start"):
            inst.wait_until_ready(timeout=300)

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.delete")
    def test_destroy_success(self, mock_delete):
        inst = VastInstance("key", 42)
        inst.destroy()
        mock_delete.assert_called_once()
        assert "42" in mock_delete.call_args[0][0]

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.delete")
    def test_destroy_handles_error(self, mock_delete):
        mock_delete.side_effect = requests.RequestException("network error")
        inst = VastInstance("key", 42)
        # Should not raise — error is logged
        inst.destroy()


# ═══════════════════════════════════════════════════════════════════════════
#  _find_cheapest_offer
# ═══════════════════════════════════════════════════════════════════════════

class TestFindCheapestOffer:
    """Test the offer search function."""

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_returns_cheapest(self, mock_get):
        offers = [
            {"id": 1, "gpu_name": "RTX 4090", "dph_total": 0.5},
            {"id": 2, "gpu_name": "A100", "dph_total": 1.2},
        ]
        mock_get.return_value = MagicMock(json=lambda: {"offers": offers})
        result = _find_cheapest_offer("key", gpu_required=True)
        assert result["id"] == 1

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_no_offers_raises(self, mock_get):
        mock_get.return_value = MagicMock(json=lambda: {"offers": []})
        with pytest.raises(RuntimeError, match="No suitable"):
            _find_cheapest_offer("key", gpu_required=True)

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_gpu_required_adds_query_params(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {"offers": [{"id": 1, "dph_total": 0.3}]},
        )
        _find_cheapest_offer("key", gpu_required=True)
        call_params = mock_get.call_args[1]["params"]
        query = json.loads(call_params["q"])
        assert "gpu_ram" in query


# ═══════════════════════════════════════════════════════════════════════════
#  _create_instance
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateInstance:
    """Test instance creation."""

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.put")
    def test_success(self, mock_put):
        mock_put.return_value = MagicMock(json=lambda: {"new_contract": 456})
        iid = _create_instance("key", offer_id=10)
        assert iid == 456

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.put")
    def test_no_contract_raises(self, mock_put):
        mock_put.return_value = MagicMock(json=lambda: {"error": "bad"})
        with pytest.raises(RuntimeError, match="Failed to create"):
            _create_instance("key", offer_id=10)


# ═══════════════════════════════════════════════════════════════════════════
#  dispatch
# ═══════════════════════════════════════════════════════════════════════════

class TestDispatch:
    """Test the full dispatch function."""

    def test_no_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("VAST_AI_KEY", raising=False)
        skill = MagicMock(name="test_skill", gpu_required=True)
        with pytest.raises(RuntimeError, match="VAST_AI_KEY"):
            dispatch(skill, MagicMock())


# ═══════════════════════════════════════════════════════════════════════════
#  _find_reusable_instance
# ═══════════════════════════════════════════════════════════════════════════

class TestFindReusableInstance:
    """Test instance reuse discovery."""

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_finds_running_opencurelabs_instance(self, mock_get):
        instances = [
            {
                "id": 100,
                "actual_status": "running",
                "label": "opencurelabs",
                "ssh_host": "74.48.78.46",
                "ssh_port": 22222,
                "gpu_name": "RTX 5090",
                "dph_total": 0.316,
            },
        ]
        mock_get.return_value = MagicMock(json=lambda: {"instances": instances})
        result = _find_reusable_instance("test-key")
        assert result is not None
        inst_id, ssh_host, ssh_port, gpu_name, cost_hr = result
        assert inst_id == 100
        assert ssh_host == "74.48.78.46"
        assert ssh_port == 22222
        assert gpu_name == "RTX 5090"

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_skips_non_running_instance(self, mock_get):
        instances = [
            {
                "id": 200,
                "actual_status": "loading",
                "label": "opencurelabs",
                "ssh_host": "1.2.3.4",
                "ssh_port": 22,
            },
        ]
        mock_get.return_value = MagicMock(json=lambda: {"instances": instances})
        assert _find_reusable_instance("test-key") is None

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_skips_non_opencurelabs_instance(self, mock_get):
        instances = [
            {
                "id": 300,
                "actual_status": "running",
                "label": "someone-else",
                "ssh_host": "5.6.7.8",
                "ssh_port": 22,
            },
        ]
        mock_get.return_value = MagicMock(json=lambda: {"instances": instances})
        assert _find_reusable_instance("test-key") is None

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_no_instances_returns_none(self, mock_get):
        mock_get.return_value = MagicMock(json=lambda: {"instances": []})
        assert _find_reusable_instance("test-key") is None

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_api_error_returns_none(self, mock_get):
        mock_get.side_effect = requests.RequestException("timeout")
        assert _find_reusable_instance("test-key") is None

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_matches_client_id_field(self, mock_get):
        """Instances tagged via client_id (not label) should also match."""
        instances = [
            {
                "id": 400,
                "actual_status": "running",
                "client_id": "opencurelabs",
                "ssh_host": "10.0.0.1",
                "ssh_port": 33333,
                "gpu_name": "A100",
                "dph_total": 1.0,
            },
        ]
        mock_get.return_value = MagicMock(json=lambda: {"instances": instances})
        result = _find_reusable_instance("test-key")
        assert result is not None
        assert result[0] == 400

    @patch("agentiq_labclaw.compute.vast_dispatcher.requests.get")
    def test_skips_instance_without_ssh_host(self, mock_get):
        instances = [
            {
                "id": 500,
                "actual_status": "running",
                "label": "opencurelabs",
                "ssh_host": None,
                "ssh_port": 22,
            },
        ]
        mock_get.return_value = MagicMock(json=lambda: {"instances": instances})
        assert _find_reusable_instance("test-key") is None


# ═══════════════════════════════════════════════════════════════════════════
#  dispatch — reuse path
# ═══════════════════════════════════════════════════════════════════════════

class TestDispatchReuse:
    """Test that dispatch claims pool instances and keeps them alive on success."""

    @patch("agentiq_labclaw.compute.vast_dispatcher._record_spend_end")
    @patch("agentiq_labclaw.compute.vast_dispatcher._record_spend_start", return_value=1)
    @patch("agentiq_labclaw.compute.vast_dispatcher._release_pool_instance")
    @patch("agentiq_labclaw.compute.vast_dispatcher._run_remote")
    @patch("agentiq_labclaw.compute.vast_dispatcher._claim_pool_instance")
    @patch("agentiq_labclaw.compute.vast_dispatcher.check_budget", return_value=(True, 10.0, 20.0))
    def test_reuses_existing_instance(
        self, mock_budget, mock_claim, mock_remote, mock_release, mock_spend_start, mock_spend_end,
        monkeypatch,
    ):
        monkeypatch.setenv("VAST_AI_KEY", "test-key")
        mock_claim.return_value = (100, "74.48.78.46", 22222, "RTX 5090", 0.316)

        skill = MagicMock()
        skill.name = "structure_prediction"
        skill.gpu_required = True
        mock_remote.return_value = MagicMock()

        result = dispatch(skill, MagicMock())

        mock_claim.assert_called_once()
        mock_remote.assert_called_once()
        # Instance returned to pool, not destroyed
        mock_release.assert_called_once_with(100)
        assert result == mock_remote.return_value

    @patch("agentiq_labclaw.compute.vast_dispatcher._record_spend_end")
    @patch("agentiq_labclaw.compute.vast_dispatcher._record_spend_start", return_value=1)
    @patch("agentiq_labclaw.compute.vast_dispatcher._release_pool_instance")
    @patch("agentiq_labclaw.compute.vast_dispatcher.VastInstance")
    @patch("agentiq_labclaw.compute.vast_dispatcher._run_remote")
    @patch("agentiq_labclaw.compute.vast_dispatcher._claim_pool_instance")
    @patch("agentiq_labclaw.compute.vast_dispatcher.check_budget", return_value=(True, 10.0, 20.0))
    @patch("agentiq_labclaw.compute.vast_dispatcher._find_cheapest_offer")
    @patch("agentiq_labclaw.compute.vast_dispatcher._create_instance")
    def test_pool_failure_falls_through_to_provision(
        self, mock_create, mock_offer, mock_budget, mock_claim, mock_remote, mock_vi,
        mock_release, mock_spend_start, mock_spend_end, monkeypatch,
    ):
        """When a pool instance fails SSH, it is evicted and dispatch falls through to provision a new instance."""
        monkeypatch.setenv("VAST_AI_KEY", "test-key")
        mock_claim.return_value = (100, "74.48.78.46", 22222, "RTX 5090", 0.316)
        # Pool SSH fails; second run_remote (on new instance) succeeds
        mock_remote.side_effect = [RuntimeError("SSH failed"), {"result": "ok"}]
        mock_offer.return_value = {"id": 999, "dph_total": 0.40, "gpu_name": "RTX 5090"}
        mock_create.return_value = 200

        inst = MagicMock()
        inst.wait_until_ready.return_value = {"ssh_host": "1.2.3.4", "ssh_port": 22}
        mock_vi.return_value = inst

        with patch("agentiq_labclaw.compute.vast_dispatcher._wait_for_setup"):
            with patch("agentiq_labclaw.compute.vast_dispatcher._register_pool_instance"):
                skill = MagicMock()
                skill.name = "qsar"
                skill.gpu_required = True
                result = dispatch(skill, MagicMock())

        assert result == {"result": "ok"}
        # Dead pool instance should be evicted
        mock_release.assert_any_call(100, destroy=True)
        # Spend should be recorded for both the failed claim and the new instance
        assert mock_spend_end.call_count == 2
