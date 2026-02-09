#!/usr/bin/env bash

set -euo pipefail

# Clone or update Decidero code and install Python dependencies.
# Run as root or a sudo-capable user on the VPS.

APP_USER="${DECIDERO_APP_USER:-decidero}"
BASE_DIR="${DECIDERO_BASE_DIR:-/opt/decidero}"
APP_DIR="${DECIDERO_APP_DIR:-${BASE_DIR}/app}"
VENV_DIR="${DECIDERO_VENV_DIR:-${BASE_DIR}/venv}"
BRANCH="${DECIDERO_GIT_BRANCH:-main}"

REPO_URL="${1:-${DECIDERO_REPO_URL:-}}"
if [[ -z "${REPO_URL}" ]]; then
  echo "Usage: bash scripts/vps/deploy_decidero.sh <git_repo_url>"
  echo "Or set DECIDERO_REPO_URL"
  exit 1
fi

if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  echo "App user '${APP_USER}' does not exist. Run bootstrap script first."
  exit 1
fi

mkdir -p "$(dirname "${APP_DIR}")"

if [[ -d "${APP_DIR}/.git" ]]; then
  echo "==> Updating existing repo in ${APP_DIR}"
  sudo -u "${APP_USER}" git -C "${APP_DIR}" fetch --all --prune
  sudo -u "${APP_USER}" git -C "${APP_DIR}" checkout "${BRANCH}"
  sudo -u "${APP_USER}" git -C "${APP_DIR}" pull --ff-only origin "${BRANCH}"
else
  echo "==> Cloning repo into ${APP_DIR}"
  sudo -u "${APP_USER}" git clone --branch "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
fi

echo "==> Creating virtual environment at ${VENV_DIR}"
sudo -u "${APP_USER}" python3 -m venv "${VENV_DIR}"
sudo -u "${APP_USER}" "${VENV_DIR}/bin/pip" install --upgrade pip

echo "==> Installing dependencies"
sudo -u "${APP_USER}" "${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "Deploy step complete."
