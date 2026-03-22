"""GitHub publisher — commits results and code to the repository."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("labclaw.publishers.github")


class GitHubPublisher:
    """Commits and pushes results to the OpenCure Labs GitHub repository."""

    def __init__(self, repo_path: str | None = None):
        if repo_path is None:
            import os
            repo_path = os.environ.get("OPENCURELABS_ROOT", str(Path(__file__).resolve().parents[3]))
        self.repo_path = Path(repo_path)

    def commit_and_push(self, files: list[str], message: str, branch: str = "main") -> bool:
        """Stage files, commit, and push to GitHub."""
        try:
            for f in files:
                subprocess.run(["git", "add", f], cwd=self.repo_path, check=True, capture_output=True)  # noqa: S603, S607

            subprocess.run(  # noqa: S603
                ["git", "commit", "-m", message],  # noqa: S607
                cwd=self.repo_path, check=True, capture_output=True,
            )
            subprocess.run(  # noqa: S603
                ["git", "push", "origin", branch],  # noqa: S607
                cwd=self.repo_path, check=True, capture_output=True,
            )
            logger.info("Pushed commit to %s: %s", branch, message)
            return True
        except subprocess.CalledProcessError as e:
            logger.error("Git operation failed: %s\n%s", e, e.stderr.decode() if e.stderr else "")
            return False

    def commit_result(self, result_path: str, pipeline_name: str) -> bool:
        """Commit a result file with a standardized message."""
        message = f"result: {pipeline_name} output"
        return self.commit_and_push([result_path], message)
