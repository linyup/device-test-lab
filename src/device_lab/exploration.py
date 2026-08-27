from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExplorationEvent:
    sequence: int
    kind: str
    payload: dict[str, Any]
    created_at_ms: int


@dataclass
class Exploration:
    id: str
    device_id: str
    platform: str
    purpose: str
    status: str = "active"
    events: list[ExplorationEvent] = field(default_factory=list)


class ExplorationStore:
    """Isolated append-only exploration timeline; production can replace this adapter."""

    def __init__(self) -> None:
        self._items: dict[str, Exploration] = {}
        self._lock = threading.RLock()

    def start(self, device_id: str, platform: str, purpose: str) -> Exploration:
        with self._lock:
            item = Exploration(str(uuid.uuid4()), device_id, platform, purpose)
            self._items[item.id] = item
            return item

    def get(self, exploration_id: str) -> Exploration:
        with self._lock:
            if exploration_id not in self._items:
                raise LookupError(exploration_id)
            return self._items[exploration_id]

    def append(self, exploration_id: str, kind: str, payload: dict[str, Any]) -> ExplorationEvent:
        with self._lock:
            item = self.get(exploration_id)
            if item.status != "active":
                raise ValueError("exploration is not active")
            event = ExplorationEvent(len(item.events) + 1, kind, dict(payload), int(time.time() * 1000))
            item.events.append(event)
            return event

    def finish(self, exploration_id: str, status: str) -> Exploration:
        if status not in {"completed", "discarded"}:
            raise ValueError("invalid exploration terminal status")
        with self._lock:
            item = self.get(exploration_id)
            item.status = status
            return item

    @staticmethod
    def serialize(item: Exploration) -> dict[str, Any]:
        return asdict(item)
