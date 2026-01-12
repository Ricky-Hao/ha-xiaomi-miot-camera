#!/usr/bin/env bash
set -e

# Read options
CONFIG_PATH=/data/options.json
LOG_LEVEL=$(jq -r '.log_level // "info"' $CONFIG_PATH)

echo "Starting Xiaomi MIoT Camera Proxy..."
echo "Log level: ${LOG_LEVEL}"
echo ""
echo "Architecture: go2rtc-based WebRTC streaming"
echo "- RTSP streams: rtsp://<addon-host>:8554/camera/{did}/{channel}"
echo "- Configure HA go2rtc to use these RTSP streams"
echo ""

# Start mediamtx (RTSP server only) in background
echo "Starting RTSP server..."
/usr/local/bin/mediamtx /app/mediamtx.yml &
MEDIAMTX_PID=$!

# Wait for mediamtx to be ready
sleep 2

# Cleanup function
cleanup() {
    echo "Shutting down..."
    kill $MEDIAMTX_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# Start the proxy server
cd /app
exec python3 -m camera_proxy --log-level "${LOG_LEVEL}"
