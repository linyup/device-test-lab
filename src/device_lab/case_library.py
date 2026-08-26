from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from copy import deepcopy
from pathlib import Path


def normalized_title(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def scenario_fingerprint(case: dict) -> str:
    value = {"title": normalized_title(case.get("title", "")), "preconditions": case.get("preconditions", []), "steps": case.get("steps", [])}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class CaseLibrary:
    def __init__(self, path: Path | str) -> None:
        self.connection = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS case_sets (
              id TEXT PRIMARY KEY,
              module TEXT NOT NULL,
              title TEXT NOT NULL,
              content TEXT NOT NULL,
              version INTEGER NOT NULL DEFAULT 1,
              deleted_at_ms INTEGER,
              created_at_ms INTEGER NOT NULL,
              updated_at_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_case_sets_module ON case_sets(module, deleted_at_ms, updated_at_ms);
            CREATE TABLE IF NOT EXISTS case_publications (
              operation_id TEXT PRIMARY KEY,
              target TEXT NOT NULL,
              payload TEXT NOT NULL,
              preview TEXT NOT NULL,
              before_content TEXT,
              status TEXT NOT NULL,
              created_at_ms INTEGER NOT NULL,
              committed_at_ms INTEGER,
              undone_at_ms INTEGER
            );
            """
        )

    def list_sets(self) -> list[dict]:
        rows = self.connection.execute("SELECT * FROM case_sets WHERE deleted_at_ms IS NULL ORDER BY module, updated_at_ms DESC").fetchall()
        return [self._set(row) for row in rows]

    def get_set(self, case_set_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM case_sets WHERE id=? AND deleted_at_ms IS NULL", (case_set_id,)).fetchone()
        if row is None:
            raise LookupError(case_set_id)
        return self._set(row)

    def list_publications(self, limit: int = 20) -> list[dict]:
        rows = self.connection.execute(
            "SELECT operation_id,target,preview,status,created_at_ms,committed_at_ms,undone_at_ms "
            "FROM case_publications ORDER BY created_at_ms DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        ).fetchall()
        return [
            {
                "operation_id": row["operation_id"],
                "target": json.loads(row["target"]),
                "summary": json.loads(row["preview"])["summary"],
                "status": row["status"],
                "created_at_ms": row["created_at_ms"],
                "committed_at_ms": row["committed_at_ms"],
                "undone_at_ms": row["undone_at_ms"],
            }
            for row in rows
        ]

    def seed_demo(self) -> dict:
        existing = self.connection.execute("SELECT id FROM case_sets WHERE deleted_at_ms IS NULL LIMIT 1").fetchone()
        if existing:
            return {"created": False, "case_set_id": existing["id"]}
        payload = {
            "schema_version": 1,
            "title": "Notes full regression",
            "module": "Notes",
            "groups": [
                {
                    "title": "Create and edit",
                    "scenarios": [
                        {
                            "id": "demo-create-note",
                            "title": "Create and save a note",
                            "priority": "P0",
                            "tags": ["smoke", "regression"],
                            "preconditions": ["The user is signed in"],
                            "steps": [
                                {
                                    "action": "Enter a title and body, then save the note",
                                    "assertions": ["The note appears in the list", "The saved content is preserved after reopening"],
                                }
                            ],
                        },
                        {
                            "id": "demo-edit-note",
                            "title": "Edit an existing note",
                            "priority": "P1",
                            "tags": ["regression"],
                            "preconditions": ["An editable note exists"],
                            "steps": [
                                {"action": "Change the note title", "assertions": ["The new title is displayed in the editor"]},
                                {"action": "Save and return to the list", "assertions": ["The list shows the new title", "The modification time is updated"]},
                            ],
                        },
                    ],
                },
                {
                    "title": "Resilience",
                    "scenarios": [
                        {
                            "id": "demo-offline-note",
                            "title": "Continue editing after reconnecting",
                            "priority": "P1",
                            "tags": ["network", "regression"],
                            "preconditions": ["A note is open"],
                            "steps": [
                                {"action": "Disconnect the network and edit the note", "assertions": ["The draft remains visible"]},
                                {"action": "Reconnect the network", "assertions": ["The draft is synchronized", "No duplicate note is created"]},
                            ],
                        }
                    ],
                },
            ],
        }
        preview = self.preview(payload, {"mode": "new_case_set", "module": "Notes", "title": "Full regression"})
        committed = self.commit(preview["operation_id"], preview["operation_id"])
        return {"created": True, **committed}

    @staticmethod
    def _set(row) -> dict:
        return {
            "id": row["id"], "module": row["module"], "title": row["title"], "content": json.loads(row["content"]),
            "version": row["version"], "created_at_ms": row["created_at_ms"], "updated_at_ms": row["updated_at_ms"],
        }

    @staticmethod
    def _cases(tree: dict):
        for group in tree.get("groups", []):
            for case in group.get("scenarios", []):
                yield group.get("title", "Imported"), case

    def preview(self, payload: dict, target: dict) -> dict:
        mode = target.get("mode")
        if mode not in {"new_case_set", "merge"}:
            raise ValueError("target.mode must be new_case_set or merge")
        additions: list[dict] = []
        duplicates: list[dict] = []
        conflicts: list[dict] = []
        if mode == "new_case_set":
            additions = [case for _, case in self._cases(payload)]
        else:
            existing = self.get_set(target["case_set_id"])["content"]
            by_id = {case["id"]: case for _, case in self._cases(existing)}
            by_title: dict[str, list[dict]] = {}
            for _, case in self._cases(existing):
                by_title.setdefault(normalized_title(case["title"]), []).append(case)
            for group_title, case in self._cases(payload):
                same_id = by_id.get(case["id"])
                titles = by_title.get(normalized_title(case["title"]), [])
                exact = next((item for item in titles if scenario_fingerprint(item) == scenario_fingerprint(case)), None)
                if same_id and scenario_fingerprint(same_id) != scenario_fingerprint(case):
                    conflicts.append({"incoming_id": case["id"], "existing_id": same_id["id"], "reason": "same-id-different-content"})
                elif same_id or exact:
                    duplicates.append({"incoming_id": case["id"], "existing_id": (same_id or exact)["id"]})
                elif titles:
                    conflicts.append({"incoming_id": case["id"], "existing_ids": [item["id"] for item in titles], "reason": "same-title-different-content"})
                else:
                    additions.append({"group": target.get("group") or group_title, "case": case})
        operation_id = str(uuid.uuid4())
        preview = {
            "operation_id": operation_id,
            "target": target,
            "summary": {"additions": len(additions), "duplicates": len(duplicates), "conflicts": len(conflicts)},
            "additions": additions,
            "duplicates": duplicates,
            "conflicts": conflicts,
            "requires_confirmation": True,
        }
        self.connection.execute(
            "INSERT INTO case_publications(operation_id,target,payload,preview,status,created_at_ms) VALUES(?,?,?,?,?,?)",
            (operation_id, json.dumps(target), json.dumps(payload), json.dumps(preview), "previewed", int(time.time() * 1000)),
        )
        return preview

    def commit(self, operation_id: str, confirmation: str) -> dict:
        if confirmation != operation_id:
            raise ValueError("confirmation must equal operation_id")
        row = self.connection.execute("SELECT * FROM case_publications WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            raise LookupError(operation_id)
        if row["status"] == "committed":
            return {"operation_id": operation_id, "status": "committed", "idempotent": True}
        if row["status"] != "previewed":
            raise ValueError(f"publication cannot be committed from {row['status']}")
        preview, payload, target = json.loads(row["preview"]), json.loads(row["payload"]), json.loads(row["target"])
        if preview["conflicts"]:
            raise ValueError("resolve conflicts before commit")
        now = int(time.time() * 1000)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if target["mode"] == "new_case_set":
                case_set_id = str(uuid.uuid4())
                self.connection.execute(
                    "INSERT INTO case_sets(id,module,title,content,version,created_at_ms,updated_at_ms) VALUES(?,?,?,?,1,?,?)",
                    (case_set_id, target["module"], target.get("title") or payload.get("title", "Imported cases"), json.dumps(payload), now, now),
                )
                before = {"created_case_set_id": case_set_id}
            else:
                current = self.get_set(target["case_set_id"])
                case_set_id = current["id"]
                before = current["content"]
                merged = deepcopy(before)
                for addition in preview["additions"]:
                    group = next((item for item in merged.setdefault("groups", []) if item.get("title") == addition["group"]), None)
                    if group is None:
                        group = {"title": addition["group"], "scenarios": []}
                        merged["groups"].append(group)
                    group.setdefault("scenarios", []).append(addition["case"])
                self.connection.execute(
                    "UPDATE case_sets SET content=?,version=version+1,updated_at_ms=? WHERE id=?",
                    (json.dumps(merged), now, case_set_id),
                )
            self.connection.execute(
                "UPDATE case_publications SET status='committed',before_content=?,committed_at_ms=? WHERE operation_id=?",
                (json.dumps(before) if before is not None else None, now, operation_id),
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return {"operation_id": operation_id, "status": "committed", "case_set_id": case_set_id}

    def undo(self, operation_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM case_publications WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            raise LookupError(operation_id)
        if row["status"] == "undone":
            return {"operation_id": operation_id, "status": "undone", "idempotent": True}
        if row["status"] != "committed":
            raise ValueError("only committed publications can be undone")
        target = json.loads(row["target"])
        now = int(time.time() * 1000)
        if target["mode"] == "new_case_set":
            before = json.loads(row["before_content"])
            self.connection.execute("UPDATE case_sets SET deleted_at_ms=? WHERE id=?", (now, before["created_case_set_id"]))
        else:
            self.connection.execute(
                "UPDATE case_sets SET content=?,version=version+1,updated_at_ms=? WHERE id=?",
                (row["before_content"], now, target["case_set_id"]),
            )
        self.connection.execute("UPDATE case_publications SET status='undone',undone_at_ms=? WHERE operation_id=?", (now, operation_id))
        return {"operation_id": operation_id, "status": "undone"}
