# Decidero Admin Hosting Guide

This guide is for facilitators/admins who need to host meetings for participants.

## Who Should Read This

- Facilitators running live workshops.
- Admins choosing between local, LAN, tunnel, and production hosting modes.
- Ops partners supporting facilitators during active sessions.

## Fast Path

If you need remote participants and a stable URL, use:

1. `docs/SERVER_HOSTING_GUIDE.md` to deploy on a server with a domain/subdomain.
2. `https://your-domain.example.com` for all facilitator/participant access.

> Explanation: Quick Tunnel is fine for short sessions, but production domain hosting is easier to repeat and support.

## Action-First Format

- `Actions` are the exact steps to run.
- `Verify` confirms each mode is working.
- `> Explanation:` callouts are context, not required commands.

## Hosting Modes

| Mode | Best for | Internet access | HTTPS | Reliability |
|---|---|---|---|---|
| Local | Practice/testing on one machine | No | No | High |
| LAN | Same office/network meetings | No (outside LAN) | Usually No | High |
| Quick Tunnel | Fast remote setup, temporary sessions | Yes | Yes | Medium |
| Production | Multi-day/global meetings | Yes | Yes | High |

## Pick the Right Mode

1. If everyone is on the same machine: use Local.
2. If everyone is on the same LAN: use LAN.
3. If people are remote and meeting is short/temporary: use Quick Tunnel.
4. If meetings are long-running or repeated with external participants: use Production.

## Mode A: Local (single machine)

### Actions

If local dependencies are not set up yet, run the local runbook first:

`docs/LOCAL_SETUP_GUIDE.md`

```bash
./start_local.sh
```

Open: `http://localhost:8000`

### Verify

1. Open `http://localhost:8000`.
2. Create/login with a test account.
3. Create and join a test meeting from another browser tab.

## Mode B: LAN (same network)

### Actions

Start server on the host machine:

```bash
source venv/bin/activate
DECIDERO_SECURE_COOKIES=false uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Participants join with: `http://<host-lan-ip>:8000`

### Verify

1. From another device on the same LAN, open `http://<host-lan-ip>:8000`.
2. Confirm login and meeting join work.

> Explanation:

- Host LAN IP (macOS): `ipconfig getifaddr en0` (or `en1` depending on adapter).
- Keep host and participants on the same network.

## Mode C: Quick Tunnel (temporary remote HTTPS)

### Actions

```bash
./start_remote_tunnel.sh
```

Share the generated `https://<random>.trycloudflare.com` URL.

### Verify

1. Open the printed tunnel URL yourself and confirm login works.
2. Have one facilitator test sign-in before sharing broadly.

> Explanation: Important operating notes.

- Keep terminal open while meeting runs.
- URL changes if tunnel restarts.
- Browser-saved credentials are often domain-specific. A new `trycloudflare.com` URL can make saved logins appear "missing."
- Require all admins/facilitators/participants to record passwords in a password manager entry not tied only to the previous tunnel URL.
- After any tunnel restart, send the new URL to everyone and have users verify they can still sign in before the session starts.
- Good for quick remote sessions, not ideal for multi-day critical meetings.
- Script behavior:
  - forces `DECIDERO_SECURE_COOKIES=true`
  - auto-restarts `cloudflared` if it exits unexpectedly
  - writes tunnel logs to `logs/cloudflared.log` with rotation (5 MB, 5 backups by default)

## Mode D: Production (recommended for long-running remote meetings)

### Actions

Use a stable domain + reverse proxy + managed TLS:

1. Complete `docs/SERVER_HOSTING_GUIDE.md`.
2. Share one stable URL (for example `https://decidero.example.com`).
3. Keep all users on that same domain for the full session.

### Verify

```bash
curl -I https://your-domain.example.com/health
```

> Explanation: Typical stack.

1. VPS/cloud host.
2. App bound to `127.0.0.1:8000`.
3. Caddy or Nginx in front on ports `80/443`.
4. Let's Encrypt certificate auto-renewal.
5. `DECIDERO_SECURE_COOKIES=true`.

## Security Settings

### Secure Cookies

#### Actions

- Use `DECIDERO_SECURE_COOKIES=true` when participants connect via HTTPS.
- Use `false` for plain HTTP local/LAN usage.

#### Verify

1. On HTTPS deployments, confirm the setting is `true` in environment config.
2. Confirm logins still work over HTTPS.

### JWT Secret

Always set a strong secret for any internet-exposed deployment:

#### Actions

```bash
export DECIDERO_ENV=production
export DECIDERO_JWT_SECRET_KEY="<long-random-secret>"
```

#### Verify

1. Restart app/service.
2. Confirm startup succeeds and no missing secret error appears.

> Explanation:

When `DECIDERO_ENV=production`, app startup now fails fast if `DECIDERO_JWT_SECRET_KEY` is missing.

### Long Sessions

Long session timeout is configured in:

`app/config/config.yaml` -> `auth.access_token_expire_minutes`

#### Actions

1. Set `auth.access_token_expire_minutes` to your workshop duration needs.
2. Restart the app after changing config.

#### Verify

1. Confirm users remain signed in for the intended window.
2. Confirm tokens still expire as expected.

> Explanation:

This supports multi-day meetings but increases token exposure window if a token leaks.

## Troubleshooting

### I see many log lines saying "Invalid HTTP request received"

> Explanation:

For public tunnel URLs, this is often internet scanner noise. Usually harmless.

### Tunnel works but login fails

#### Actions

1. Verify credentials work on `http://localhost:8000`.
2. Try private/incognito window (old cookies can cause JWT warnings).
3. Confirm host clock is correct (token expiry depends on time).
4. Confirm users are on the current tunnel URL. `trycloudflare.com` URLs change on restart.
5. If password manager autofill disappeared after URL rotation, manually enter credentials or use the correct stored password entry.

### Admin password is lost after URL/domain change

> Explanation: This is usually a browser/password-manager lookup issue caused by domain change, not a database wipe.

#### Actions

1. First test admin credentials locally on the server host (`http://localhost:8000`).
2. If still locked out, reset from server-side access and immediately set a strong replacement password.
3. Re-share the current URL and have admins sign in once to re-save credentials for the new domain.

### Tunnel command says "Cannot determine default configuration path"

> Explanation:

This is normal for quick tunnels without a local cloudflared config file.

### Tune tunnel reconnect behavior

Set these before running `./start_remote_tunnel.sh`:

#### Actions

```bash
export DECIDERO_TUNNEL_PROTOCOL=http2
export DECIDERO_TUNNEL_RETRY_MIN_SECONDS=3
export DECIDERO_TUNNEL_RETRY_MAX_SECONDS=15
```

You can also tune log file behavior:

```bash
export DECIDERO_TUNNEL_LOG_FILE=logs/cloudflared.log
export DECIDERO_TUNNEL_LOG_MAX_BYTES=5242880
export DECIDERO_TUNNEL_LOG_BACKUP_COUNT=5
```

#### Verify

1. Restart `./start_remote_tunnel.sh`.
2. Confirm reconnect behavior and log rotation match your settings.

## Participant Instructions (send this)

#### Actions

1. Open the meeting URL provided by the facilitator.
2. Log in with your credentials.
3. Keep using links within that same domain for the whole session.
