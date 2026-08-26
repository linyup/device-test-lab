from __future__ import annotations

import unittest

from device_lab.models import Device, TaskStatus
from device_lab.scheduler import InMemoryTaskRepository, Scheduler, TaskConflict


class Clock:
    def __init__(self) -> None:
        self.now = 1_000

    def __call__(self) -> int:
        return self.now


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.scheduler = Scheduler(InMemoryTaskRepository(), self.clock)
        self.android = Device("pixel", "agent-1", "android", frozenset({"screen", "input"}), {"pool": "local"})

    def test_claim_respects_platform_capabilities_and_labels(self):
        self.scheduler.submit("ios.flow.json", "ios")
        expected = self.scheduler.submit("android.flow.json", "android", {"screen"}, {"pool": "local"})
        claimed = self.scheduler.claim(self.android)
        self.assertIsNotNone(claimed)
        self.assertEqual(expected.id, claimed.id)
        self.assertEqual(TaskStatus.RUNNING, claimed.status)

    def test_expired_lease_is_recovered_and_reclaimed(self):
        submitted = self.scheduler.submit("demo.flow.json", "android")
        first = self.scheduler.claim(self.android, lease_ms=100)
        self.assertEqual(submitted.id, first.id)
        self.clock.now += 101
        second = self.scheduler.claim(self.android, lease_ms=100)
        self.assertEqual(submitted.id, second.id)
        self.assertEqual(2, second.attempt)

    def test_wrong_device_cannot_complete_task(self):
        submitted = self.scheduler.submit("demo.flow.json", "android")
        self.scheduler.claim(self.android)
        with self.assertRaises(TaskConflict):
            self.scheduler.complete(submitted.id, "other-device", True)

    def test_cancel_is_idempotent(self):
        submitted = self.scheduler.submit("demo.flow.json", "android")
        self.assertEqual(TaskStatus.CANCELED, self.scheduler.cancel(submitted.id).status)
        self.assertEqual(TaskStatus.CANCELED, self.scheduler.cancel(submitted.id).status)


if __name__ == "__main__":
    unittest.main()

