#!/usr/bin/env bash
set -e

# Read options
CONFIG_PATH=/data/options.json
LOG_LEVEL=$(jq -r '.log_level // "info"' $CONFIG_PATH)

echo "Starting Xiaomi MIoT Camera Proxy..."
echo "Log level: ${LOG_LEVEL}"

# Start the proxy server
cd /app
exec python3 -m camera_proxy --log-level "${LOG_LEVEL}"
