# Deployment

## Local Docker

From the portfolio root:

```bash
cp .env.example .env
docker compose up --build
```

Open `http://127.0.0.1:8877`. The API schema is available at `/docs`.

## Production baseline

- Terminate TLS at a reverse proxy.
- Set a strong `DEVICE_LAB_TOKEN`, or replace bearer authentication with OIDC.
- Mount `/data` on durable encrypted storage.
- Store large artifacts in object storage rather than SQLite.
- Run agents on trusted execution machines with least-privilege device access.
- Do not expose ADB, WDA or agent control ports to the public network.

