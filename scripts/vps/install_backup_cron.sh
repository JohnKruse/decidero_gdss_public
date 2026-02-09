#!/usr/bin/env bash

set -euo pipefail

# Install a nightly SQLite backup cron entry for Decidero.
# Run as root on the VPS.

APP_USER="${DECIDERO_APP_USER:-decidero}"
BASE_DIR="${DECIDERO_BASE_DIR:-/opt/decidero}"
APP_DIR="${DECIDERO_APP_DIR:-${BASE_DIR}/app}"
BACKUP_DIR="${DECIDERO_BACKUP_DIR:-${APP_DIR}/backups}"
DB_PATH="${DECIDERO_DB_PATH:-${APP_DIR}/decidero.db}"
CRON_SCHEDULE="${DECIDERO_BACKUP_CRON:-30 2 * * *}"

mkdir -p "${BACKUP_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${BACKUP_DIR}"

CRON_CMD="sudo -u ${APP_USER} sqlite3 ${DB_PATH} \".backup '${BACKUP_DIR}/decidero-\$(date +\\%F-\\%H\\%M\\%S).db'\""
ENTRY="${CRON_SCHEDULE} ${CRON_CMD}"

TMP_FILE="$(mktemp)"
trap 'rm -f "${TMP_FILE}"' EXIT

if crontab -l >/dev/null 2>&1; then
  crontab -l | grep -v "sqlite3 ${DB_PATH}" > "${TMP_FILE}" || true
fi

echo "${ENTRY}" >> "${TMP_FILE}"
crontab "${TMP_FILE}"

echo "Installed backup cron entry:"
echo "${ENTRY}"
