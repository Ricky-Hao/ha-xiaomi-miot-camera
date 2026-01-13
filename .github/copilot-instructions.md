# Copilot Instructions

This file provides guidance to GitHub Copilot when working with code in this repository.

## Project Overview

Xiaomi MIoT Camera Integration is a Home Assistant integration for viewing Xiaomi IoT camera video streams. It consists of two parts:

1. **Home Assistant Integration** (`custom_components/xiaomi_miot_camera/`): The HACS-installable integration that provides camera entities in Home Assistant
2. **Camera Proxy Add-on** (`xiaomi_camera_proxy/`): A Home Assistant Add-on that runs the native camera library (required for HAOS users)

The integration uses a **proxy-only architecture** with **WebRTC streaming**:
- All camera streaming goes through the Camera Proxy Add-on
- Add-on uses `miot_kit` from [xiaomi-miloco](https://github.com/xiaomi/xiaomi-miloco) to communicate with Xiaomi cloud
- WebRTC via MediaMTX provides instant, low-latency playback
- Only **China (cn)** region is supported

## Current Version

- **Integration**: 1.0.0 (`manifest.json`)
- **Add-on**: 1.0.0 (`config.yaml`)

## Project Structure

```
ha-xiaomi-miot-camera/
├── custom_components/xiaomi_miot_camera/   # HA Integration (HACS)
│   ├── miot/                               # MIoT types and proxy client
│   │   ├── proxy_client.py                 # HTTP client for Add-on API (CameraProxyHttpClient)
│   │   ├── camera_backend.py               # Backend interface (CameraBackend)
│   │   └── types.py                        # Pydantic models (MIoTCameraInfo, MIoTOauthInfo, etc.)
│   ├── camera.py                           # HA Camera entity (XiaomiMiotCamera, WebRTC via WHEP)
│   ├── coordinator.py                      # Data coordinator (XiaomiCameraCoordinator)
│   ├── config_flow.py                      # Configuration UI (OAuth flow via Add-on)
│   ├── const.py                            # Constants (DOMAIN, PLATFORMS, etc.)
│   ├── strings.json                        # UI strings (English)
│   ├── translations/                       # Localization (en.json, zh-Hans.json)
│   └── manifest.json                       # Integration manifest
├── xiaomi_camera_proxy/                    # HA Add-on
│   ├── src/camera_proxy/                   # Python source
│   │   ├── camera_service.py               # Camera management service (CameraService)
│   │   ├── server.py                       # HTTP API server (CameraProxyServer)
│   │   ├── rtsp_streamer.py                # FFmpeg→RTSP streamer (RTSPStreamer, FFmpegWriter)
│   │   └── __main__.py                     # Entry point
│   ├── rootfs/
│   │   ├── run.sh                          # Add-on startup script
│   │   └── app/mediamtx.yml                # MediaMTX config (RTSP + WebRTC)
│   ├── config.yaml                         # Add-on configuration (ports, options schema)
│   ├── requirements.txt                    # Python dependencies (miot_kit from git)
│   └── Dockerfile                          # Add-on container build (Debian bookworm)
└── repository.json                         # Add-on repository manifest
```

## Architecture

### Data Flow
```
Xiaomi Cloud → miot_kit → Camera Frames → FFmpeg → RTSP (internal) → MediaMTX → WebRTC (browser)
```

### Ports
- **8765**: HTTP API (OAuth, devices, camera control, snapshots)
- **8889**: WebRTC streaming (WHEP protocol)
- **8554**: RTSP (internal only, FFmpeg → MediaMTX)
- **9997**: MediaMTX API (internal)

### Communication Flow
```
HA Integration  ←→  HTTP API (8765)  ←→  Camera Proxy Add-on  ←→  miot_kit  ←→  Xiaomi Cloud
                                                                                     ↓
HA Frontend     ←→  WebRTC (8889)   ←→  MediaMTX            ←→  FFmpeg    ←→  Camera Stream
```

### Key Components

#### Integration Side
- **XiaomiCameraCoordinator**: Manages camera lifecycle, polls status every 10 seconds
- **XiaomiMiotCamera**: Camera entity with native WebRTC support via WHEP
- **CameraProxyHttpClient**: HTTP client for Add-on communication
- **CameraBackend**: High-level abstraction over proxy client

#### Add-on Side
- **CameraProxyServer**: aiohttp server exposing REST API
- **CameraService**: Core logic using miot_kit for camera operations
- **RTSPStreamer**: Manages FFmpeg processes for video transcoding
- **FFmpegWriter**: Thread-based writer to prevent asyncio blocking

### Add-on Options (config.yaml)
```yaml
options:
  log_level: info        # debug|info|warning|error
  transcode_h264: true   # Transcode H.265→H.264 for browser compatibility
  video_quality: 3       # 1=LOW, 3=HIGH, 4/5=experimental
```

### HTTP API Endpoints

```python
# Health & Info
GET  /health                              # {"status": "ok", "version": "1.0.0", "authenticated": bool}
GET  /info                                # {"version": str, "cloud_server": str, "camera_count": int}

# OAuth
GET  /oauth/servers                       # {"servers": {"cn": "China", ...}}
POST /oauth/auth_url                      # Body: {"cloud_server": "cn", "redirect_uri": "..."} → {"auth_url": str}
POST /oauth/callback                      # Body: {"code": str, "state": str} → {"status": "ok"}
POST /oauth/set_tokens                    # Body: {"cloud_server": str, "access_token": str, "refresh_token": str}
POST /oauth/refresh                       # Refresh access token → {"status": "ok"}

# Devices
GET  /devices                             # {"devices": {did: MIoTDeviceInfo}}
GET  /cameras                             # {"cameras": {did: MIoTCameraInfo}}

# Configuration
POST /config/cameras                      # Body: {"camera_dids": [...]} - Set cameras for auto-start

# Camera Control
POST /camera/{did}/start                  # Body: {"pin_code": str?, "enable_audio": bool?} → {"status": "ok"}
POST /camera/{did}/stop                   # → {"status": "ok"}
GET  /camera/{did}/status                 # → {"status": int} (MIoTCameraStatus enum value)

# Snapshots
GET  /snapshot/{did}                      # → image/jpeg
GET  /snapshot/{did}/{channel}            # → image/jpeg
```

### WebRTC (WHEP)
```bash
# MediaMTX WHEP endpoint (handled by HA Frontend automatically)
POST http://<addon-host>:8889/camera/{did}/{channel}/whep
Content-Type: application/sdp
Body: SDP Offer
Response: SDP Answer (201 Created)
```

### Stream Paths
- **RTSP (internal)**: `rtsp://localhost:8554/camera/{did}/{channel}`
- **WebRTC (WHEP)**: `http://localhost:8889/camera/{did}/{channel}/whep`

## Development Commands

### Testing Integration Locally
```bash
# Copy integration to HA config
cp -r custom_components/xiaomi_miot_camera /path/to/ha-config/custom_components/

# Restart Home Assistant
ha core restart
```

### Building Add-on (for testing)
```bash
# Build Add-on image locally
cd xiaomi_camera_proxy
docker build -t xiaomi_camera_proxy .

# Test Add-on locally (need /data directory for persistence)
docker run -p 8765:8765 -p 8889:8889 -p 8554:8554 -v /tmp/data:/data xiaomi_camera_proxy
```

### Debugging
Enable debug logging in Home Assistant configuration.yaml:
```yaml
logger:
  default: warning
  logs:
    custom_components.xiaomi_miot_camera: debug
```

Check Add-on logs in Home Assistant → Settings → Add-ons → Xiaomi MIoT Camera Proxy → Log

### Testing HTTP API
```bash
# Health check
curl http://localhost:8765/health

# Get cameras (requires authentication)
curl http://localhost:8765/cameras

# Start camera
curl -X POST http://localhost:8765/camera/{did}/start

# Get snapshot
curl http://localhost:8765/snapshot/{did} --output snapshot.jpg
```

## Common Issues & Solutions

### HTTP 401 Authentication Error
**Symptom**: `http_post_json failed, error http code, 401` in Add-on logs

**Causes**:
1. Wrong API host - must use `mico.api.mijia.tech`, not `api.io.mi.com`
2. Expired access token - re-authenticate via integration config flow
3. Region mismatch - only `cn` (China) is supported

### WebRTC Not Working
**Symptom**: Camera shows black screen or "Stream unavailable"

**Causes**:
1. MediaMTX not running - check add-on logs for startup errors
2. Port 8889 not accessible - ensure `host_network: true` in add-on config
3. Browser doesn't support WebRTC - try Chrome or Firefox
4. H.265 not transcoded - ensure `transcode_h264: true` in add-on options

### Add-on Not Starting
**Symptom**: Add-on shows as stopped or fails to start

**Causes**:
1. MediaMTX failed to start - check logs for port conflicts
2. Missing dependencies - check Dockerfile build
3. Architecture mismatch - only amd64 and aarch64 are supported

### OAuth Flow Issues
**Symptom**: Cannot complete OAuth authentication

**Causes**:
1. Add-on not running - start the add-on first
2. Redirect URI mismatch - must use `https://mico.api.mijia.tech/login_redirect`
3. Network issues - ensure HA can reach Xiaomi cloud

## Development Workflow

### Adding New Features
1. Design the HTTP API endpoints
2. Implement in Add-on (`camera_service.py` for logic, `server.py` for API)
3. Implement client in integration (`proxy_client.py`)
4. Update coordinator/camera entity as needed
5. Test locally before committing

### Debugging Add-on Issues
1. Check Add-on logs first
2. Add debug logging: `_LOGGER.debug("Variable: %s", var)`
3. Test HTTP API directly: `curl http://localhost:8765/health`
4. Test WebRTC: Open browser console, check for WHEP errors

### Release Checklist
1. Update version in `custom_components/xiaomi_miot_camera/manifest.json`
2. Update version in `xiaomi_camera_proxy/config.yaml`
3. Update version in `xiaomi_camera_proxy/src/camera_proxy/server.py` (`__version__`)
4. Update CHANGELOG.md
5. Commit with message: `chore: Bump version to x.x.x`
6. Push to GitHub
7. Users reinstall Add-on to get new version

## Code Style

- Follow Python PEP 8 style guide
- Use type hints for function parameters and return values
- Use `_LOGGER` for logging (not `print`)
- Async functions should be named with `_async` suffix
- Use Pydantic models for data validation (`types.py`)
- Use absolute paths in Docker container code
- Copyright header: `# Copyright (C) 2025 Xiaomi Corporation`

## Key Files Reference

### Integration
- [manifest.json](custom_components/xiaomi_miot_camera/manifest.json): Integration metadata, version, dependencies
- [camera.py](custom_components/xiaomi_miot_camera/camera.py): WebRTC camera entity implementation
- [coordinator.py](custom_components/xiaomi_miot_camera/coordinator.py): Data coordinator, camera management
- [config_flow.py](custom_components/xiaomi_miot_camera/config_flow.py): OAuth flow, camera selection UI
- [proxy_client.py](custom_components/xiaomi_miot_camera/miot/proxy_client.py): HTTP client for Add-on API
- [types.py](custom_components/xiaomi_miot_camera/miot/types.py): Pydantic models for camera data

### Add-on
- [config.yaml](xiaomi_camera_proxy/config.yaml): Add-on metadata, ports, options schema
- [server.py](xiaomi_camera_proxy/src/camera_proxy/server.py): HTTP API implementation
- [camera_service.py](xiaomi_camera_proxy/src/camera_proxy/camera_service.py): Core camera logic
- [rtsp_streamer.py](xiaomi_camera_proxy/src/camera_proxy/rtsp_streamer.py): FFmpeg streaming, H.265→H.264 transcoding
- [mediamtx.yml](xiaomi_camera_proxy/rootfs/app/mediamtx.yml): MediaMTX RTSP/WebRTC configuration
- [run.sh](xiaomi_camera_proxy/rootfs/run.sh): Add-on startup script

## Commit Message Format

```
<type>: <subject>

<body>
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`

Examples:
- `feat: Add multi-channel camera support`
- `fix: Use correct API host for camera library`
- `chore: Bump version to 1.0.0`
- `docs: Update installation guide`