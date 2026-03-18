"""Discord webhook publisher — streams agent logs and results to Discord."""

import json
import logging
import os

import requests

logger = logging.getLogger("labclaw.publishers.discord")


class DiscordPublisher:
    """Publishes agent logs and results to Discord via webhook."""

    def __init__(self, webhook_url: str | None = None):
        self.webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL", "")

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def send_message(self, content: str, username: str = "OpenCure Labs") -> bool:
        """Send a text message to Discord."""
        if not self.enabled:
            logger.warning("Discord webhook not configured, skipping publish")
            return False

        payload = {"content": content[:2000], "username": username}
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error("Failed to send Discord message: %s", e)
            return False

    def send_embed(self, title: str, description: str, fields: list[dict] | None = None,
                   color: int = 0x5865F2, username: str = "OpenCure Labs") -> bool:
        """Send a rich embed to Discord."""
        if not self.enabled:
            logger.warning("Discord webhook not configured, skipping publish")
            return False

        embed = {"title": title[:256], "description": description[:4096], "color": color}
        if fields:
            embed["fields"] = [
                {"name": f["name"][:256], "value": f["value"][:1024], "inline": f.get("inline", False)}
                for f in fields[:25]
            ]

        payload = {"embeds": [embed], "username": username}
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error("Failed to send Discord embed: %s", e)
            return False

    def log_agent_action(self, agent_name: str, action: str, details: str = ""):
        """Log an agent action to Discord."""
        content = f"**[{agent_name}]** {action}"
        if details:
            content += f"\n```\n{details[:1500]}\n```"
        return self.send_message(content)

    def log_result(self, pipeline_name: str, result: dict, novel: bool = False):
        """Log a pipeline result to Discord as an embed."""
        color = 0x57F287 if novel else 0x5865F2  # green for novel, blue for replication
        title = f"{'🆕 Novel Result' if novel else '📊 Result'}: {pipeline_name}"
        description = json.dumps(result, indent=2, default=str)[:4000]
        return self.send_embed(title, f"```json\n{description}\n```", color=color)
