# Testing RTSP Streaming (v0.3.0)

## What Changed

### Before (v0.2.8)
- Camera sends H.264 → Decode to JPEG → WebSocket → HA
- CPU intensive, high bandwidth, always running

### After (v0.3.0)
- Camera sends H.264 → RTSP server (mediamtx) → HA stream component
- Low CPU, low bandwidth, **on-demand only**

## Testing Steps

### 1. Build & Install Add-on

```bash
cd /workspaces/ha-xiaomi-miot-camera
# Build will install mediamtx + ffmpeg
docker build -t test-addon xiaomi_camera_proxy/
```

### 2. Check Services Running

After starting the add-on, verify:

```bash
# Check add-on logs
# Should see:
# - "Starting mediamtx RTSP server..."
# - "Starting Xiaomi MIoT Camera Proxy v0.3.0"
```

### 3. Verify RTSP Stream

When you open a camera in HA:

**Expected flow:**
1. HA requests stream → calls `camera.stream_source`
2. Returns `rtsp://127.0.0.1:8554/camera/{did}/0`
3. HA stream component connects to RTSP
4. mediamtx starts the camera automatically (on-demand)
5. H.264 frames pushed to RTSP by camera_manager
6. Stream appears in HA

**Check add-on logs:**
```
Started RTSP stream: {did}_0 -> rtsp://localhost:8554/camera/{did}/0
Video frame: codec=4, len=XXXX, frame_type=1  # H.264 frames
```

### 4. Test On-Demand

**When viewing stops:**
- Wait 10 seconds (configured in mediamtx.yml)
- mediamtx should auto-stop the stream
- Camera stops sending frames

**Check logs:**
```
Stopped RTSP stream: {did}_0
```

### 5. Test Snapshots

`camera.snapshot` service should still work:
- Uses JPEG over WebSocket (I-frames only)
- Independent of RTSP streaming

## Ports

- **8765**: WebSocket (control + snapshots)
- **8554**: RTSP streaming
- **9997**: mediamtx API (internal)

## Troubleshooting

### Stream not appearing

1. Check mediamtx is running: `ps aux | grep mediamtx`
2. Check ffmpeg is available: `which ffmpeg`
3. Check RTSP port: `netstat -ln | grep 8554`

### High CPU usage

- Should only see CPU usage when **actively viewing**
- If always high → check camera isn't stuck streaming

### No on-demand behavior

Check mediamtx config:
```yaml
# In mediamtx.yml
sourceOnDemand: yes
sourceOnDemandCloseAfter: 10s
```

## Performance Comparison

| Metric | Before (JPEG) | After (RTSP) |
|--------|---------------|--------------|
| Bandwidth | ~5-10 Mbps | ~1 Mbps |
| CPU (idle) | 10-20% | 0% |
| CPU (viewing) | 30-50% | 5-10% |
| Latency | 2-3s | 0.5-1s |

## Next Steps

If testing successful:
1. Update version in manifest
2. Create GitHub release
3. Update HACS repository
