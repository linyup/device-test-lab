# Device Test Lab

A self-hosted test-device control plane for distributed desktop and mobile execution.

## Product capabilities

- Agent registration, capability discovery and heartbeats
- Device inventory, labels, groups and availability state
- Lease-based task scheduling with cancellation and timeout recovery
- Single flow, suite, batch, scheduled and webhook-triggered execution
- Android screen streaming and input; iOS WDA/MJPEG adapter
- Read-only observation while a task owns a device
- Artifact upload, unified reports, audit history and retention policies
- SQLite local mode plus replaceable persistence and object-storage adapters

## Services

```text
Vue web console
      |
Control API ---- scheduler ---- persistence port
      |                            |-- SQLite
      |                            |-- PostgreSQL/MySQL
      |                            `-- optional Java service
      |
WebSocket gateway
      |
Execution agents ---- desktop / Android / iOS devices
```

The open version will not depend on private build systems, databases or internal authentication. Authentication is an adapter with local development, OIDC and reverse-proxy modes.

## Operational design

- Task creation returns immediately with an immutable task identifier.
- Agents claim work through leases; expired leases are recoverable.
- Destructive operations use soft deletion and retention before purge.
- Large reports and videos are stored outside the relational database.
- UI mutations update local state immediately and reconcile in the background.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
device-lab-api
```

Open `http://127.0.0.1:8877`, create a desktop task, then start a local execution agent:

```bash
device-lab-agent \
  --device-id local-mac \
  --platform desktop \
  --studio-root ../cross-platform-test-studio
```

Set `DEVICE_LAB_TOKEN` on both the API and agent for bearer-token authentication. SQLite is the default; persistence is isolated behind the repository contract.
