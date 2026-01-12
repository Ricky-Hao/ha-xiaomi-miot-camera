#!/usr/bin/env bash
set -e

# Read options
CONFIG_PATH=/data/options.json
LOG_LEVEL=$(jq -r '.log_level // "info"' $CONFIG_PATH)
TRANSCODE_H264=$(jq -r '.transcode_h264 // true' $CONFIG_PATH)
VIDEO_QUALITY=$(jq -r '.video_quality // 3' $CONFIG_PATH)

echo "Starting Xiaomi MIoT Camera Proxy..."
echo "Log level: ${LOG_LEVEL}"
echo "Transcode H.265→H.264: ${TRANSCODE_H264}"
echo "Video quality: ${VIDEO_QUALITY} (1=LOW, 3=HIGH, 4/5=experimental)"
echo ""
echo "Architecture: Direct WebRTC streaming via MediaMTX"
echo "- WebRTC (WHEP): http://<addon-host>:8889/camera/{did}/{channel}/whep"
echo "- RTSP (internal): rtsp://localhost:8554/camera/{did}/{channel}"
echo ""

# Build transcode argument
TRANSCODE_ARG=""
if [ "$TRANSCODE_H264" = "true" ]; then
    TRANSCODE_ARG="--transcode-h264"
else
    TRANSCODE_ARG="--no-transcode-h264"
fi

# Cleanup function
cleanup() {
    echo "Shutting down..."
    kill $MEDIAMTX_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# Start mediamtx (RTSP + WebRTC server) in background
echo "Starting MediaMTX (RTSP + WebRTC server)..."
/usr/local/bin/mediamtx /app/mediamtx.yml 2>&1 &
MEDIAMTX_PID=$!

# Wait for MediaMTX to be ready (check RTSP port 8554)
echo "Waiting for MediaMTX to be ready..."
MAX_WAIT=30
WAITED=0
while ! nc -z localhost 8554 2>/dev/null; do
    sleep 1
    WAITED=$((WAITED + 1))
    if [ $WAITED -ge $MAX_WAIT ]; then
        echo "ERROR: MediaMTX failed to start within ${MAX_WAIT} seconds"
        echo "Checking if MediaMTX process is running..."
        if ! kill -0 $MEDIAMTX_PID 2>/dev/null; then
            echo "MediaMTX process died. Check configuration."
        fi
        exit 1
    fi
    echo "Waiting for MediaMTX... (${WAITED}s)"
done
echo "MediaMTX is ready (RTSP on 8554, WebRTC on 8889)"

# Start the proxy server
cd /app
exec python3 -m camera_proxy --log-level "${LOG_LEVEL}" ${TRANSCODE_ARG} --video-quality "${VIDEO_QUALITY}"
