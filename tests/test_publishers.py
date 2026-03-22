"""Tests for GitHub and PDF publishers."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

from agentiq_labclaw.publishers.github_publisher import GitHubPublisher


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
