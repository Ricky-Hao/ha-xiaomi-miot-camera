# Xiaomi Camera Proxy Add-on

Camera streaming proxy for Xiaomi MIoT cameras.

## About

This add-on is **required** for the Xiaomi MIoT Camera integration. It provides a WebSocket proxy server that runs the native `libmiot_camera_lite.so` library and handles video decoding.

The add-on runs in a Debian-based container with glibc, which is necessary because the native camera library is compiled with glibc.

## How It Works

```
┌─────────────────────────────────────┐
│  Home Assistant                     │
│  └── Xiaomi MIoT Camera Integration │
│      └── WebSocket Client ──────────┼──┐
└─────────────────────────────────────┘  │
                                         │ Port 8765
┌─────────────────────────────────────┐  │
│  Camera Proxy Add-on (Debian/glibc) │  │
│  ├── WebSocket Server ◄─────────────┼──┘
│  ├── Native Library (glibc)         │
│  ├── H264/H265 Video Decoding       │
│  └── JPEG Frame Output              │
└─────────────────────────────────────┘
```

## Installation

1. Go to **Settings** → **Add-ons** → **Add-on Store**
2. Click the **⋮** menu → **Repositories**
3. Add: `https://github.com/Ricky-Hao/ha-xiaomi-miot-camera`
4. Find and install **Xiaomi Camera Proxy**
5. Start the add-on
6. Install the Xiaomi MIoT Camera integration

## Configuration

```yaml
log_level: info  # debug, info, warning, error
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `log_level` | Logging verbosity | `info` |

## WebSocket API

The add-on exposes a WebSocket API on port 8765 for internal use by the integration.

### Message Format

All messages are JSON:

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
| `subscribe_frames` | Subscribe to JPEG frames | `did`, `channel?` |
| `unsubscribe_frames` | Unsubscribe | `did`, `channel?` |

## Troubleshooting

### Add-on won't start

- Check the add-on logs for error messages
- Ensure you have enough system resources
- Try reinstalling the add-on

### Integration can't connect

- Make sure the add-on is running (shows "Started")
- Check that port 8765 is accessible
- Review the add-on logs for connection errors

### Video stream issues

- Check add-on logs for decoding errors
- Ensure your camera is online in Mi Home app
- Try restarting the add-on

## Support

- [GitHub Issues](https://github.com/Ricky-Hao/ha-xiaomi-miot-camera/issues)
