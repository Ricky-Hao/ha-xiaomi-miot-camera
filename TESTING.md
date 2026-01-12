# Testing WebRTC Streaming (v0.4.18)

## Architecture Overview

### Current Design (WebRTC Only)
```
Camera → miot_kit → FFmpeg → RTSP (internal) → MediaMTX → WebRTC (external)
```

**Key Points:**
- WebRTC is the only external streaming protocol
- RTSP is internal only (FFmpeg → MediaMTX)
- Instant playback with <1s latency
- No HLS, no external RTSP

## Testing Steps

### 1. Build & Install Add-on

```bash
cd /workspaces/ha-xiaomi-miot-camera
docker build -t xiaomi_camera_proxy xiaomi_camera_proxy/
```

### 2. Check Services Running

After starting the add-on, verify in logs:

```
Starting mediamtx RTSP server...
Starting Xiaomi MIoT Camera Proxy v0.4.18 (using miot_kit)
Server started on 0.0.0.0:8765
```

### 3. Verify WebRTC Stream

When you open a camera in HA:

**Expected flow:**
1. Camera entity has `StreamType.WEB_RTC`
2. HA frontend sends WebRTC offer to camera entity
3. Entity calls `async_handle_web_rtc_offer()`
4. Integration forwards offer to MediaMTX WHEP endpoint
5. MediaMTX returns SDP answer
6. WebRTC connection established
7. Video plays instantly

**Check add-on logs:**
```
Camera XXX already streaming and ready, returning immediately
```

### 4. Test Snapshots

`camera.snapshot` service should work:
- Uses HTTP API: `GET /snapshot/{did}/{channel}`
- Returns JPEG from decoded I-frames

```yaml
service: camera.snapshot
target:
  entity_id: camera.living_room
data:
  filename: /config/snapshot.jpg
```

### 5. Test Connection Release

When stopping a camera:

**Check logs:**
```
Stopped camera: XXX (connection released)
Destroyed camera instance: XXX
```

Each camera should have exactly one connection.

## Ports

| Port | Protocol | Description |
|------|----------|-------------|
| 8765 | HTTP | API (OAuth, control, snapshots) |
| 8889 | HTTP | WebRTC (WHEP protocol) |
| 8554 | RTSP | Internal only (FFmpeg → MediaMTX) |
| 9997 | HTTP | MediaMTX API (internal) |

## Troubleshooting

### Stream not appearing

1. Check mediamtx is running: `ps aux | grep mediamtx`
2. Check port 8889 is accessible
3. Verify WebRTC is enabled in mediamtx.yml
4. Check browser supports WebRTC

### WebRTC connection failed

1. Check WHEP endpoint: `curl -X POST http://localhost:8889/camera/{did}/0/whep`
2. Check MediaMTX API: `curl http://localhost:9997/v3/paths/list`
3. Verify camera is streaming (check RTSP input)

### Too many connections

1. Ensure `destroy_camera_async()` is called on stop
2. Check add-on logs for "connection released"
3. Restart add-on to clear stuck connections

## Performance

| Metric | Value |
|--------|-------|
| Latency | <1 second |
| Protocol | WebRTC (WHEP) |
| Codec | H.264/H.265 (passthrough) |
| CPU Usage | Minimal (no transcoding) |

## API Testing

### Health Check
```bash
curl http://localhost:8765/health
# {"status": "ok", "version": "0.4.18", ...}
```

### Start Camera
```bash
curl -X POST http://localhost:8765/camera/{did}/start \
  -H "Content-Type: application/json" \
  -d '{"quality": 2}'
# {"status": "ok"}
```

### Get Snapshot
```bash
curl http://localhost:8765/snapshot/{did}/0 -o snapshot.jpg
```

### WebRTC WHEP
```bash
curl -X POST http://localhost:8889/camera/{did}/0/whep \
  -H "Content-Type: application/sdp" \
  -d "{SDP_OFFER}"
# Returns SDP Answer
```
