# Xiaomi Camera Proxy Add-on

Camera streaming proxy for Xiaomi MIoT cameras with WebRTC support.

## About

This add-on is **required** for the Xiaomi MIoT Camera integration. It provides:

- **WebRTC streaming** via MediaMTX for instant, low-latency video playback
- **HTTP API** for camera control and OAuth authentication
- **Native camera library** (miot_kit) for Xiaomi cloud communication

The add-on runs in a Debian-based container with glibc, which is necessary because the native camera library requires glibc.

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
│  │   ├── OAuth authentication       │
│  │   ├── Device discovery           │
│  │   ├── Camera control             │
│  │   └── Snapshots                  │
│  ├── MediaMTX (WebRTC Server)       │
│  │   └── WHEP protocol (port 8889)  │
│  ├── FFmpeg (RTP encapsulation)     │
│  └── miot_kit (camera library)      │
└─────────────────────────────────────┘
```

**Data Flow:**
```
Camera → miot_kit → FFmpeg → RTSP (internal) → MediaMTX → WebRTC (external)
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
video_quality: 3     # Video quality: 1=LOW, 3=HIGH, 4/5=experimental
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `log_level` | Logging verbosity | `info` |
| `transcode_h264` | Transcode H.265 to H.264 for browser WebRTC | `true` |
| `video_quality` | Video quality (1=LOW, 3=HIGH, 4/5=experimental) | `3` |

### Video Quality

- **1 (LOW)**: Lower resolution, less bandwidth
- **3 (HIGH)**: Standard HD quality (recommended)
- **4-5 (Experimental)**: May provide higher quality on some cameras, but not officially supported

## Ports

| Port | Protocol | Description |
|------|----------|-------------|
| 8765 | HTTP | API server (OAuth, devices, control, snapshots) |
| 8889 | HTTP | WebRTC streaming (WHEP protocol) |

## HTTP API

The add-on exposes a REST API on port 8765.

### Endpoints

#### Health & Info

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/info` | Server info and status |

#### OAuth

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/oauth/servers` | Get supported cloud servers |
| POST | `/oauth/auth_url` | Get OAuth authorization URL |
| POST | `/oauth/callback` | Handle OAuth callback |
| POST | `/oauth/set_tokens` | Set tokens directly |
| POST | `/oauth/refresh` | Refresh access token |

#### Devices

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/devices` | Get all devices |
| GET | `/cameras` | Get discovered cameras |

#### Camera Control

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/camera/{did}/start` | Start camera streaming |
| POST | `/camera/{did}/stop` | Stop camera streaming |
| GET | `/camera/{did}/status` | Get camera status |

#### Snapshots

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/snapshot/{did}` | Get camera snapshot (JPEG) |
| GET | `/snapshot/{did}/{channel}` | Get snapshot for specific channel |

### WebRTC Streaming

WebRTC streams are available via MediaMTX's WHEP protocol:

```
POST http://localhost:8889/camera/{did}/{channel}/whep
Content-Type: application/sdp

{SDP Offer}
```

Returns SDP Answer with status 201.

## Troubleshooting

### Add-on won't start

- Check the add-on logs for error messages
- Ensure you have enough system resources
- Try reinstalling the add-on

### Integration can't connect

- Make sure the add-on is running (shows "Started")
- Check that ports 8765 and 8889 are accessible
- Review the add-on logs for connection errors

### Video stream issues

- Check add-on logs for streaming errors
- Ensure your camera is online in Mi Home app
- Try restarting the add-on
- Check that WebRTC is supported in your browser

### Too many connections error

- The add-on properly releases connections when cameras stop
- If you see this error, try restarting the add-on

## Version History

See [CHANGELOG.md](CHANGELOG.md) for detailed version history.

## Support

For issues and feature requests, visit:
https://github.com/Ricky-Hao/ha-xiaomi-miot-camera/issues
