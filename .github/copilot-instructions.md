# Copilot Instructions

This file provides guidance to GitHub Copilot when working with code in this repository.

## Project Overview

Xiaomi MIoT Camera Integration is a Home Assistant integration for viewing Xiaomi IoT camera video streams. It consists of two parts:

1. **Home Assistant Integration** (`custom_components/xiaomi_miot_camera/`): The HACS-installable integration that provides camera entities in Home Assistant
2. **Camera Proxy Add-on** (`xiaomi_camera_proxy/`): A Home Assistant Add-on that runs the native camera library (required for HAOS users)

The integration uses a **proxy-only architecture** - all camera streaming goes through the Camera Proxy Add-on which wraps the native C library (`libmiot_camera_lite.so`).

## Project Structure

```
ha-xiaomi-miot-camera/
├── custom_components/xiaomi_miot_camera/   # HA Integration (HACS)
│   ├── miot/                               # Core MIoT library (OAuth, cloud API)
│   ├── camera.py                           # HA Camera entity
│   ├── camera_backend.py                   # Proxy client (WebSocket)
│   ├── coordinator.py                      # Data coordinator
│   ├── config_flow.py                      # Configuration UI
│   └── manifest.json                       # Integration manifest
├── xiaomi_camera_proxy/                    # HA Add-on
│   ├── src/camera_proxy/                   # Python source
│   │   ├── camera_manager.py               # Native library wrapper (ctypes)
│   │   ├── server.py                       # WebSocket API server
│   │   └── __main__.py                     # Entry point
│   ├── libs/                               # Native libraries
│   │   └── linux/{x86_64,arm64}/           # Platform-specific .so files
│   ├── config.yaml                         # Add-on configuration
│   └── Dockerfile                          # Add-on container build
└── repository.json                         # Add-on repository manifest
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
docker run -p 8765:8765 xiaomi_camera_proxy
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

## Architecture

### Communication Flow
```
HA Integration  ←→  WebSocket (8765)  ←→  Camera Proxy Add-on  ←→  Native Library  ←→  Xiaomi Cloud
                                                                                    ↓
                                                                               Camera Device
```

### WebSocket API Protocol
The integration communicates with the Add-on via WebSocket JSON messages:

```python
# Initialize library
{"action": "init", "cloud_server": "cn", "access_token": "..."}

# Create camera
{"action": "create_camera", "camera_info": {...}, "frame_interval": 1000}

# Start streaming
{"action": "start", "did": "device_id", "channel": 0}

# Frame callback (from Add-on)
{"action": "frame", "did": "device_id", "channel": 0, "data": "<base64>", ...}
```

### Key Constants

**API Host** (camera_manager.py):
```python
PROJECT_CODE = "mico"
OAUTH2_API_HOST_DEFAULT = f"{PROJECT_CODE}.api.mijia.tech"  # mico.api.mijia.tech
```

For non-China regions: `{region}.{OAUTH2_API_HOST_DEFAULT}` (e.g., `ru.mico.api.mijia.tech`)

**Library Path** (in Docker container):
```python
lib_base = Path("/app/libs")  # NOT relative path!
```

## Version Management

**⚠️ CRITICAL RULE**: Any code changes to Add-on or Integration MUST include a version bump. This includes:
- Bug fixes
- New features
- Refactoring
- Configuration changes

Version numbers must be updated in **documentation**, **code**, and **configuration files** simultaneously.

### Add-on Version (xiaomi_camera_proxy/)

When modifying any file in `xiaomi_camera_proxy/`, update ALL of these:

| File | Field | Example |
|------|-------|---------|
| `config.yaml` | `version: "x.x.x"` | `version: "0.2.2"` |
| `src/camera_proxy/__init__.py` | `__version__ = "x.x.x"` | `__version__ = "0.2.2"` |
| `src/camera_proxy/__main__.py` | Log message version string | `"Starting... v0.2.2"` |
| `CHANGELOG.md` | Add new version section | `## [0.2.2] - YYYY-MM-DD` |

### Integration Version (custom_components/xiaomi_miot_camera/)

When modifying any file in `custom_components/xiaomi_miot_camera/`, update:

| File | Field |
|------|-------|
| `manifest.json` | `"version": "x.x.x"` |

### Update Checklist
```bash
# After making changes, update all version files, then:
git add -A
git commit -m "chore: Bump version to x.x.x"
git push
```

## Common Issues & Solutions

### HTTP 401 Authentication Error
**Symptom**: `http_post_json failed, error http code, 401` in Add-on logs

**Causes**:
1. Wrong API host - must use `mico.api.mijia.tech`, not `api.io.mi.com`
2. Expired access token - re-authenticate via integration config flow
3. Region mismatch - ensure `cloud_server` matches user's region

### Library Not Found
**Symptom**: `FileNotFoundError: Library not found: /libs/linux/x86_64/...`

**Solution**: In Docker container, library path should be `/app/libs/`, not relative path.

### Add-on Version Not Updating
**Symptom**: Add-on shows old version after update

**Solution**: 
1. Check all version files are updated (see Version Management section)
2. Uninstall and reinstall the Add-on in Home Assistant
3. Clear browser cache

## Development Workflow

### Adding New Features
1. Design the WebSocket API message format
2. Implement in Add-on (`camera_manager.py` for native calls, `server.py` for API)
3. Implement client in integration (`camera_backend.py`)
4. Update coordinator/camera entity as needed
5. Test locally before committing

### Debugging Add-on Issues
1. Check Add-on logs first
2. Add debug logging: `_LOGGER.debug("Variable: %s", var)`
3. Verify constants match between integration and Add-on:
   - `OAUTH2_API_HOST_DEFAULT`
   - `OAUTH2_CLIENT_ID`
   - `cloud_server` format
4. Check library path is absolute in container (`/app/libs/`)

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