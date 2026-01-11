# Xiaomi Camera Proxy Add-on

Camera streaming proxy for Xiaomi MIoT cameras.

## About

This add-on provides a WebSocket proxy server that runs the native `libmiot_camera_lite.so` library in a glibc-based environment (Debian). This is necessary because Home Assistant OS uses Alpine Linux with musl libc, which is incompatible with glibc-compiled libraries.

## Architecture

```
┌─────────────────────────────────────┐
│  Home Assistant (Alpine/musl)       │
│  ├── Xiaomi MIoT Camera Component   │
│  │   └── WebSocket Client ──────────┼──┐
└─────────────────────────────────────┘  │
                                         │
┌─────────────────────────────────────┐  │
│  Camera Proxy Add-on (Debian/glibc) │  │
│  ├── WebSocket Server ◄─────────────┼──┘
│  ├── libmiot_camera_lite.so ✓       │
│  └── Frame decoding (H264→JPG)      │
└─────────────────────────────────────┘
```

## Configuration

```yaml
log_level: info  # debug, info, warning, error
```

## WebSocket API

The add-on exposes a WebSocket API on port 8765.

### Message Format

All messages are JSON with the following structure:

```json
{
  "type": "message_type",
  "id": "unique_message_id",
  ...params
}
```

### Available Commands

| Type | Description | Parameters |
|------|-------------|------------|
| `init` | Initialize camera library | `cloud_server`, `access_token` |
| `update_token` | Update access token | `access_token` |
| `create_camera` | Create camera instance | `camera_info` |
| `destroy_camera` | Destroy camera instance | `did` |
| `start_camera` | Start streaming | `did`, `pin_code?`, `qualities?`, `enable_audio?` |
| `stop_camera` | Stop streaming | `did` |
| `get_status` | Get camera status | `did` |
| `subscribe_frames` | Subscribe to frames | `did`, `channel?`, `frame_type?` |
| `unsubscribe_frames` | Unsubscribe | `did`, `channel?` |

### Frame Types

- `jpg` - Decoded JPEG images (default)
- `raw_video` - Raw H264/H265 NAL units
- `raw_audio` - Raw AAC frames
- `pcm` - Decoded PCM audio

## Support

- [GitHub Issues](https://github.com/Ricky-Hao/ha-xiaomi-miot-camera/issues)
