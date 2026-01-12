# Copilot Instructions

This file provides guidance to GitHub Copilot when working with code in this repository.

## Project Overview

Xiaomi MIoT Camera Integration is a Home Assistant integration for viewing Xiaomi IoT camera video streams. It consists of two parts:

1. **Home Assistant Integration** (`custom_components/xiaomi_miot_camera/`): The HACS-installable integration that provides camera entities in Home Assistant
2. **Camera Proxy Add-on** (`xiaomi_camera_proxy/`): A Home Assistant Add-on that runs the native camera library (required for HAOS users)

The integration uses a **proxy-only architecture** with **WebRTC streaming**:
- All camera streaming goes through the Camera Proxy Add-on
- Add-on uses miot_kit to communicate with Xiaomi cloud
- WebRTC via MediaMTX provides instant, low-latency playback

## Project Structure

```
ha-xiaomi-miot-camera/
├── custom_components/xiaomi_miot_camera/   # HA Integration (HACS)
│   ├── miot/                               # MIoT types and proxy client
│   │   ├── proxy_client.py                 # HTTP client for Add-on API
│   │   ├── camera_backend.py               # Backend interface
│   │   └── types.py                        # Pydantic models
│   ├── camera.py                           # HA Camera entity (WebRTC)
│   ├── coordinator.py                      # Data coordinator
│   ├── config_flow.py                      # Configuration UI
│   └── manifest.json                       # Integration manifest
├── xiaomi_camera_proxy/                    # HA Add-on
│   ├── src/camera_proxy/                   # Python source
│   │   ├── camera_service.py               # Camera management service
│   │   ├── server.py                       # HTTP API server
│   │   ├── rtsp_streamer.py                # FFmpeg→RTSP streamer
│   │   └── __main__.py                     # Entry point
│   ├── rootfs/app/mediamtx.yml             # MediaMTX config
│   ├── config.yaml                         # Add-on configuration
│   └── Dockerfile                          # Add-on container build
└── repository.json                         # Add-on repository manifest
```

## Architecture

### Data Flow
```
Camera → miot_kit → FFmpeg → RTSP (internal) → MediaMTX → WebRTC (external)
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

### HTTP API Endpoints

```python
# Health & Info
GET  /health
GET  /info

# OAuth
GET  /oauth/servers
POST /oauth/auth_url
POST /oauth/callback
POST /oauth/set_tokens
POST /oauth/refresh

# Devices
GET  /devices
GET  /cameras

# Camera Control
POST /camera/{did}/start
POST /camera/{did}/stop
GET  /camera/{did}/status

# Snapshots
GET  /snapshot/{did}
GET  /snapshot/{did}/{channel}
```

### WebRTC (WHEP)
```python
# MediaMTX WHEP endpoint
POST http://localhost:8889/camera/{did}/{channel}/whep
Content-Type: application/sdp
Body: SDP Offer
Response: SDP Answer (201 Created)
```

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

# Test Add-on locally
docker run -p 8765:8765 -p 8889:8889 xiaomi_camera_proxy
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

## Common Issues & Solutions

### HTTP 401 Authentication Error
**Symptom**: `http_post_json failed, error http code, 401` in Add-on logs

**Causes**:
1. Wrong API host - must use `mico.api.mijia.tech`, not `api.io.mi.com`
2. Expired access token - re-authenticate via integration config flow
3. Region mismatch - ensure `cloud_server` matches user's region

### Too Many Connections
**Symptom**: Camera reports too many connections

**Cause**: `stop_camera_async()` was not calling `destroy_camera_async()`

**Solution**: Fixed in v0.4.18 - now properly releases connections when cameras stop

### WebRTC Not Working
**Symptom**: Camera shows black screen or "Stream unavailable"

**Causes**:
1. MediaMTX not running - check add-on logs
2. Port 8889 not accessible
3. Browser doesn't support WebRTC

### Add-on Version Not Updating
**Symptom**: Add-on shows old version after update

**Solution**: 
1. Check all version files are updated (see Version Management section)
2. Uninstall and reinstall the Add-on in Home Assistant
3. Clear browser cache

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
4. Test WebRTC: `curl -X POST http://localhost:8889/camera/{did}/0/whep`

### Release Checklist
1. Update all version numbers (see Version Management)
2. Update CHANGELOG.md
3. Commit with message: `chore: Bump version to x.x.x`
4. Push to GitHub
5. Users reinstall Add-on to get new version

## Code Style

- Follow Python PEP 8 style guide
- Use type hints for function parameters and return values
- Use `_LOGGER` for logging (not `print`)
- Async functions should be named with `_async` suffix
- Use absolute paths in Docker container code

## Commit Message Format

```
<type>: <subject>

<body>
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`

Examples:
- `feat: Add multi-channel camera support`
- `fix: Use correct API host for camera library`
- `chore: Bump add-on version to 0.2.2`
- `docs: Update installation guide`
## Git Configuration

### Commit Author Settings

**⚠️ IMPORTANT**: GitHub blocks pushes that expose private email addresses. Always use the GitHub noreply email format.

**Repository owner**: Hao (Ricky-Hao)
**Noreply email**: `14084342+Ricky-Hao@users.noreply.github.com`

### Before Committing

Always use environment variables to set author/committer when creating commits:

```bash
GIT_COMMITTER_NAME="Hao" \
GIT_COMMITTER_EMAIL="14084342+Ricky-Hao@users.noreply.github.com" \
git commit --author="Hao <14084342+Ricky-Hao@users.noreply.github.com>" -m "message"
```

Or set global config first:
```bash
git config --global user.name "Hao"
git config --global user.email "14084342+Ricky-Hao@users.noreply.github.com"
```

### If Push is Rejected (GH007 Error)

If you see `remote: error: GH007: Your push would publish a private email address`:

```bash
# Fix the last commit with correct author info
GIT_COMMITTER_NAME="Hao" \
GIT_COMMITTER_EMAIL="14084342+Ricky-Hao@users.noreply.github.com" \
git commit --amend --author="Hao <14084342+Ricky-Hao@users.noreply.github.com>" --no-edit

# Then push
git push --force-with-lease
```