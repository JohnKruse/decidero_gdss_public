#!/bin/bash

set -euo pipefail

if [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

export DECIDERO_SECURE_COOKIES=false
export GRAB_ENABLED="${GRAB_ENABLED:-true}"

echo "Starting Decidero in local HTTP mode..."
echo "URL: http://127.0.0.1:8000"
echo "Secure cookies: ${DECIDERO_SECURE_COOKIES}"

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
