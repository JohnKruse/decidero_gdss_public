#!/usr/bin/env bash

set -euo pipefail

# Configure Caddy reverse proxy + TLS for Decidero.
# Run as root on the VPS.

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/vps/configure_caddy.sh <domain>"
  exit 1
fi

DOMAIN="${1:-${DECIDERO_DOMAIN:-}}"
if [[ -z "${DOMAIN}" ]]; then
  echo "Usage: bash scripts/vps/configure_caddy.sh <domain>"
  echo "Or set DECIDERO_DOMAIN"
  exit 1
fi

CADDYFILE="${DECIDERO_CADDYFILE:-/etc/caddy/Caddyfile}"
BLOCK_REGISTER="${DECIDERO_BLOCK_PUBLIC_REGISTER:-false}"

cat > "${CADDYFILE}" <<EOF
${DOMAIN} {
    encode gzip zstd
EOF

if [[ "${BLOCK_REGISTER}" == "true" ]]; then
  cat >> "${CADDYFILE}" <<'EOF'
    @block_register {
        path /register /api/auth/register
    }
    respond @block_register 403
EOF
fi

cat >> "${CADDYFILE}" <<'EOF'
    reverse_proxy 127.0.0.1:8000
}
EOF

echo "==> Validating and reloading Caddy"
caddy validate --config "${CADDYFILE}"
systemctl reload caddy
systemctl status caddy --no-pager

echo "Caddy configuration complete for ${DOMAIN}."
