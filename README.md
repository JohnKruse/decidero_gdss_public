# Decidero GDSS

<p align="center">
  <img src="app/static/assets/images/logo-360.png" alt="Decidero logo" width="240" />
</p>

Decidero GDSS is a group decision support system for facilitated meetings with activity-based workflows (brainstorming, voting, transfer/curation).

> [!IMPORTANT]
> **READ THESE RUNBOOKS BEFORE USING QUICK START FOR HOSTING/DEPLOYMENT.**
>
> Start here:
> 1. **Documentation index (all paths):** [`docs/INDEX.md`](docs/INDEX.md)
> 2. **Local setup runbook (lowest barrier):** [`docs/LOCAL_SETUP_GUIDE.md`](docs/LOCAL_SETUP_GUIDE.md)
> 3. **Admin hosting runbook:** [`docs/ADMIN_HOSTING_GUIDE.md`](docs/ADMIN_HOSTING_GUIDE.md)
> 4. **Server production runbook:** [`docs/SERVER_HOSTING_GUIDE.md`](docs/SERVER_HOSTING_GUIDE.md)
>
> `Quick Start (Local Host)` below is for local development, not production hosting.

## About
Decidero GDSS is maintained by John Kruse.

- Project repository: `https://github.com/JohnKruse/decidero_gdss_public`
- License: Apache License 2.0 (`LICENSE`)

## Capacity Expectations (SQLite, Single Node)

Use this project with conservative expectations on the default SQLite setup.

- Current conservative published target: up to ~50 concurrent participants.
- Above that, behavior can degrade during synchronized surges (for example,
  many users logging in or submitting at the same moment).
- For higher confidence, run the k6 scripts in this repo against your own
  deployment before a live event.
- Run realistic load tests with distinct participant accounts (not one shared
  login), or results can be artificially pessimistic.
- Roadmap goal: improve reliability to support ~100 concurrent participants.

Recommended server sizing for that target:

- Preferred: 3 vCPU / 4-8 GB RAM
- Minimum for smaller groups/pilots: 2 vCPU / 4 GB RAM

Related docs:

- `docs/SERVER_HOSTING_GUIDE.md`
- `docs/RELIABILITY_100_CONCURRENCY_PLAN.md`

## Fast Path (Stable Public URL)

### Actions

1. Pick a domain/subdomain for Decidero (example: `decidero.example.com`).
2. Point DNS `A` (and optional `AAAA`) record to your server IP.
3. Follow:
   - `docs/ADMIN_HOSTING_GUIDE.md`
   - `docs/SERVER_HOSTING_GUIDE.md`

### Verify

```bash
curl -I https://your-domain.example.com/health
```

> Explanation: For recurring or multi-day remote meetings, prefer a stable domain over temporary tunnel URLs.

## Quick Start (Local Host)
For the simplest local setup instructions, use `docs/LOCAL_SETUP_GUIDE.md`.

### Actions

1. Clone the repo and enter it:

```bash
git clone https://github.com/JohnKruse/decidero_gdss_public.git
cd decidero_gdss_public
```

2. Create and activate a virtual environment.
3. Install dependencies.
4. Copy env template.
5. Start local server.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./start_local.sh
```

### Verify

Open `http://localhost:8000`.

## Remote Participants (Easy HTTPS, No Domain Needed)
If participants are outside your LAN and you need a quick temporary URL, use a secure tunnel.

### Option A: One-command remote mode (recommended)

#### Actions

```bash
./start_remote_tunnel.sh
```

This starts the app and prints a public `https://<random>.trycloudflare.com` URL to share.

#### Verify

1. Open the printed tunnel URL in your browser.
2. Confirm `/health` and login both work before sharing.

> Explanation: The script auto-restarts `cloudflared` if it exits and writes logs to `logs/cloudflared.log`.
> Explanation: Tunnel URLs are ephemeral and can change on restart.

## Cookie Security Toggle

### Actions

When serving over HTTPS (tunnel or reverse proxy), enable secure cookies.

```bash
export DECIDERO_SECURE_COOKIES=true
```

Or set in `app/config/config.yaml`:

```yaml
auth:
  secure_cookies: true
```

### Verify

1. Sign in over HTTPS and confirm sessions persist.
2. For local HTTP development, keep secure cookies `false`.

## Host Checklist

### Actions

1. Same machine testing: run `./start_local.sh` and use `http://localhost:8000`.
2. Same LAN meeting: run `./start_local.sh`; if needed, bind app to LAN IP.
3. Remote meeting (temporary): run `./start_remote_tunnel.sh` and share the HTTPS tunnel URL.
4. Remote meeting (stable): use the domain/subdomain flow in `docs/SERVER_HOSTING_GUIDE.md`.
5. Keep `.env` private and never commit it.
6. For any internet-exposed usage, set:
   - `DECIDERO_ENV=production`
   - `DECIDERO_JWT_SECRET_KEY=<long-random-secret>`

## Remote Tunnel Reliability Knobs
`start_remote_tunnel.sh` supports environment overrides:

- `DECIDERO_TUNNEL_PROTOCOL` (`http2` default)
- `DECIDERO_TUNNEL_RETRY_MIN_SECONDS` (`3` default)
- `DECIDERO_TUNNEL_RETRY_MAX_SECONDS` (`15` default)
- `DECIDERO_TUNNEL_LOG_FILE` (`logs/cloudflared.log` default)
- `DECIDERO_TUNNEL_LOG_MAX_BYTES` (`5242880` default = 5 MB)
- `DECIDERO_TUNNEL_LOG_BACKUP_COUNT` (`5` default)

## Participant Instructions
- Open the host-shared meeting URL in a browser.
- Use your provided login credentials.
- No local installation is required.

## Developer Notes
- Activity contract guide (critical): `docs/ACTIVITY_CONTRACT_GUIDE.md`.
- Plugin guide: `docs/PLUGIN_DEV_GUIDE.md`.
- Categorization contract: `docs/CATEGORIZATION_CONTRACT.md`.
- Plugins are loaded from built-ins plus drop-ins at `./plugins` (or `DECIDERO_PLUGIN_DIR`).
- Reliability contract: all activity write operations must use shared frontend `runReliableWriteAction`; module catalog provides normalized `reliability_policy.write_default` baseline.
- Meeting UI applies adaptive refresh backoff + jitter during write bursts and transient overload (`429/502/503/504`) to prioritise user submissions over background polling.
- Activity outputs are snapshot bundles stored in the database.
