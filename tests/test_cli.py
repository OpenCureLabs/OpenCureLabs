"""Tests for the opencure CLI module — env helpers and burst commands."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

from agentiq_labclaw.cli import (
    _list_instances,
    _opencure_instances,
    _read_env_compute_mode,
    _read_env_key,
    _set_env_key,
    _vast_headers,
    main,
)

# ═══════════════════════════════════════════════════════════════════════════
#  _read_env_key
# ═══════════════════════════════════════════════════════════════════════════

class TestReadEnvKey:
    """Test reading keys from .env file."""

    def test_reads_existing_key(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("VAST_AI_KEY=abc123\nOTHER=foo\n")
        monkeypatch.setattr("agentiq_labclaw.cli.ENV_FILE", env)
        assert _read_env_key("VAST_AI_KEY") == "abc123"

    def test_returns_none_for_missing_key(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("OTHER=foo\n")
        monkeypatch.setattr("agentiq_labclaw.cli.ENV_FILE", env)
        assert _read_env_key("VAST_AI_KEY") is None

    def test_returns_none_for_missing_file(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        monkeypatch.setattr("agentiq_labclaw.cli.ENV_FILE", env)
        assert _read_env_key("VAST_AI_KEY") is None

    def test_ignores_commented_lines(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("# VAST_AI_KEY=old\nVAST_AI_KEY=new\n")
        monkeypatch.setattr("agentiq_labclaw.cli.ENV_FILE", env)
        assert _read_env_key("VAST_AI_KEY") == "new"

    def test_strips_quotes(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text('VAST_AI_KEY="quoted_value"\n')
        monkeypatch.setattr("agentiq_labclaw.cli.ENV_FILE", env)
        assert _read_env_key("VAST_AI_KEY") == "quoted_value"

    def test_handles_value_with_equals(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("KEY=val=ue\n")
        monkeypatch.setattr("agentiq_labclaw.cli.ENV_FILE", env)
        assert _read_env_key("KEY") == "val=ue"


# ═══════════════════════════════════════════════════════════════════════════
#  _set_env_key
# ═══════════════════════════════════════════════════════════════════════════

class TestSetEnvKey:
    """Test writing keys to .env file."""

    def test_creates_new_file(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        monkeypatch.setattr("agentiq_labclaw.cli.ENV_FILE", env)
        _set_env_key("NEW_KEY", "new_value")
        assert env.read_text() == "NEW_KEY=new_value\n"

    def test_updates_existing_key(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("KEY=old\nOTHER=keep\n")
        monkeypatch.setattr("agentiq_labclaw.cli.ENV_FILE", env)
        _set_env_key("KEY", "new")
        content = env.read_text()
        assert "KEY=new" in content
        assert "OTHER=keep" in content
        assert "KEY=old" not in content

    def test_appends_new_key(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("EXISTING=val\n")
        monkeypatch.setattr("agentiq_labclaw.cli.ENV_FILE", env)
        _set_env_key("NEW", "added")
        content = env.read_text()
        assert "EXISTING=val" in content
        assert "NEW=added" in content


# ═══════════════════════════════════════════════════════════════════════════
#  _read_env_compute_mode
# ═══════════════════════════════════════════════════════════════════════════

class TestReadEnvComputeMode:
    """Test compute mode detection."""

    def test_defaults_to_local(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("")
        monkeypatch.setattr("agentiq_labclaw.cli.ENV_FILE", env)
        assert _read_env_compute_mode() == "local"

    def test_reads_from_env(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("LABCLAW_COMPUTE=vast_ai\n")
        monkeypatch.setattr("agentiq_labclaw.cli.ENV_FILE", env)
        assert _read_env_compute_mode() == "vast_ai"


# ═══════════════════════════════════════════════════════════════════════════
#  _vast_headers
# ═══════════════════════════════════════════════════════════════════════════

class TestVastHeaders:
    """Test API header generation."""

    def test_from_env_var(self, monkeypatch):
        monkeypatch.setenv("VAST_AI_KEY", "test-key-123")
        headers = _vast_headers()
        assert headers == {"Authorization": "Bearer test-key-123"}

    def test_missing_key_exits(self, monkeypatch, tmp_path):
        monkeypatch.delenv("VAST_AI_KEY", raising=False)
        env = tmp_path / ".env"
        env.write_text("")
        monkeypatch.setattr("agentiq_labclaw.cli.ENV_FILE", env)
        with pytest.raises(SystemExit):
            _vast_headers()


# ═══════════════════════════════════════════════════════════════════════════
#  _list_instances / _opencure_instances
# ═══════════════════════════════════════════════════════════════════════════

class TestInstanceListing:
    """Test Vast.ai instance listing functions."""

    @patch("agentiq_labclaw.cli.requests.get")
    def test_list_instances(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {"instances": [{"id": 1}, {"id": 2}]},
        )
        result = _list_instances({"Authorization": "Bearer key"})
        assert len(result) == 2

    @patch("agentiq_labclaw.cli.requests.get")
    def test_opencure_instances_filters(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {"instances": [
                {"id": 1, "label": "opencurelabs"},
                {"id": 2, "label": "other"},
                {"id": 3, "client_id": "opencurelabs"},
            ]},
        )
        result = _opencure_instances({"Authorization": "Bearer key"})
        assert len(result) == 2
        assert all(i["id"] != 2 for i in result)


# ═══════════════════════════════════════════════════════════════════════════
#  main (CLI entrypoint)
# ═══════════════════════════════════════════════════════════════════════════

class TestMain:
    """Test CLI argument parsing."""

    def test_no_args_prints_help(self, capsys):
        with patch("sys.argv", ["opencure"]):
            main()
        captured = capsys.readouterr()
        assert "usage" in captured.out.lower() or "opencure" in captured.out.lower()

    def test_burst_no_action_shows_status(self, monkeypatch, tmp_path):
        env = tmp_path / ".env"
        env.write_text("LABCLAW_COMPUTE=local\n")
        monkeypatch.setattr("agentiq_labclaw.cli.ENV_FILE", env)
        monkeypatch.delenv("VAST_AI_KEY", raising=False)
        with patch("sys.argv", ["opencure", "burst"]):
            main()  # Should not raise
