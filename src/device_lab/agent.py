from __future__ import annotations

import argparse
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


class PlatformClient:
    def __init__(self, base_url: str, token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def post(self, path: str, payload: dict):
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {self.token}"} if self.token else {})},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"null")

    def get(self, path: str):
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={**({"Authorization": f"Bearer {self.token}"} if self.token else {})},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"null")


def execute_task(task: dict, studio_root: Path, artifacts: Path, cancel_check=None) -> dict:
    report = artifacts / f"{task['id']}.json"
    command = [
        os.environ.get("PYTHON", "python3"),
        "-m",
        "test_studio.cli",
        "run",
        task["flow_ref"],
        "--artifacts",
        str(artifacts / task["id"]),
        "--report",
        str(report),
    ]
    environment = os.environ.copy()
    source = studio_root / "src"
    environment["PYTHONPATH"] = f"{source}{os.pathsep}{environment.get('PYTHONPATH', '')}"
    process = subprocess.Popen(command, cwd=studio_root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    canceled = False
    while process.poll() is None:
        if cancel_check and cancel_check():
            canceled = True
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            break
        time.sleep(0.25)
    stdout, stderr = process.communicate()
    result = json.loads(report.read_text()) if report.exists() else {"stdout": stdout, "stderr": stderr}
    if canceled:
        result["canceled"] = True
    return {"passed": process.returncode == 0 and not canceled, "result": result, "canceled": canceled}


def execute_with_lease(client: PlatformClient, task: dict, device_id: str, studio_root: Path, artifacts: Path, lease_ms: int) -> dict:
    stopped = threading.Event()
    renewal_errors: list[str] = []

    def renew() -> None:
        interval = max(1.0, lease_ms / 3000)
        while not stopped.wait(interval):
            try:
                client.post(f"/api/v1/tasks/{task['id']}/renew", {"device_id": device_id, "lease_ms": lease_ms})
            except Exception as error:
                renewal_errors.append(f"{type(error).__name__}: {error}")

    thread = threading.Thread(target=renew, name=f"lease-{task['id']}", daemon=True)
    thread.start()
    try:
        def canceled() -> bool:
            try:
                return client.get(f"/api/v1/tasks/{task['id']}").get("status") == "canceled"
            except Exception:
                return False

        outcome = execute_task(task, studio_root, artifacts, canceled)
        if renewal_errors:
            outcome["result"]["lease_renewal_warnings"] = renewal_errors
        return outcome
    finally:
        stopped.set()
        thread.join(timeout=2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-url", default=os.environ.get("DEVICE_LAB_URL", "http://127.0.0.1:8877"))
    parser.add_argument("--token", default=os.environ.get("DEVICE_LAB_TOKEN", ""))
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--agent-id", default="local-agent")
    parser.add_argument("--platform", choices=("desktop", "android", "ios"), required=True)
    parser.add_argument("--capability", action="append", default=[])
    parser.add_argument("--studio-root", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--lease-ms", type=int, default=60_000)
    args = parser.parse_args()
    client = PlatformClient(args.platform_url, args.token)
    args.artifacts.mkdir(parents=True, exist_ok=True)
    while True:
        task = client.post(
            "/api/v1/tasks/claim/next",
            {
                "device_id": args.device_id,
                "agent_id": args.agent_id,
                "platform": args.platform,
                "capabilities": args.capability,
                "labels": {},
                "lease_ms": args.lease_ms,
            },
        )
        if task:
            outcome = execute_with_lease(client, task, args.device_id, args.studio_root, args.artifacts, args.lease_ms)
            if not outcome.pop("canceled", False):
                client.post(
                    f"/api/v1/tasks/{task['id']}/complete",
                    {"device_id": args.device_id, **outcome},
                )
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
