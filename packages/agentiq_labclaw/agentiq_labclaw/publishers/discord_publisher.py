"""Discord webhook publisher — streams agent logs and results to Discord.

Uses two webhooks:
  DISCORD_WEBHOOK_URL_AGENT_LOGS  → #agent-logs  (LabClaw — reasoning traces)
  DISCORD_WEBHOOK_URL_RESULTS     → #results     (Discovery Feed — findings)

Legacy DISCORD_WEBHOOK_URL is used as fallback for both if the split vars aren't set.
"""

import json
import logging
import os

import requests

logger = logging.getLogger("labclaw.publishers.discord")

_ENV_AGENT_LOGS = "DISCORD_WEBHOOK_URL_AGENT_LOGS"
_ENV_RESULTS = "DISCORD_WEBHOOK_URL_RESULTS"
_ENV_LEGACY = "DISCORD_WEBHOOK_URL"


def _resolve_webhook(env_var: str) -> str:
    """Return webhook URL from env_var, falling back to the legacy single-URL var."""
    return os.environ.get(env_var, "") or os.environ.get(_ENV_LEGACY, "")


class DiscordPublisher:
    """Publishes agent logs and results to Discord via webhook.

    Supports separate webhooks for agent-logs and results channels.
    Falls back to DISCORD_WEBHOOK_URL if split vars aren't set.
    """

    def __init__(self, webhook_url: str | None = None):
        self._explicit_url = webhook_url
        self.logs_url = webhook_url or _resolve_webhook(_ENV_AGENT_LOGS)
        self.results_url = webhook_url or _resolve_webhook(_ENV_RESULTS)

    @property
    def webhook_url(self) -> str:
        """Legacy accessor — returns the agent-logs URL."""
        return self.logs_url

    @property
    def enabled(self) -> bool:
        return bool(self.logs_url or self.results_url)

    def _post(self, url: str, payload: dict) -> bool:
        if not url:
            logger.warning("Discord webhook not configured, skipping publish")
            return False
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error("Failed to send Discord message: %s", e)
            return False

    def send_message(self, content: str, username: str = "LabClaw",
                     channel: str = "logs") -> bool:
        """Send a text message to Discord.

        channel: 'logs' → #agent-logs, 'results' → #results
        """
        url = self.results_url if channel == "results" else self.logs_url
        payload = {"content": content[:2000], "username": username}
        return self._post(url, payload)

    def send_embed(self, title: str, description: str, fields: list[dict] | None = None,
                   color: int = 0x5865F2, username: str = "LabClaw",
                   channel: str = "logs") -> bool:
        """Send a rich embed to Discord."""
        url = self.results_url if channel == "results" else self.logs_url
        embed = {"title": title[:256], "description": description[:4096], "color": color}
        if fields:
            embed["fields"] = [
                {"name": f["name"][:256], "value": f["value"][:1024], "inline": f.get("inline", False)}
                for f in fields[:25]
            ]
        payload = {"embeds": [embed], "username": username}
        return self._post(url, payload)

    def log_agent_action(self, agent_name: str, action: str, details: str = ""):
        """Log an agent action to #agent-logs."""
        content = f"**[{agent_name}]** {action}"
        if details:
            content += f"\n```\n{details[:1500]}\n```"
        return self.send_message(content, channel="logs")

    def log_result(self, pipeline_name: str, result: dict, novel: bool = False):
        """Log a pipeline result to #results as an embed."""
        color = 0x57F287 if novel else 0x5865F2  # green for novel, blue for replication
        title = f"{'🆕 Novel Result' if novel else '📊 Result'}: {pipeline_name}"
        description = json.dumps(result, indent=2, default=str)[:4000]
        return self.send_embed(title, f"```json\n{description}\n```", color=color,
                               username="Discovery Feed", channel="results")
