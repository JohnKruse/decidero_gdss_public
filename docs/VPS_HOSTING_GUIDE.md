# Decidero VPS Hosting Guide

This guide is a production-oriented runbook for hosting Decidero on a Linux VPS with:

- `systemd` (process management)
- `uvicorn` (ASGI app server)
- `Caddy` (TLS + reverse proxy)
- SQLite (current default in this repo)

## Recommendation For This Codebase

Use a **single VPS instance** with **one uvicorn worker** behind Caddy.

Why this is the right default right now:

- Realtime meeting state is in-memory (`app/services/meeting_state.py`).
- WebSocket connection tracking is in-memory (`app/utils/websocket_manager.py`).
- SQLite is file-based and best for single-node deployments.

If you run multiple workers/processes, realtime state will split across processes and behavior can become inconsistent.

## Architecture

- Internet -> `:443` Caddy (TLS termination, reverse proxy)
- Caddy -> `127.0.0.1:8000` uvicorn app
- App data -> `decidero.db` (SQLite) + `logs/`

## 1. Provision VPS

Suggested baseline:

- Ubuntu 24.04 LTS
- 2 vCPU, 4 GB RAM
- 40+ GB SSD
- Static IP
- Domain pointed to VPS (`A` record)

## 2. Initial Server Hardening

SSH to VPS as a sudo-capable user and run:

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install python3 python3-venv python3-pip git caddy ufw sqlite3

# Optional but recommended
sudo timedatectl set-timezone UTC
```

Firewall:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

## 3. Create App User + Directories

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin decidero || true
sudo mkdir -p /opt/decidero
sudo chown -R decidero:decidero /opt/decidero
```

Deploy code:

```bash
sudo -u decidero git clone <YOUR_REPO_URL> /opt/decidero/app
cd /opt/decidero/app
```

## 4. Python Environment

```bash
sudo -u decidero python3 -m venv /opt/decidero/venv
sudo -u decidero /opt/decidero/venv/bin/pip install --upgrade pip
sudo -u decidero /opt/decidero/venv/bin/pip install -r /opt/decidero/app/requirements.txt
```

## 5. Runtime Environment File

This app reads environment variables directly. It does **not** auto-load `.env` by default in production startup, so use a systemd `EnvironmentFile`.

Create `/etc/decidero/decidero.env`:

```bash
sudo mkdir -p /etc/decidero
sudo chmod 750 /etc/decidero
sudo tee /etc/decidero/decidero.env >/dev/null <<'EOF'
DECIDERO_ENV=production
DECIDERO_JWT_SECRET_KEY=REPLACE_WITH_A_LONG_RANDOM_SECRET
DECIDERO_JWT_ISSUER=decidero
DECIDERO_SECURE_COOKIES=true
GRAB_ENABLED=false
LOG_LEVEL=INFO
LOG_MAX_BYTES=5242880
LOG_BACKUP_COUNT=5
EOF
sudo chown root:decidero /etc/decidero/decidero.env
sudo chmod 640 /etc/decidero/decidero.env
```

Generate a strong secret:

```bash
openssl rand -hex 48
```

Paste that value into `DECIDERO_JWT_SECRET_KEY`.

## 6. Create systemd Service

Create `/etc/systemd/system/decidero.service`:

```ini
[Unit]
Description=Decidero FastAPI Service
After=network.target

[Service]
Type=simple
User=decidero
Group=decidero
WorkingDirectory=/opt/decidero/app
EnvironmentFile=/etc/decidero/decidero.env
ExecStart=/opt/decidero/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now decidero
sudo systemctl status decidero --no-pager
```

Health check:

```bash
curl -sS http://127.0.0.1:8000/health
```

## 7. Configure Caddy (TLS + Reverse Proxy)

Create `/etc/caddy/Caddyfile`:

```caddy
your-domain.example.com {
    encode gzip zstd
    reverse_proxy 127.0.0.1:8000
}
```

Validate and reload:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
sudo systemctl status caddy --no-pager
```

Test:

```bash
curl -I https://your-domain.example.com/health
```

## 8. First Login / Admin Bootstrap

Important behavior in this codebase:

- The first account created via `/register` becomes `super_admin`.
- After that, new registrations become `participant`.

Recommended rollout:

1. Bring service online.
2. Immediately create the first admin account yourself.
3. Then decide whether to keep public registration open.

If you want to close public registration at proxy layer after bootstrap, add to Caddy:

```caddy
@block_register {
    path /register /api/auth/register
}
respond @block_register 403
```

Then reload Caddy.

## 9. Data and Backups (SQLite)

Current DB path from config: `sqlite:///./decidero.db` -> `/opt/decidero/app/decidero.db`.

On-demand backup:

```bash
sudo -u decidero sqlite3 /opt/decidero/app/decidero.db ".backup '/opt/decidero/app/backups/decidero-$(date +%F-%H%M%S).db'"
```

Create backup directory first:

```bash
sudo -u decidero mkdir -p /opt/decidero/app/backups
```

Automate with cron (example nightly 02:30):

```bash
sudo crontab -e
```

Add:

```cron
30 2 * * * sudo -u decidero sqlite3 /opt/decidero/app/decidero.db ".backup '/opt/decidero/app/backups/decidero-$(date +\%F-\%H\%M\%S).db'"
```

Restore (downtime required):

```bash
sudo systemctl stop decidero
sudo cp /opt/decidero/app/backups/<backup-file>.db /opt/decidero/app/decidero.db
sudo chown decidero:decidero /opt/decidero/app/decidero.db
sudo systemctl start decidero
```

## 10. Update Procedure

```bash
cd /opt/decidero/app
sudo -u decidero git pull
sudo -u decidero /opt/decidero/venv/bin/pip install -r requirements.txt
sudo systemctl restart decidero
sudo systemctl status decidero --no-pager
```

Smoke checks:

```bash
curl -sS https://your-domain.example.com/health
```

Then verify login, dashboard, meeting create/join, and realtime meeting updates in browser.

## 11. Logs and Troubleshooting

Systemd logs:

```bash
sudo journalctl -u decidero -f
```

App file logs:

- `/opt/decidero/app/logs/app.log`
- `/opt/decidero/app/logs/error.log`

Common issues:

- `Missing DECIDERO_JWT_SECRET_KEY while DECIDERO_ENV is set to production`:
  set `DECIDERO_JWT_SECRET_KEY` in `/etc/decidero/decidero.env`.
- Login cookie problems:
  ensure `DECIDERO_SECURE_COOKIES=true` and use HTTPS domain.
- 502 from Caddy:
  check `systemctl status decidero` and that app binds `127.0.0.1:8000`.

## 12. Known Limits and Next Upgrade Path

Current production limit:

- Single process/single node is the safe mode for realtime correctness.

When you outgrow this:

1. Move DB from SQLite to Postgres.
2. Move realtime state from in-memory to Redis/shared store.
3. Add multi-worker/process scaling.
4. Add managed backup/monitoring pipeline.

## 13. Keep This Guide "Living"

Add a short change note each time you adjust infra:

```md
## Change Log

- YYYY-MM-DD: Changed <what>, because <why>, rollback: <how>.
```

Use this checklist after each change:

1. `systemctl status decidero` is green.
2. `/health` is healthy through HTTPS.
3. Login works and cookie is set.
4. Realtime meeting updates still work.
5. Backup job still runs.
