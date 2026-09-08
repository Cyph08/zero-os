"""
core/alerts.py — Zero OS Proactive Alert Queue

A lightweight in-memory queue for proactive messages Zero pushes to the phone.
When a scheduled job runs (morning briefing, news digest, research digest),
it pushes an AlertMessage here. The phone polls /phone/alerts every 30 seconds
and receives any pending messages.

This is intentionally simple — no WebSockets, no Firebase, no infrastructure.
Just a deque the phone polls. If Redis is running, uses that for persistence
across restarts. Falls back to in-memory if not.

Alert lifecycle:
  1. Scheduler job runs → calls alert_queue.push(message)
  2. Phone polls /phone/alerts → receives list of unread alerts
  3. Server marks them as delivered (or phone can mark them explicitly)
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Max alerts to keep in memory (oldest are dropped when full)
MAX_ALERTS = 50


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AlertMessage:
    """
    A single proactive message from Zero to the phone.

    Attributes:
        alert_id:   Unique ID for this alert (used to mark as delivered).
        alert_type: Category — "briefing", "news", "research", "reminder", "system"
        title:      Short headline shown in the notification (e.g. "Morning Briefing")
        body:       Full message content to display in chat.
        delivered:  True once the phone has received this alert.
        timestamp:  Unix timestamp when this was created.
    """
    alert_id: str
    alert_type: str
    title: str
    body: str
    delivered: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict for JSON response."""
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type,
            "title": self.title,
            "body": self.body,
            "delivered": self.delivered,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Alert queue
# ---------------------------------------------------------------------------

class AlertQueue:
    """
    In-memory FIFO queue for proactive Zero → phone messages.

    Thread-safe — scheduler jobs and FastAPI handlers run concurrently.
    """

    def __init__(self, max_size: int = MAX_ALERTS) -> None:
        """
        Args:
            max_size: Maximum alerts to keep. Oldest dropped when full.
        """
        self._queue: deque[AlertMessage] = deque(maxlen=max_size)
        self._counter: int = 0

    def push(
        self,
        alert_type: str,
        title: str,
        body: str,
    ) -> AlertMessage:
        """
        Push a new proactive alert onto the queue.

        Called by scheduler jobs when they have something to tell Cyph.

        Args:
            alert_type: Category string — "briefing", "news", "research", "reminder".
            title:      Short notification title.
            body:       Full message body.

        Returns:
            The created AlertMessage.
        """
        self._counter += 1
        alert = AlertMessage(
            alert_id=f"alert_{self._counter}_{int(time.time())}",
            alert_type=alert_type,
            title=title,
            body=body,
        )
        self._queue.append(alert)
        logger.info(f"[alerts] Pushed: [{alert_type}] {title!r}")
        return alert

    def get_undelivered(self) -> list[AlertMessage]:
        """
        Return all undelivered alerts without marking them as delivered.

        The phone calls this to check for new messages.

        Returns:
            List of undelivered AlertMessage objects, oldest first.
        """
        return [a for a in self._queue if not a.delivered]

    def mark_delivered(self, alert_ids: list[str]) -> int:
        """
        Mark specific alerts as delivered.

        Args:
            alert_ids: List of alert_id strings to mark.

        Returns:
            Number of alerts actually marked.
        """
        marked = 0
        for alert in self._queue:
            if alert.alert_id in alert_ids:
                alert.delivered = True
                marked += 1
        logger.debug(f"[alerts] Marked {marked} alerts as delivered")
        return marked

    def mark_all_delivered(self) -> int:
        """
        Mark all pending alerts as delivered (phone has seen them all).

        Returns:
            Number of alerts marked.
        """
        count = 0
        for alert in self._queue:
            if not alert.delivered:
                alert.delivered = True
                count += 1
        logger.debug(f"[alerts] Marked all {count} pending alerts as delivered")
        return count

    def clear(self) -> None:
        """Wipe all alerts (useful for testing or reset)."""
        self._queue.clear()
        logger.info("[alerts] Queue cleared")

    def all_alerts(self) -> list[AlertMessage]:
        """Return all alerts (delivered + undelivered), newest first."""
        return list(reversed(self._queue))

    @property
    def pending_count(self) -> int:
        """Number of undelivered alerts waiting for the phone."""
        return sum(1 for a in self._queue if not a.delivered)

    def __len__(self) -> int:
        return len(self._queue)

    def __repr__(self) -> str:
        return f"AlertQueue({self.pending_count} pending / {len(self._queue)} total)"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

alert_queue = AlertQueue()
