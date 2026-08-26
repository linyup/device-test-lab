from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from device_lab.case_library import CaseLibrary


def tree(case_id: str, title: str, action: str = "Create a note") -> dict:
    return {
        "schema_version": 1,
        "title": "Notes regression",
        "module": "Notes",
        "groups": [{"title": "Editing", "scenarios": [{"id": case_id, "title": title, "steps": [{"action": action, "assertions": ["The note is saved"]}]}]}],
    }


class CaseLibraryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.library = CaseLibrary(Path(self.directory.name) / "cases.db")

    def tearDown(self):
        self.directory.cleanup()

    def publish_new_set(self):
        preview = self.library.preview(tree("create", "Create a note"), {"mode": "new_case_set", "module": "Notes", "title": "Regression"})
        return self.library.commit(preview["operation_id"], preview["operation_id"])

    def test_new_set_commit_is_idempotent_and_undoable(self):
        committed = self.publish_new_set()
        repeated = self.library.commit(committed["operation_id"], committed["operation_id"])
        self.assertTrue(repeated["idempotent"])
        self.assertEqual(1, len(self.library.list_sets()))
        self.library.undo(committed["operation_id"])
        self.assertEqual([], self.library.list_sets())

    def test_merge_preview_classifies_duplicate_conflict_and_addition(self):
        case_set_id = self.publish_new_set()["case_set_id"]
        duplicate = self.library.preview(tree("create", "Create a note"), {"mode": "merge", "case_set_id": case_set_id})
        self.assertEqual(1, duplicate["summary"]["duplicates"])
        conflict = self.library.preview(tree("other", "Create a note", "Create it differently"), {"mode": "merge", "case_set_id": case_set_id})
        self.assertEqual(1, conflict["summary"]["conflicts"])
        addition = self.library.preview(tree("delete", "Delete a note", "Delete a note"), {"mode": "merge", "case_set_id": case_set_id, "group": "Editing"})
        self.assertEqual(1, addition["summary"]["additions"])
        result = self.library.commit(addition["operation_id"], addition["operation_id"])
        self.assertEqual(2, len(self.library.get_set(result["case_set_id"])["content"]["groups"][0]["scenarios"]))
        self.library.undo(addition["operation_id"])
        self.assertEqual(1, len(self.library.get_set(result["case_set_id"])["content"]["groups"][0]["scenarios"]))

    def test_demo_seed_is_idempotent_and_publication_is_visible(self):
        first = self.library.seed_demo()
        second = self.library.seed_demo()
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(1, len(self.library.list_sets()))
        publications = self.library.list_publications()
        self.assertEqual("committed", publications[0]["status"])
        self.assertEqual(3, publications[0]["summary"]["additions"])


if __name__ == "__main__":
    unittest.main()
