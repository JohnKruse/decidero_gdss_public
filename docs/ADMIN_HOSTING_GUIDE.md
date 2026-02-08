# Decidero Admin Hosting Guide

This guide is for facilitators/admins who need to host meetings for participants.

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

```bash
./start_local.sh
```

Open: `http://localhost:8000`

## Mode B: LAN (same network)

Start server on the host machine:

```bash
source venv/bin/activate
DECIDERO_SECURE_COOKIES=false uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Participants join with: `http://<host-lan-ip>:8000`

Notes:
- Host LAN IP (macOS): `ipconfig getifaddr en0` (or `en1` depending on adapter).
- Keep host and participants on the same network.

## Mode C: Quick Tunnel (temporary remote HTTPS)

```bash
./start_remote_tunnel.sh
```

Share the generated `https://<random>.trycloudflare.com` URL.

Important:
- Keep terminal open while meeting runs.
- URL changes if tunnel restarts.
- Good for quick remote sessions, not ideal for multi-day critical meetings.
- Script behavior:
  - forces `DECIDERO_SECURE_COOKIES=true`
  - auto-restarts `cloudflared` if it exits unexpectedly
  - writes tunnel logs to `logs/cloudflared.log` with rotation (5 MB, 5 backups by default)

## Mode D: Production (recommended for long-running remote meetings)

Use a stable domain + reverse proxy + managed TLS.

Typical stack:
1. VPS/cloud host.
2. App bound to `127.0.0.1:8000`.
3. Caddy or Nginx in front on ports `80/443`.
4. Let's Encrypt certificate auto-renewal.
5. `DECIDERO_SECURE_COOKIES=true`.

## Security Settings

### Secure Cookies

- Use `DECIDERO_SECURE_COOKIES=true` when participants connect via HTTPS.
- Use `false` for plain HTTP local/LAN usage.

### JWT Secret

Always set a strong secret for any internet-exposed deployment:

```bash
export DECIDERO_JWT_SECRET_KEY="<long-random-secret>"
```

### Long Sessions

Long session timeout is configured in:

`app/config/config.yaml` -> `auth.access_token_expire_minutes`

This supports multi-day meetings but increases token exposure window if a token leaks.

## Troubleshooting

### I see many log lines saying "Invalid HTTP request received"

For public tunnel URLs, this is often internet scanner noise. Usually harmless.

### Tunnel works but login fails

1. Verify credentials work on `http://localhost:8000`.
2. Try private/incognito window (old cookies can cause JWT warnings).
3. Confirm host clock is correct (token expiry depends on time).

### Tunnel command says "Cannot determine default configuration path"

This is normal for quick tunnels without a local cloudflared config file.

### Tune tunnel reconnect behavior

Set these before running `./start_remote_tunnel.sh`:

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

## Participant Instructions (send this)

1. Open the meeting URL provided by the facilitator.
2. Log in with your credentials.
3. Keep using links within that same domain for the whole session.
