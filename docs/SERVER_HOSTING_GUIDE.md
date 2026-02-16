# Decidero Server Hosting Guide

This guide is a production-oriented runbook for hosting Decidero on a single-node Linux server with:

- `systemd` (process management)
- `uvicorn` (ASGI app server)
- `Caddy` (TLS + reverse proxy)
- SQLite (current default in this repo)

## Who Should Read This

- Engineers responsible for deploying and operating Decidero on a server.
- Admins setting up a stable domain/subdomain for recurring remote sessions.
- Maintainers handling backups, updates, and production incident response.

## Fast Path (Domain/Subdomain + HTTPS)

If you just want the shortest path to a stable URL, follow this chain first:

1. Pick a host name for Decidero, usually a subdomain like `decidero.example.com`.
2. In your DNS provider, add:
   - `A` record: `decidero` -> `<your server public IPv4>`
   - `AAAA` record: `decidero` -> `<your server public IPv6>` (only if your server has IPv6)
3. Wait for DNS to resolve:
   - `dig +short decidero.example.com`
4. On the server, run setup scripts in order:
   - `sudo bash scripts/vps/bootstrap_ubuntu.sh`
   - `sudo bash scripts/vps/deploy_decidero.sh <YOUR_REPO_URL>`
   - `sudo DECIDERO_JWT_SECRET_KEY='<strong_secret>' bash scripts/vps/configure_systemd.sh`
   - `sudo bash scripts/vps/configure_caddy.sh decidero.example.com`
5. Verify:
   - `curl -I https://decidero.example.com/health`

> Explanation: Keep your existing `@` and `www` records unchanged if they already serve another site (for example Blogger/WordPress). Add a new subdomain record for Decidero instead.

## Action-First Format

- Lines under each step are actions to perform.
- `> Explanation:` callouts are context, not required commands.

## Recommendation For This Codebase

Use a **single Linux host** with **one uvicorn worker** behind Caddy.

> Explanation: This is the safest default for the current architecture.

- Realtime meeting state is in-memory (`app/services/meeting_state.py`).
- WebSocket connection tracking is in-memory (`app/utils/websocket_manager.py`).
- SQLite is file-based and best for single-node deployments.

If you run multiple workers/processes, realtime state will split across processes and behavior can become inconsistent.

> Explanation: Practical impact.

- This is a reliability-first choice, not a maximum-throughput choice.
- You can still serve normal workshop traffic on one mid-size server.
- If you need horizontal scale later, the architecture needs shared state (Redis/Postgres), not just bigger worker counts.

## Architecture

- Internet -> `:443` Caddy (TLS termination, reverse proxy)
- Caddy -> `127.0.0.1:8000` uvicorn app
- App data -> `decidero.db` (SQLite) + `logs/`

## Scripted Setup Option

If you prefer automation over manual commands, use:

- `scripts/vps/README.md`
- `scripts/vps/bootstrap_ubuntu.sh`
- `scripts/vps/deploy_decidero.sh`
- `scripts/vps/configure_systemd.sh`
- `scripts/vps/configure_caddy.sh`
- `scripts/vps/install_backup_cron.sh`

These scripts implement the same flow as this guide, but in repeatable steps.

## 1. Provision Server

### Actions

Use this baseline:

- Ubuntu 24.04 LTS
- 2 vCPU, 4 GB RAM
- 40+ GB SSD
- Static IP
- Domain pointed to server IP (`A` record)

### 1.1 DNS Domain/Subdomain Setup (for stable URL)

1. Choose a public host name (recommended: subdomain), for example:
   - `decidero.example.com`
2. In your DNS control panel, add:
   - `A` record for `decidero` -> your server public IPv4
   - `AAAA` record for `decidero` -> your server public IPv6 (if used)
3. Confirm DNS:

```bash
dig +short decidero.example.com
```

> Explanation: Do not repoint your existing `www` record unless you want Decidero to replace that site. Most setups keep `www` for the current website and use a dedicated subdomain for Decidero.

## 2. Initial Server Hardening

### Actions

SSH to the server as a sudo-capable user and run:

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install python3 python3-venv python3-pip git caddy ufw sqlite3

# Optional but recommended
sudo timedatectl set-timezone UTC
```

> Explanation:

- `ufw`: default-deny host firewall so only intended ports are reachable.
- `80/443`: required for HTTP->HTTPS and TLS traffic.
- `OpenSSH`: keeps remote admin access available.
- UTC timezone: avoids confusion when correlating auth/session/log timestamps.

Simple firewall mode (recommended for this runbook): configure firewall on-server with `ufw` only.

Firewall:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

### Verify

```bash
sudo ufw status
```

If your cloud provider firewall is already set up, you can keep it, but this guide does not require it.

> Explanation: Risks of skipping firewall setup entirely.

- Not always an immediate outage risk, but it increases blast radius if any service accidentally binds publicly.
- Cloud/provider firewalls can help, but host firewall is usually simpler to keep in sync with this guide.
- In practice, skipping this is a common reason internal-only services become internet-exposed.

## 3. Create App User + Directories

### Actions

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin decidero || true
sudo mkdir -p /opt/decidero
sudo chown -R decidero:decidero /opt/decidero
```

> Explanation:

- Limits damage if the app process is compromised.
- Keeps ownership boundaries clean between app files and system files.
- Makes audits and incident response simpler (`decidero` owns app runtime artifacts).

If you run as `root`, a code or dependency exploit has full-system write access.

Deploy code:

```bash
# Public repo (direct copy/paste)
sudo -u decidero git clone https://github.com/JohnKruse/decidero_gdss_public.git /opt/decidero/app
cd /opt/decidero/app
```

If you are deploying a fork or private copy instead, replace the URL with your repo:

```bash
sudo -u decidero git clone <YOUR_REPO_URL> /opt/decidero/app
```

### Verify

```bash
ls -ld /opt/decidero /opt/decidero/app
```

## 4. Python Environment

### Actions

```bash
sudo -u decidero python3 -m venv /opt/decidero/venv
sudo -u decidero /opt/decidero/venv/bin/pip install --upgrade pip
sudo -u decidero /opt/decidero/venv/bin/pip install -r /opt/decidero/app/requirements.txt
```

Note: this installs code + dependencies only. The app is started in Step 6 when `systemd` is enabled.

### Verify

```bash
sudo -u decidero /opt/decidero/venv/bin/python -V
```

## 5. Runtime Environment File

This app reads environment variables directly. It does **not** auto-load `.env` by default in production startup, so use a systemd `EnvironmentFile`.

### Actions

Create `/etc/decidero/decidero.env`:

```bash
sudo mkdir -p /etc/decidero
sudo chmod 750 /etc/decidero
DECIDERO_JWT_SECRET_KEY="$(openssl rand -hex 48)"
sudo tee /etc/decidero/decidero.env >/dev/null <<EOF
DECIDERO_ENV=production
DECIDERO_JWT_SECRET_KEY=${DECIDERO_JWT_SECRET_KEY}
DECIDERO_JWT_ISSUER=decidero
DECIDERO_SECURE_COOKIES=true
GRAB_ENABLED=false
LOG_LEVEL=INFO
LOG_MAX_BYTES=5242880
LOG_BACKUP_COUNT=5
EOF
sudo chown root:decidero /etc/decidero/decidero.env
sudo chmod 640 /etc/decidero/decidero.env
echo "Generated JWT secret length: ${#DECIDERO_JWT_SECRET_KEY}"
```

> Explanation:

- `DECIDERO_ENV=production` enforces stronger startup behavior (missing JWT secret fails fast).
- `DECIDERO_JWT_SECRET_KEY` signs auth tokens; weak or rotating secrets will break sessions and can weaken security.
- `DECIDERO_SECURE_COOKIES=true` ensures auth cookies are only sent over HTTPS.

If you skip this and rely on ad-hoc shell exports, reboot/restart drift is very likely.

Generate a strong secret manually (optional):

```bash
openssl rand -hex 48
```

The main command block above already generates and writes this for you.

### Verify

```bash
sudo ls -l /etc/decidero/decidero.env
sudo grep -E '^DECIDERO_ENV=|^DECIDERO_SECURE_COOKIES=' /etc/decidero/decidero.env
```

## 6. Create systemd Service

### Actions

Create `/etc/systemd/system/decidero.service`:

```bash
sudo tee /etc/systemd/system/decidero.service >/dev/null <<'EOF'
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
EOF
```

> Explanation:

- Auto-restart on crash.
- Starts on boot.
- Centralized logs with `journalctl`.
- Stable, repeatable runtime config.

If you skip `systemd`, the app will eventually stop after disconnects/reboots and require manual recovery.

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now decidero
sudo systemctl status decidero --no-pager
```

### Verify

Health check:

```bash
curl -sS http://127.0.0.1:8000/health
```

After any later code update (`git pull` / `deploy_decidero.sh`), restart the service:

```bash
sudo systemctl restart decidero
sudo systemctl status decidero --no-pager
curl -sS http://127.0.0.1:8000/health
```

## 7. Publish Access (Choose One Track)

### Track A (Simple/Temporary, No Domain): Cloudflare Quick Tunnel

Use this for short workshops (1-3 days) when you do not have a domain.

#### Actions

Install `cloudflared`:

```bash
curl -L --fail --output /tmp/cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i /tmp/cloudflared.deb || sudo apt-get -f install -y
cloudflared --version
```

Start tunnel:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

Copy/share the printed `https://*.trycloudflare.com` URL.

#### Verify

```bash
curl -sS https://<your-random>.trycloudflare.com/health
```

> Explanation: Important operating notes for Quick Tunnel.

- `trycloudflare.com` URLs are ephemeral and usually change when `cloudflared` restarts.
- Browser-saved credentials are domain-scoped, so users may think passwords are "gone" when the URL changes.
- Require admins/facilitators/participants to record passwords in a retrievable password manager entry before sessions.
- After tunnel restart, distribute the new URL and run a quick sign-in check with facilitators/admins before participants join.

Example output (copy the URL on the line with `https://...trycloudflare.com`):

```text
2026-02-09T14:34:49Z INF Requesting new quick Tunnel on trycloudflare.com...
2026-02-09T14:34:53Z INF +--------------------------------------------------------------------------------------------+
2026-02-09T14:34:53Z INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
2026-02-09T14:34:53Z INF |  https://colours-mercy-sections-analysts.trycloudflare.com                                 |
2026-02-09T14:34:53Z INF +--------------------------------------------------------------------------------------------+
```

Notes:

- Keep this terminal open; if `cloudflared` stops, the public URL stops.
- Warnings about missing `config.yml` are expected for quick tunnels.
- This is best for temporary/demo usage, not long-term production.

### Track B (Production, Domain): Caddy TLS Reverse Proxy

#### Actions

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

#### Verify

```bash
curl -I https://your-domain.example.com/health
```

> Explanation:

- Automatic certificate issuance/renewal.
- Clean HTTPS defaults with minimal config.
- Keeps app bound privately on `127.0.0.1`.

> Explanation: Could you expose uvicorn directly on `0.0.0.0:8000`?

- Yes, but then you lose managed TLS, cookie/security expectations, and reverse-proxy controls.
- For this app, HTTPS is not optional in production because auth cookies should be `Secure`.

## 8. First Login / Admin Bootstrap

Important behavior in this codebase:

- The first account created via `/register` becomes `super_admin`.
- After that, new registrations become `participant`.

Recommended rollout:

1. Bring service online.
2. Immediately create the first admin account yourself.
3. Then decide whether to keep public registration open.

### Actions

1. Open `https://your-domain.example.com/register`.
2. Create the first account yourself (this becomes `super_admin`).
3. Decide whether to keep `/register` open.
4. If closing registration, add the Caddy block below and reload Caddy.

If you want to close public registration at proxy layer after bootstrap, add to Caddy:

```caddy
@block_register {
    path /register /api/auth/register
}
respond @block_register 403
```

Then reload Caddy.

### Verify

1. Sign out and sign back in with the new admin account.
2. Open `/register`:
   - If blocked, expect HTTP `403`.
   - If left open, participant signup should still work.

> Explanation:

- Public registration stays available unless you explicitly close it.
- After first admin creation, open registration still allows anyone to self-register as participant.
- That may be acceptable for open communities, but not for private/client workshops.

## 9. Data and Backups (SQLite)

Current DB path from config: `sqlite:///./decidero.db` -> `/opt/decidero/app/decidero.db`.

### Actions

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

### Verify

```bash
ls -1 /opt/decidero/app/backups | tail
```

> Explanation: Is backup required on a single server?

- Yes. SQLite is a single file; accidental deletion, disk corruption, or operator error can wipe state instantly.
- VM/cloud snapshots are helpful but usually slower for granular restore than a direct `.backup` file.
- A nightly backup is the minimum baseline; add off-host copy when possible.

## 10. Update Procedure

### Actions

```bash
cd /opt/decidero/app
sudo -u decidero git pull
sudo -u decidero /opt/decidero/venv/bin/pip install -r requirements.txt
sudo systemctl restart decidero
sudo systemctl status decidero --no-pager
```

Smoke checks:

```bash
# Domain (Track B)
curl -sS https://your-domain.example.com/health

# Quick tunnel (Track A)
curl -sS https://<your-random>.trycloudflare.com/health
```

Then verify login, dashboard, meeting create/join, and realtime meeting updates in browser.

### Verify

1. `sudo systemctl status decidero --no-pager` is green.
2. `/health` is healthy on the active public URL.

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
- Users report missing saved passwords after Quick Tunnel restart:
  confirm they are on the current `trycloudflare.com` URL; browser autofill may not appear across domain changes, so users must enter recorded credentials manually.
- Admin login unavailable after domain/tunnel change:
  this is usually password-manager lookup behavior, not data loss; validate locally first, then perform server-side credential reset only if credentials are truly unknown.
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

Trigger signals that you are outgrowing this setup:

- Realtime behavior becomes inconsistent when testing multiple workers.
- You need zero-downtime deploys and parallel app instances.
- Concurrent write load causes frequent SQLite lock contention.
- You need stronger RPO/RTO guarantees than local-file backups provide.

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
