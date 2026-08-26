from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL_STATUSES = {TaskStatus.PASSED, TaskStatus.FAILED, TaskStatus.CANCELED}


@dataclass(frozen=True)
class Device:
    id: str
    agent_id: str
    platform: str
    capabilities: frozenset[str] = frozenset()
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class Task:
    id: str
    flow_ref: str
    platform: str
    required_capabilities: frozenset[str] = frozenset()
    labels: dict[str, str] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.QUEUED
    created_at_ms: int = 0
    lease_owner: str | None = None
    lease_expires_at_ms: int | None = None
    attempt: int = 0
    result: dict[str, Any] | None = None

    def matches(self, device: Device) -> bool:
        return (
            self.platform in {"any", device.platform}
            and self.required_capabilities.issubset(device.capabilities)
            and all(device.labels.get(key) == value for key, value in self.labels.items())
        )

