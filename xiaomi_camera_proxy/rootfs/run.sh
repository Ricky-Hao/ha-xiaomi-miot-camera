#!/usr/bin/env bash
set -e

# Read options
CONFIG_PATH=/data/options.json
LOG_LEVEL=$(jq -r '.log_level // "info"' $CONFIG_PATH)
TRANSCODE_H264=$(jq -r '.transcode_h264 // true' $CONFIG_PATH)

echo "Starting Xiaomi MIoT Camera Proxy..."
echo "Log level: ${LOG_LEVEL}"
echo "Transcode H.265→H.264: ${TRANSCODE_H264}"
echo ""
echo "Architecture: go2rtc-based WebRTC streaming"
echo "- RTSP streams: rtsp://<addon-host>:8554/camera/{did}/{channel}"
echo "- Configure HA go2rtc to use these RTSP streams"
echo ""

# Build transcode argument
TRANSCODE_ARG=""
if [ "$TRANSCODE_H264" = "true" ]; then
    TRANSCODE_ARG="--transcode-h264"
else
    TRANSCODE_ARG="--no-transcode-h264"
fi

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
exec python3 -m camera_proxy --log-level "${LOG_LEVEL}" ${TRANSCODE_ARG}
