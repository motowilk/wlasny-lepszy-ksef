import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class DiscordNotificationAdapter:
    """Send messages to a Discord channel via webhook."""

    def __init__(self, webhook_url: str | None = None) -> None:
        self._webhook_url = webhook_url or settings.discord_webhook_url

    @property
    def enabled(self) -> bool:
        return bool(self._webhook_url)

    def send(self, content: str) -> bool:
        if not self.enabled:
            logger.debug("Discord webhook not configured, skipping.")
            return False

        payload = {"content": content}

        try:
            response = httpx.post(
                self._webhook_url,
                json=payload,
                timeout=10,
            )
            if response.status_code in (200, 204):
                logger.info("Discord notification sent successfully.")
                return True
            else:
                logger.warning(
                    "Discord webhook returned %s: %s",
                    response.status_code,
                    response.text[:200],
                )
                return False
        except httpx.HTTPError as exc:
            logger.error("Discord webhook request failed: %s", exc)
            return False
