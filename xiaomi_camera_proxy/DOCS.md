# Xiaomi Camera Proxy Add-on

Camera streaming proxy for Xiaomi MIoT cameras with WebRTC support.

## About

This add-on is **required** for the Xiaomi MIoT Camera integration. It provides:

- **WebRTC streaming** via MediaMTX for instant, low-latency video playback
- **HTTP API** for camera control and OAuth authentication
- **Native camera library** (miot_kit) for Xiaomi cloud communication

## How It Works

```
┌─────────────────────────────────────┐
│  Home Assistant                     │
│  └── Xiaomi MIoT Camera Integration │
│      ├── WebRTC (WHEP) ─────────────┼──► Port 8889 (MediaMTX)
│      └── HTTP API ──────────────────┼──┐
└─────────────────────────────────────┘  │
                                         │ Port 8765
┌─────────────────────────────────────┐  │
│  Camera Proxy Add-on (Debian/glibc) │◄─┘
│  ├── HTTP API Server                │
│  ├── MediaMTX (WebRTC Server)       │
│  ├── FFmpeg (Video transcoding)     │
│  └── miot_kit (Camera library)      │
└─────────────────────────────────────┘
```

**Data Flow:**
```
Xiaomi Cloud → miot_kit → FFmpeg → RTSP → MediaMTX → WebRTC → Browser
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
log_level: info      # debug, info, warning, error
transcode_h264: true # Transcode H.265 to H.264 for browser compatibility
video_quality: 3     # Video quality: 1=LOW, 3=HIGH
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `log_level` | Logging verbosity | `info` |
| `transcode_h264` | Transcode H.265 to H.264 for WebRTC | `true` |
| `video_quality` | Video quality (1=LOW, 3=HIGH) | `3` |

## Ports

| Port | Protocol | Description |
|------|----------|-------------|
| 8765 | HTTP | API server |
| 8889 | HTTP | WebRTC (WHEP) |

## Troubleshooting

### Add-on won't start
- Check add-on logs for errors
- Ensure sufficient system resources

### No video stream
- Verify camera is online in Mi Home app
- Check add-on logs for connection errors
- Restart the add-on

### Browser compatibility
- WebRTC requires a modern browser
- Enable `transcode_h264` for best compatibility

## Support

For issues: https://github.com/Ricky-Hao/ha-xiaomi-miot-camera/issues
