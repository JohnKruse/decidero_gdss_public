#!/bin/bash

set -euo pipefail

echo "start_server.sh now maps to local mode."
echo "Use ./start_local.sh for local HTTP or ./start_remote_tunnel.sh for HTTPS tunnel mode."

exec ./start_local.sh
