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
    _create_instance,
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
