"""Tests for Discord, GitHub, and PDF publishers."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

from agentiq_labclaw.publishers.discord_publisher import (
    DiscordPublisher,
    _resolve_webhook,
    _ENV_AGENT_LOGS,
    _ENV_RESULTS,
    _ENV_LEGACY,
)
from agentiq_labclaw.publishers.github_publisher import GitHubPublisher


# ═══════════════════════════════════════════════════════════════════════════
#  _resolve_webhook
# ═══════════════════════════════════════════════════════════════════════════

class TestResolveWebhook:
    """Test the _resolve_webhook helper function."""

    def test_returns_specific_env_var(self, monkeypatch):
        monkeypatch.setenv(_ENV_AGENT_LOGS, "https://hooks.example.com/logs")
        assert _resolve_webhook(_ENV_AGENT_LOGS) == "https://hooks.example.com/logs"

    def test_falls_back_to_legacy(self, monkeypatch):
        monkeypatch.delenv(_ENV_AGENT_LOGS, raising=False)
        monkeypatch.setenv(_ENV_LEGACY, "https://hooks.example.com/legacy")
        assert _resolve_webhook(_ENV_AGENT_LOGS) == "https://hooks.example.com/legacy"

    def test_returns_empty_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv(_ENV_AGENT_LOGS, raising=False)
        monkeypatch.delenv(_ENV_LEGACY, raising=False)
        assert _resolve_webhook(_ENV_AGENT_LOGS) == ""

    def test_prefers_specific_over_legacy(self, monkeypatch):
        monkeypatch.setenv(_ENV_AGENT_LOGS, "https://specific")
        monkeypatch.setenv(_ENV_LEGACY, "https://legacy")
        assert _resolve_webhook(_ENV_AGENT_LOGS) == "https://specific"

    def test_empty_specific_falls_back(self, monkeypatch):
        monkeypatch.setenv(_ENV_AGENT_LOGS, "")
        monkeypatch.setenv(_ENV_LEGACY, "https://legacy")
        assert _resolve_webhook(_ENV_AGENT_LOGS) == "https://legacy"


# ═══════════════════════════════════════════════════════════════════════════
#  DiscordPublisher
# ═══════════════════════════════════════════════════════════════════════════

class TestDiscordPublisher:
    """Test DiscordPublisher initialization, properties, and methods."""

    def test_init_with_explicit_url(self):
        pub = DiscordPublisher(webhook_url="https://explicit")
        assert pub.logs_url == "https://explicit"
        assert pub.results_url == "https://explicit"

    def test_init_from_env(self, monkeypatch):
        monkeypatch.setenv(_ENV_AGENT_LOGS, "https://logs")
        monkeypatch.setenv(_ENV_RESULTS, "https://results")
        pub = DiscordPublisher()
        assert pub.logs_url == "https://logs"
        assert pub.results_url == "https://results"

    def test_enabled_true(self):
        pub = DiscordPublisher(webhook_url="https://hook")
        assert pub.enabled is True

    def test_enabled_false(self, monkeypatch):
        monkeypatch.delenv(_ENV_AGENT_LOGS, raising=False)
        monkeypatch.delenv(_ENV_RESULTS, raising=False)
        monkeypatch.delenv(_ENV_LEGACY, raising=False)
        pub = DiscordPublisher()
        assert pub.enabled is False

    def test_webhook_url_property(self):
        pub = DiscordPublisher(webhook_url="https://hook")
        assert pub.webhook_url == "https://hook"

    @patch("agentiq_labclaw.publishers.discord_publisher.requests.post")
    def test_post_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        pub = DiscordPublisher(webhook_url="https://hook")
        assert pub._post("https://hook", {"content": "test"}) is True
        mock_post.assert_called_once()

    @patch("agentiq_labclaw.publishers.discord_publisher.requests.post")
    def test_post_no_url_returns_false(self, mock_post):
        pub = DiscordPublisher(webhook_url="https://hook")
        assert pub._post("", {"content": "test"}) is False
        mock_post.assert_not_called()

    @patch("agentiq_labclaw.publishers.discord_publisher.requests.post")
    def test_post_request_error(self, mock_post):
        import requests
        mock_post.side_effect = requests.RequestException("timeout")
        pub = DiscordPublisher(webhook_url="https://hook")
        assert pub._post("https://hook", {"content": "test"}) is False

    @patch("agentiq_labclaw.publishers.discord_publisher.requests.post")
    def test_send_message_logs_channel(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        pub = DiscordPublisher(webhook_url="https://hook")
        pub.send_message("hello", channel="logs")
        payload = mock_post.call_args[1]["json"]
        assert payload["content"] == "hello"
        assert payload["username"] == "LabClaw"

    @patch("agentiq_labclaw.publishers.discord_publisher.requests.post")
    def test_send_message_results_channel(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        pub = DiscordPublisher(webhook_url="https://hook")
        pub.results_url = "https://results-hook"
        pub.send_message("hello", channel="results")
        assert mock_post.call_args[0][0] == "https://results-hook"

    @patch("agentiq_labclaw.publishers.discord_publisher.requests.post")
    def test_send_message_truncates_at_2000(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        pub = DiscordPublisher(webhook_url="https://hook")
        long_msg = "x" * 3000
        pub.send_message(long_msg)
        payload = mock_post.call_args[1]["json"]
        assert len(payload["content"]) == 2000

    @patch("agentiq_labclaw.publishers.discord_publisher.requests.post")
    def test_send_embed_basic(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        pub = DiscordPublisher(webhook_url="https://hook")
        pub.send_embed("Title", "Desc", color=0xFF0000)
        payload = mock_post.call_args[1]["json"]
        embed = payload["embeds"][0]
        assert embed["title"] == "Title"
        assert embed["description"] == "Desc"
        assert embed["color"] == 0xFF0000

    @patch("agentiq_labclaw.publishers.discord_publisher.requests.post")
    def test_send_embed_truncates_fields_at_25(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        pub = DiscordPublisher(webhook_url="https://hook")
        fields = [{"name": f"F{i}", "value": f"V{i}"} for i in range(30)]
        pub.send_embed("T", "D", fields=fields)
        payload = mock_post.call_args[1]["json"]
        assert len(payload["embeds"][0]["fields"]) == 25

    @patch("agentiq_labclaw.publishers.discord_publisher.requests.post")
    def test_send_embed_truncates_description(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        pub = DiscordPublisher(webhook_url="https://hook")
        pub.send_embed("T", "x" * 5000)
        payload = mock_post.call_args[1]["json"]
        assert len(payload["embeds"][0]["description"]) == 4096

    @patch("agentiq_labclaw.publishers.discord_publisher.requests.post")
    def test_log_agent_action(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        pub = DiscordPublisher(webhook_url="https://hook")
        pub.log_agent_action("CancerAgent", "Started pipeline", "details here")
        payload = mock_post.call_args[1]["json"]
        assert "CancerAgent" in payload["content"]
        assert "Started pipeline" in payload["content"]
        assert "details here" in payload["content"]

    @patch("agentiq_labclaw.publishers.discord_publisher.requests.post")
    def test_log_agent_action_no_details(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        pub = DiscordPublisher(webhook_url="https://hook")
        pub.log_agent_action("Agent", "Action")
        payload = mock_post.call_args[1]["json"]
        assert "```" not in payload["content"]

    @patch("agentiq_labclaw.publishers.discord_publisher.requests.post")
    def test_log_result_novel(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        pub = DiscordPublisher(webhook_url="https://hook")
        pub.log_result("neoantigen", {"gene": "TP53"}, novel=True)
        payload = mock_post.call_args[1]["json"]
        embed = payload["embeds"][0]
        assert "Novel" in embed["title"]
        assert embed["color"] == 0x57F287

    @patch("agentiq_labclaw.publishers.discord_publisher.requests.post")
    def test_log_result_replication(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        pub = DiscordPublisher(webhook_url="https://hook")
        pub.log_result("docking", {"score": 0.5}, novel=False)
        payload = mock_post.call_args[1]["json"]
        embed = payload["embeds"][0]
        assert "Result" in embed["title"]
        assert embed["color"] == 0x5865F2


# ═══════════════════════════════════════════════════════════════════════════
#  GitHubPublisher
# ═══════════════════════════════════════════════════════════════════════════

class TestGitHubPublisher:
    """Test GitHubPublisher with mocked subprocess."""

    @patch("agentiq_labclaw.publishers.github_publisher.subprocess.run")
    def test_commit_and_push_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        pub = GitHubPublisher(repo_path="/tmp/test-repo")
        result = pub.commit_and_push(["file.txt"], "test commit")
        assert result is True
        # git add + git commit + git push = 3 calls
        assert mock_run.call_count == 3

    @patch("agentiq_labclaw.publishers.github_publisher.subprocess.run")
    def test_commit_and_push_git_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr=b"error")
        pub = GitHubPublisher(repo_path="/tmp/test-repo")
        result = pub.commit_and_push(["file.txt"], "test commit")
        assert result is False

    @patch("agentiq_labclaw.publishers.github_publisher.subprocess.run")
    def test_commit_result(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        pub = GitHubPublisher(repo_path="/tmp/test-repo")
        result = pub.commit_result("reports/out.pdf", "neoantigen")
        assert result is True
        # Check the commit message
        commit_call = mock_run.call_args_list[1]
        assert "neoantigen" in commit_call[0][0][3]

    @patch("agentiq_labclaw.publishers.github_publisher.subprocess.run")
    def test_commit_and_push_multiple_files(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        pub = GitHubPublisher(repo_path="/tmp/test-repo")
        result = pub.commit_and_push(["a.txt", "b.txt", "c.txt"], "multi")
        assert result is True
        # 3 git add + 1 commit + 1 push = 5 calls
        assert mock_run.call_count == 5
