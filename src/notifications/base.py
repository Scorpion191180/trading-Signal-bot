"""Benachrichtigungsvertrag mit Deduplizierungsschlüssel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Notification:
    deduplication_key: str
    title: str
    message: str
    severity: str = "info"


class NotificationChannel(Protocol):
    name: str

    def send(self, notification: Notification) -> bool:
        """Versendet eine Meldung und meldet Erfolg; Secrets liegen nie im Code."""
