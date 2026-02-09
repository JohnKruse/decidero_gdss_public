#!/usr/bin/env bash

set -euo pipefail

# Bootstrap base VPS dependencies and host hardening primitives for Decidero.
# Run as root on Ubuntu/Debian.

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/vps/bootstrap_ubuntu.sh"
  exit 1
fi

APP_USER="${DECIDERO_APP_USER:-decidero}"
BASE_DIR="${DECIDERO_BASE_DIR:-/opt/decidero}"
TIMEZONE="${DECIDERO_TIMEZONE:-UTC}"
ENABLE_UFW="${DECIDERO_ENABLE_UFW:-true}"

echo "==> Updating packages"
apt update
apt -y upgrade

echo "==> Installing required packages"
apt -y install python3 python3-venv python3-pip git caddy ufw sqlite3 openssl curl

echo "==> Setting timezone to ${TIMEZONE}"
timedatectl set-timezone "${TIMEZONE}" || true

echo "==> Creating app user and directories"
if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "${APP_USER}"
fi
mkdir -p "${BASE_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${BASE_DIR}"

if [[ "${ENABLE_UFW}" == "true" ]]; then
  echo "==> Configuring firewall (ufw)"
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
  ufw status verbose
else
  echo "==> Skipping ufw configuration (DECIDERO_ENABLE_UFW=${ENABLE_UFW})"
fi

echo "Bootstrap complete."
