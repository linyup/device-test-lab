from __future__ import annotations

import threading
import time
import uuid
from dataclasses import replace
from typing import Callable

from .models import TERMINAL_STATUSES, Device, Task, TaskStatus


class TaskConflict(RuntimeError):
    pass


class TaskNotFound(LookupError):
    pass


class InMemoryTaskRepository:
    """Reference repository. Production adapters must preserve atomic claim semantics."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.RLock()

    def create(self, task: Task) -> Task:
        with self._lock:
            if task.id in self._tasks:
                raise TaskConflict(f"task already exists: {task.id}")
            self._tasks[task.id] = task
            return replace(task)

    def get(self, task_id: str) -> Task:
        with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFound(task_id)
            return replace(self._tasks[task_id])

    def mutate(self, task_id: str, operation: Callable[[Task], None]) -> Task:
        with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFound(task_id)
            operation(self._tasks[task_id])
            return replace(self._tasks[task_id])

    def queued(self) -> list[Task]:
        with self._lock:
            return [replace(item) for item in sorted(self._tasks.values(), key=lambda value: value.created_at_ms) if item.status == TaskStatus.QUEUED]

    def all(self) -> list[Task]:
        with self._lock:
            return [replace(item) for item in self._tasks.values()]


class Scheduler:
    def __init__(self, repository: InMemoryTaskRepository, clock_ms: Callable[[], int] | None = None) -> None:
        self.repository = repository
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._claim_lock = threading.Lock()

    def submit(
        self,
        flow_ref: str,
        platform: str,
        required_capabilities: set[str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> Task:
        return self.repository.create(
            Task(
                id=str(uuid.uuid4()),
                flow_ref=flow_ref,
                platform=platform,
                required_capabilities=frozenset(required_capabilities or set()),
                labels=dict(labels or {}),
                created_at_ms=self.clock_ms(),
            )
        )

    def claim(self, device: Device, lease_ms: int = 60_000) -> Task | None:
        if lease_ms <= 0:
            raise ValueError("lease_ms must be positive")
        with self._claim_lock:
            self.recover_expired()
            for task in self.repository.queued():
                if not task.matches(device):
                    continue

                def assign(current: Task) -> None:
                    if current.status != TaskStatus.QUEUED:
                        raise TaskConflict(f"task is not queued: {current.id}")
                    current.status = TaskStatus.RUNNING
                    current.lease_owner = device.id
                    current.lease_expires_at_ms = self.clock_ms() + lease_ms
                    current.attempt += 1

                return self.repository.mutate(task.id, assign)
        return None

    def renew(self, task_id: str, device_id: str, lease_ms: int = 60_000) -> Task:
        def operation(task: Task) -> None:
            self._require_owner(task, device_id)
            task.lease_expires_at_ms = self.clock_ms() + lease_ms

        return self.repository.mutate(task_id, operation)

    def complete(self, task_id: str, device_id: str, passed: bool, result: dict | None = None) -> Task:
        def operation(task: Task) -> None:
            self._require_owner(task, device_id)
            task.status = TaskStatus.PASSED if passed else TaskStatus.FAILED
            task.result = dict(result or {})
            task.lease_owner = None
            task.lease_expires_at_ms = None

        return self.repository.mutate(task_id, operation)

    def cancel(self, task_id: str) -> Task:
        def operation(task: Task) -> None:
            if task.status in TERMINAL_STATUSES:
                return
            task.status = TaskStatus.CANCELED
            task.lease_owner = None
            task.lease_expires_at_ms = None

        return self.repository.mutate(task_id, operation)

    def recover_expired(self) -> list[str]:
        recovered: list[str] = []
        now = self.clock_ms()
        for snapshot in self.repository.all():
            if snapshot.status != TaskStatus.RUNNING or snapshot.lease_expires_at_ms is None:
                continue
            if snapshot.lease_expires_at_ms > now:
                continue

            def operation(task: Task) -> None:
                if task.status == TaskStatus.RUNNING and task.lease_expires_at_ms is not None and task.lease_expires_at_ms <= now:
                    task.status = TaskStatus.QUEUED
                    task.lease_owner = None
                    task.lease_expires_at_ms = None

            updated = self.repository.mutate(snapshot.id, operation)
            if updated.status == TaskStatus.QUEUED:
                recovered.append(updated.id)
        return recovered

    @staticmethod
    def _require_owner(task: Task, device_id: str) -> None:
        if task.status != TaskStatus.RUNNING:
            raise TaskConflict(f"task is not running: {task.id}")
        if task.lease_owner != device_id:
            raise TaskConflict(f"task lease belongs to another device: {task.id}")

