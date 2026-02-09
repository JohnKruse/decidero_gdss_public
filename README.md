# Decidero GDSS

<p align="center">
  <img src="app/static/assets/images/logo-360.png" alt="Decidero logo" width="240" />
</p>

Decidero GDSS is a group decision support system for facilitated meetings with activity-based workflows (brainstorming, voting, transfer/curation).

> [!IMPORTANT]
> **READ THESE RUNBOOKS BEFORE USING QUICK START FOR HOSTING/DEPLOYMENT.**
>
> Start here:
> 1. **Admin hosting runbook:** [`docs/ADMIN_HOSTING_GUIDE.md`](docs/ADMIN_HOSTING_GUIDE.md)
> 2. **Server production runbook:** [`docs/SERVER_HOSTING_GUIDE.md`](docs/SERVER_HOSTING_GUIDE.md)
>
> `Quick Start (Local Host)` below is for local development, not production hosting.

## About
Decidero GDSS is maintained by John Kruse.

- Project repository: `https://github.com/JohnKruse/decidero_gdss_public`
- License: Apache License 2.0 (`LICENSE`)

## Quick Start (Local Host)
1. Create and activate a virtual environment.
2. Install dependencies.
3. Copy env template.
4. Start local server.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./start_local.sh
```

Open `http://localhost:8000`.

## Remote Participants (Easy HTTPS, No Domain Needed)
If participants are outside your LAN, use a secure tunnel. This gives you an `https://...` URL without managing certificates.

### Option A: One-command remote mode (recommended)
Run:

```bash
./start_remote_tunnel.sh
```

This starts the app and prints a public `https://<random>.trycloudflare.com` URL to share.
It also auto-restarts `cloudflared` if the tunnel process exits and writes tunnel logs to `logs/cloudflared.log`.

## Cookie Security Toggle
When serving over HTTPS (tunnel or reverse proxy), enable secure cookies:

```bash
export DECIDERO_SECURE_COOKIES=true
```

Or set in `app/config/config.yaml`:

```yaml
auth:
  secure_cookies: true
```

For plain local HTTP development, keep it `false`.

## Host Checklist
- Same machine testing: run `./start_local.sh` and use `http://localhost:8000`.
- Same LAN meeting: run `./start_local.sh`; if needed, bind app to LAN IP.
- Remote meeting: run `./start_remote_tunnel.sh` and share the HTTPS tunnel URL.
- Keep `.env` private and never commit it.
- For any internet-exposed usage, set:
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
- Plugin guide: `docs/PLUGIN_DEV_GUIDE.md`.
- Plugins are loaded from built-ins plus drop-ins at `./plugins` (or `DECIDERO_PLUGIN_DIR`).
- Activity outputs are snapshot bundles stored in the database.
