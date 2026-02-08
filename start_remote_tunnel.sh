#!/bin/bash

set -euo pipefail

if [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is not installed."
  echo "Install on macOS: brew install cloudflared"
  exit 1
fi

export DECIDERO_SECURE_COOKIES=true
export GRAB_ENABLED="${GRAB_ENABLED:-true}"
TUNNEL_PROTOCOL="${DECIDERO_TUNNEL_PROTOCOL:-http2}"
RETRY_MIN_SECONDS="${DECIDERO_TUNNEL_RETRY_MIN_SECONDS:-3}"
RETRY_MAX_SECONDS="${DECIDERO_TUNNEL_RETRY_MAX_SECONDS:-15}"
TUNNEL_LOG_DIR="${DECIDERO_TUNNEL_LOG_DIR:-logs}"
TUNNEL_LOG_FILE="${DECIDERO_TUNNEL_LOG_FILE:-${TUNNEL_LOG_DIR}/cloudflared.log}"
TUNNEL_LOG_MAX_BYTES="${DECIDERO_TUNNEL_LOG_MAX_BYTES:-5242880}"
TUNNEL_LOG_BACKUP_COUNT="${DECIDERO_TUNNEL_LOG_BACKUP_COUNT:-5}"

mkdir -p "${TUNNEL_LOG_DIR}"

if ! [[ "${RETRY_MIN_SECONDS}" =~ ^[0-9]+$ ]] || ! [[ "${RETRY_MAX_SECONDS}" =~ ^[0-9]+$ ]]; then
  echo "Retry values must be integers."
  exit 1
fi
if [ "${RETRY_MIN_SECONDS}" -gt "${RETRY_MAX_SECONDS}" ]; then
  tmp="${RETRY_MIN_SECONDS}"
  RETRY_MIN_SECONDS="${RETRY_MAX_SECONDS}"
  RETRY_MAX_SECONDS="${tmp}"
fi

rotate_tunnel_logs() {
  if [ ! -f "${TUNNEL_LOG_FILE}" ]; then
    return
  fi

  local size
  size="$(stat -f%z "${TUNNEL_LOG_FILE}" 2>/dev/null || stat -c%s "${TUNNEL_LOG_FILE}" 2>/dev/null || wc -c < "${TUNNEL_LOG_FILE}")"
  if [ "${size}" -lt "${TUNNEL_LOG_MAX_BYTES}" ]; then
    return
  fi

  local i
  for ((i=TUNNEL_LOG_BACKUP_COUNT; i>=1; i--)); do
    if [ -f "${TUNNEL_LOG_FILE}.${i}" ]; then
      if [ "${i}" -eq "${TUNNEL_LOG_BACKUP_COUNT}" ]; then
        rm -f "${TUNNEL_LOG_FILE}.${i}"
      else
        mv "${TUNNEL_LOG_FILE}.${i}" "${TUNNEL_LOG_FILE}.$((i + 1))"
      fi
    fi
  done

  mv "${TUNNEL_LOG_FILE}" "${TUNNEL_LOG_FILE}.1"
}

random_retry_delay() {
  if [ "${RETRY_MAX_SECONDS}" -le "${RETRY_MIN_SECONDS}" ]; then
    echo "${RETRY_MIN_SECONDS}"
    return
  fi
  local span=$((RETRY_MAX_SECONDS - RETRY_MIN_SECONDS + 1))
  echo $((RETRY_MIN_SECONDS + RANDOM % span))
}

echo "Starting Decidero in remote mode (HTTPS via Cloudflare Tunnel)..."
echo "App bind: http://127.0.0.1:8000"
echo "Secure cookies: ${DECIDERO_SECURE_COOKIES}"
echo "Tunnel protocol: ${TUNNEL_PROTOCOL}"
echo "Tunnel logs: ${TUNNEL_LOG_FILE}"
echo
echo "Keep this terminal open during the meeting."
echo "Share the https://*.trycloudflare.com URL printed below."
echo

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 &
APP_PID=$!
CLEANED_UP=0

cleanup() {
  if [ "${CLEANED_UP}" -eq 1 ]; then
    return
  fi
  CLEANED_UP=1
  echo
  echo "Shutting down tunnel and app..."
  kill "${APP_PID}" >/dev/null 2>&1 || true
}

handle_interrupt() {
  cleanup
  exit 0
}

trap cleanup EXIT
trap handle_interrupt INT TERM

while true; do
  rotate_tunnel_logs
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Starting cloudflared tunnel..." | tee -a "${TUNNEL_LOG_FILE}"

  set +e
  cloudflared tunnel --protocol "${TUNNEL_PROTOCOL}" --url http://127.0.0.1:8000 2>&1 | tee -a "${TUNNEL_LOG_FILE}"
  tunnel_exit_code=${PIPESTATUS[0]}
  set -e

  if [ "${tunnel_exit_code}" -eq 0 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] cloudflared exited cleanly." | tee -a "${TUNNEL_LOG_FILE}"
    break
  fi

  if [ "${tunnel_exit_code}" -eq 130 ] || [ "${tunnel_exit_code}" -eq 143 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] cloudflared interrupted by signal." | tee -a "${TUNNEL_LOG_FILE}"
    break
  fi

  retry_delay="$(random_retry_delay)"
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] cloudflared exited with code ${tunnel_exit_code}; retrying in ${retry_delay}s." | tee -a "${TUNNEL_LOG_FILE}"
  sleep "${retry_delay}"
done
