"""Service for monitoring a GitHub Projects v2 board and notifying via Discord."""

import json
import logging
from pathlib import Path

import httpx

from app.adapters.notification.discord import DiscordNotificationAdapter
from app.core.config import settings

logger = logging.getLogger(__name__)

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
STATE_FILE = Path("data/github_board_state.json")

KSEF_REPO_URL = "https://github.com/CIRFMF/ksef-api"

# GraphQL query for Projects v2
PROJECT_QUERY = """
query($org: String!, $projectNumber: Int!) {
  organization(login: $org) {
    projectV2(number: $projectNumber) {
      title
      items(first: 100) {
        nodes {
          id
          content {
            ... on Issue {
              number
              title
              url
            }
            ... on PullRequest {
              number
              title
              url
            }
          }
          fieldValueByName(name: "Status") {
            ... on ProjectV2ItemFieldSingleSelectValue {
              name
            }
          }
        }
      }
    }
  }
}
"""


class GitHubMonitorService:
    @staticmethod
    def check_board_changes() -> dict:
        """
        Poll the GitHub project board, compare with last known state,
        and send a Discord notification if anything changed.

        Returns a summary dict with changes detected.
        """
        token = settings.github_token
        if not token:
            logger.debug("GITHUB_TOKEN not configured, skipping board check.")
            return {"skipped": True, "reason": "no token"}

        current_state = GitHubMonitorService._fetch_board_state(token)
        if current_state is None:
            return {"skipped": True, "reason": "fetch failed"}

        previous_state = GitHubMonitorService._load_state()
        changes = GitHubMonitorService._diff_states(previous_state, current_state)

        if changes:
            GitHubMonitorService._send_notification(changes)

        GitHubMonitorService._save_state(current_state)

        return {"changes": len(changes), "details": changes}

    @staticmethod
    def _fetch_board_state(token: str) -> dict | None:
        """Fetch current board items and their statuses via GraphQL."""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        variables = {
            "org": settings.github_project_org,
            "projectNumber": settings.github_project_number,
        }

        try:
            response = httpx.post(
                GITHUB_GRAPHQL_URL,
                json={"query": PROJECT_QUERY, "variables": variables},
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("GitHub GraphQL request failed: %s", exc)
            return None

        data = response.json()

        if "errors" in data:
            logger.error("GitHub GraphQL errors: %s", data["errors"])
            return None

        project = (
            data.get("data", {})
            .get("organization", {})
            .get("projectV2")
        )
        if not project:
            logger.warning("Project board not found in response.")
            return None

        # Build state: {issue_number: {"title": ..., "status": ..., "url": ...}}
        state: dict[str, dict] = {}
        for item in project.get("items", {}).get("nodes", []):
            content = item.get("content")
            if not content or not content.get("number"):
                continue

            number = str(content["number"])
            status_field = item.get("fieldValueByName")
            status = status_field.get("name") if status_field else "Unknown"

            state[number] = {
                "title": content.get("title", ""),
                "status": status,
                "url": content.get("url", ""),
            }

        return state

    @staticmethod
    def _diff_states(
        previous: dict | None, current: dict
    ) -> list[dict]:
        """Compare previous and current board states, return list of changes."""
        changes: list[dict] = []

        if previous is None:
            # First run — no diff, just store state
            return []

        # Detect status changes and new items
        for number, cur_item in current.items():
            prev_item = previous.get(number)
            if prev_item is None:
                changes.append({
                    "type": "added",
                    "number": number,
                    "title": cur_item["title"],
                    "status": cur_item["status"],
                    "url": cur_item.get("url", ""),
                })
            elif prev_item.get("status") != cur_item["status"]:
                changes.append({
                    "type": "moved",
                    "number": number,
                    "title": cur_item["title"],
                    "from_status": prev_item["status"],
                    "to_status": cur_item["status"],
                    "url": cur_item.get("url", ""),
                })

        # Detect removed items
        for number, prev_item in previous.items():
            if number not in current:
                changes.append({
                    "type": "removed",
                    "number": number,
                    "title": prev_item["title"],
                    "status": prev_item.get("status", ""),
                    "url": prev_item.get("url", ""),
                })

        return changes

    @staticmethod
    def _send_notification(changes: list[dict]) -> None:
        """Compose and send a Discord message summarising board changes."""
        lines = ["**KSeF Board — zmiany:**"]

        for change in changes:
            number = change["number"]
            title = change["title"]
            link = f"{KSEF_REPO_URL}/issues/{number}"

            if change["type"] == "moved":
                lines.append(
                    f"\u2022 [#{number}]({link}) przesuni\u0119to: "
                    f"**{change['from_status']}** \u2192 **{change['to_status']}** \u2014 {title}"
                )
            elif change["type"] == "added":
                lines.append(
                    f"\u2022 [#{number}]({link}) dodano do **{change['status']}** \u2014 {title}"
                )
            elif change["type"] == "removed":
                lines.append(
                    f"\u2022 [#{number}]({link}) usuni\u0119to z tablicy \u2014 {title}"
                )

        message = "\n".join(lines)
        if len(message) > 1950:
            message = message[:1950] + "\n\u2026 (obci\u0119to)"

        DiscordNotificationAdapter().send(message)

    @staticmethod
    def _load_state() -> dict | None:
        """Load previously saved board state from disk."""
        if not STATE_FILE.exists():
            return None
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load board state: %s", exc)
            return None

    @staticmethod
    def _save_state(state: dict) -> None:
        """Persist current board state to disk."""
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
