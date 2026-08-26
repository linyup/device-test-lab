from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .models import Task, TaskStatus
from .scheduler import TaskConflict, TaskNotFound


class SqliteTaskRepository:
    """SQLite adapter with transactional mutation and atomic scheduler claims."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY,
              flow_ref TEXT NOT NULL,
              platform TEXT NOT NULL,
              required_capabilities TEXT NOT NULL,
              labels TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at_ms INTEGER NOT NULL,
              lease_owner TEXT,
              lease_expires_at_ms INTEGER,
              attempt INTEGER NOT NULL DEFAULT 0,
              result TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_claim
              ON tasks(status, platform, created_at_ms);
            """
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            flow_ref=row["flow_ref"],
            platform=row["platform"],
            required_capabilities=frozenset(json.loads(row["required_capabilities"])),
            labels=json.loads(row["labels"]),
            status=TaskStatus(row["status"]),
            created_at_ms=row["created_at_ms"],
            lease_owner=row["lease_owner"],
            lease_expires_at_ms=row["lease_expires_at_ms"],
            attempt=row["attempt"],
            result=json.loads(row["result"]) if row["result"] else None,
        )

    def _write(self, task: Task) -> None:
        self._connection.execute(
            """
            UPDATE tasks SET status=?, lease_owner=?, lease_expires_at_ms=?, attempt=?, result=? WHERE id=?
            """,
            (
                task.status.value,
                task.lease_owner,
                task.lease_expires_at_ms,
                task.attempt,
                json.dumps(task.result) if task.result is not None else None,
                task.id,
            ),
        )

    def create(self, task: Task) -> Task:
        try:
            self._connection.execute(
                """
                INSERT INTO tasks(id, flow_ref, platform, required_capabilities, labels, status, created_at_ms,
                                  lease_owner, lease_expires_at_ms, attempt, result)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.flow_ref,
                    task.platform,
                    json.dumps(sorted(task.required_capabilities)),
                    json.dumps(task.labels, sort_keys=True),
                    task.status.value,
                    task.created_at_ms,
                    task.lease_owner,
                    task.lease_expires_at_ms,
                    task.attempt,
                    None,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise TaskConflict(f"task already exists: {task.id}") from error
        return replace(task)

    def get(self, task_id: str) -> Task:
        row = self._connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise TaskNotFound(task_id)
        return self._from_row(row)

    def mutate(self, task_id: str, operation: Callable[[Task], None]) -> Task:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                task = self.get(task_id)
                operation(task)
                self._write(task)
                self._connection.execute("COMMIT")
                return replace(task)
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def queued(self) -> list[Task]:
        rows = self._connection.execute(
            "SELECT * FROM tasks WHERE status=? ORDER BY created_at_ms, id", (TaskStatus.QUEUED.value,)
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def all(self) -> list[Task]:
        rows = self._connection.execute("SELECT * FROM tasks ORDER BY created_at_ms DESC, id").fetchall()
        return [self._from_row(row) for row in rows]

