from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from device_lab.api import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.directory.name) / "api.db", api_token="test-token"))
        self.headers = {"Authorization": "Bearer test-token"}

    def tearDown(self):
        self.directory.cleanup()

    def test_health_does_not_require_authentication(self):
        self.assertEqual({"status": "ok"}, self.client.get("/health").json())

    def test_task_lifecycle_through_http(self):
        unauthorized = self.client.post("/api/v1/tasks", json={"flow_ref": "demo.flow.json"})
        self.assertEqual(401, unauthorized.status_code)
        created = self.client.post(
            "/api/v1/tasks",
            headers=self.headers,
            json={"flow_ref": "demo.flow.json", "platform": "desktop"},
        )
        self.assertEqual(202, created.status_code)
        task_id = created.json()["id"]
        claimed = self.client.post(
            "/api/v1/tasks/claim/next",
            headers=self.headers,
            json={"device_id": "mac", "agent_id": "local", "platform": "desktop"},
        )
        self.assertEqual(task_id, claimed.json()["id"])
        completed = self.client.post(
            f"/api/v1/tasks/{task_id}/complete",
            headers=self.headers,
            json={"device_id": "mac", "passed": True, "result": {"report": "report.json"}},
        )
        self.assertEqual("passed", completed.json()["status"])
        self.assertEqual("report.json", completed.json()["result"]["report"])

    def test_case_publication_preview_commit_and_undo(self):
        payload = {
            "schema_version": 1,
            "title": "Notes cases",
            "module": "Notes",
            "groups": [{"title": "Editing", "scenarios": [{"id": "create", "title": "Create note", "steps": [{"action": "Save", "assertions": ["Saved"]}]}]}],
        }
        preview = self.client.post(
            "/api/v1/case-publications/preview",
            headers=self.headers,
            json={"payload": payload, "target": {"mode": "new_case_set", "module": "Notes", "title": "Regression"}},
        ).json()
        committed = self.client.post(
            "/api/v1/case-publications/commit",
            headers=self.headers,
            json={"operation_id": preview["operation_id"], "confirmation": preview["operation_id"]},
        )
        self.assertEqual(200, committed.status_code)
        self.assertEqual(1, len(self.client.get("/api/v1/case-sets", headers=self.headers).json()))
        undone = self.client.post(
            f"/api/v1/case-publications/{preview['operation_id']}/undo", headers=self.headers
        )
        self.assertEqual("undone", undone.json()["status"])
        self.assertEqual([], self.client.get("/api/v1/case-sets", headers=self.headers).json())

    def test_exploration_timeline_is_isolated_from_tasks(self):
        started = self.client.post(
            "/api/v1/explorations", headers=self.headers,
            json={"device_id": "android-demo", "platform": "android", "purpose": "flow_repair"},
        ).json()
        exploration_id = started["id"]
        event = self.client.post(
            f"/api/v1/explorations/{exploration_id}/events", headers=self.headers,
            json={"kind": "tool_result", "payload": {"command_success": True, "evidence_success": False}},
        ).json()
        self.assertEqual(1, event["sequence"])
        completed = self.client.post(f"/api/v1/explorations/{exploration_id}/complete", headers=self.headers).json()
        self.assertEqual("completed", completed["status"])
        self.assertEqual([], self.client.get("/api/v1/tasks", headers=self.headers).json())


if __name__ == "__main__":
    unittest.main()
