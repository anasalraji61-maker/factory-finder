"""Ports the application service depends on (implemented by adapters / realtime layer)."""

from typing import Protocol

from ff_messaging.domain.events import DomainEvent


class EventPublisher(Protocol):
    """Receives domain events *after* the transaction that produced them has committed."""

    def publish(self, event: DomainEvent) -> None: ...


class NullPublisher:
    """Publisher that drops everything (CLI tools, tests that do not care about realtime)."""

    def publish(self, event: DomainEvent) -> None:
        return None


class RecordingPublisher:
    """Publisher that keeps events in memory (tests)."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)
