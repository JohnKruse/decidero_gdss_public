#!/usr/bin/env bash

set -euo pipefail

# Create /etc/decidero/decidero.env and /etc/systemd/system/decidero.service.
# Run as root on the VPS.

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/vps/configure_systemd.sh"
  exit 1
fi

APP_USER="${DECIDERO_APP_USER:-decidero}"
BASE_DIR="${DECIDERO_BASE_DIR:-/opt/decidero}"
APP_DIR="${DECIDERO_APP_DIR:-${BASE_DIR}/app}"
VENV_DIR="${DECIDERO_VENV_DIR:-${BASE_DIR}/venv}"
ENV_DIR="${DECIDERO_ENV_DIR:-/etc/decidero}"
ENV_FILE="${DECIDERO_ENV_FILE:-${ENV_DIR}/decidero.env}"
SERVICE_FILE="${DECIDERO_SERVICE_FILE:-/etc/systemd/system/decidero.service}"

JWT_SECRET="${DECIDERO_JWT_SECRET_KEY:-}"
if [[ -z "${JWT_SECRET}" ]]; then
  JWT_SECRET="$(openssl rand -hex 48)"
  echo "Generated DECIDERO_JWT_SECRET_KEY for ${ENV_FILE}"
fi

mkdir -p "${ENV_DIR}"
cat > "${ENV_FILE}" <<EOF
DECIDERO_ENV=production
DECIDERO_JWT_SECRET_KEY=${JWT_SECRET}
DECIDERO_JWT_ISSUER=decidero
DECIDERO_SECURE_COOKIES=true
GRAB_ENABLED=false
LOG_LEVEL=INFO
LOG_MAX_BYTES=5242880
LOG_BACKUP_COUNT=5
EOF
chown root:"${APP_USER}" "${ENV_FILE}" || true
chmod 640 "${ENV_FILE}"

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Decidero FastAPI Service
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

echo "==> Reloading and enabling service"
systemctl daemon-reload
systemctl enable --now decidero
systemctl status decidero --no-pager

echo "Systemd configuration complete."
