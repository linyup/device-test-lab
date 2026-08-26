from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from device_lab.models import Device, TaskStatus
from device_lab.scheduler import Scheduler
from device_lab.sqlite_repository import SqliteTaskRepository


class SqliteRepositoryTests(unittest.TestCase):
    def test_task_survives_repository_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lab.db"
            task = Scheduler(SqliteTaskRepository(path)).submit("demo.flow.json", "desktop")
            reopened = SqliteTaskRepository(path).get(task.id)
            self.assertEqual("demo.flow.json", reopened.flow_ref)

    def test_claim_and_complete_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SqliteTaskRepository(Path(directory) / "lab.db")
            scheduler = Scheduler(repository)
            task = scheduler.submit("demo.flow.json", "desktop")
            device = Device("mac", "agent", "desktop")
            scheduler.claim(device)
            scheduler.complete(task.id, device.id, True, {"report": "result.json"})
            persisted = repository.get(task.id)
            self.assertEqual(TaskStatus.PASSED, persisted.status)
            self.assertEqual("result.json", persisted.result["report"])


if __name__ == "__main__":
    unittest.main()

