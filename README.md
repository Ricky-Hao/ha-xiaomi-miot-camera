# Xiaomi MIoT Camera for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/Ricky-Hao/ha-xiaomi-miot-camera)

This custom component integrates Xiaomi MIoT cameras into Home Assistant, allowing you to view live video streams from your Xiaomi smart home cameras.

## Features

- 🎥 **Instant WebRTC streaming** - Sub-second latency live video
- 🔐 **Secure OAuth2 authentication** with Xiaomi account
- 📷 **Still image capture** (snapshots)
- 🔄 **Auto-reconnection** on connection loss
- 📺 **Multi-channel camera support**
- 🐳 **Home Assistant OS support** via Add-on

## Requirements

- Home Assistant 2024.1.0 or newer
- A Xiaomi account with cameras linked in Mi Home app
- Network access to Xiaomi cloud services
- **Xiaomi Camera Proxy Add-on** (required for camera streaming)

## Installation

### Step 1: Install the Camera Proxy Add-on (Required)

The integration requires the Camera Proxy Add-on for video streaming. This add-on runs the native camera library in a compatible environment.

1. Go to **Settings** → **Add-ons** → **Add-on Store**
2. Click the **⋮** menu → **Repositories**
3. Add: `https://github.com/Ricky-Hao/ha-xiaomi-miot-camera`
4. Find and install the **Xiaomi Camera Proxy** add-on
5. **Start the add-on** and ensure it's running

### Step 2: Install the Integration

#### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL and select "Integration" as the category
6. Click "Add"
7. Search for "Xiaomi MIoT Camera" and install it
8. Restart Home Assistant

#### Manual Installation

1. Download the `custom_components/xiaomi_miot_camera` folder from this repository
2. Copy it to your Home Assistant's `custom_components` directory
3. Restart Home Assistant

## Configuration

1. Ensure the **Xiaomi Camera Proxy** add-on is running
2. Go to **Settings** → **Devices & Services** → **Add Integration**
3. Search for "Xiaomi MIoT Camera"
4. Select your cloud server region
5. Follow the OAuth2 login process:
   - Click the provided link to login to your Xiaomi account
   - After authorization, copy the `code` and `state` from the redirect URL
   - Enter these values in Home Assistant
6. Select the cameras you want to add
7. Done! Your cameras will appear as camera entities

## Usage

### Viewing Camera Streams

- Go to **Overview** → Add a Picture Glance or Picture Entity card
- Select your Xiaomi camera entity
- The live stream will be displayed

### Lovelace Card Example

```yaml
type: picture-entity
entity: camera.living_room_camera
camera_view: live
```

### Automation Example

```yaml
automation:
  - alias: "Save snapshot on motion"
    trigger:
      - platform: state
        entity_id: binary_sensor.motion_sensor
        to: "on"
    action:
      - service: camera.snapshot
        target:
          entity_id: camera.living_room_camera
        data:
          filename: "/config/snapshots/motion_{{ now().strftime('%Y%m%d_%H%M%S') }}.jpg"
```

## Supported Camera Models

This integration should work with any Xiaomi/Mi Home camera that supports streaming through the MIoT protocol, including:

- Xiaomi Smart Camera C series
- Xiaomi Smart Camera Pro
- Xiaomi 360° Home Security Camera
- Mi Home Security Camera
- And more...

## Troubleshooting

### "Camera streaming not available" error

Make sure the Camera Proxy Add-on is installed and running:

1. Go to **Settings** → **Add-ons**
2. Find **Xiaomi Camera Proxy**
3. Ensure it shows "Running"
4. Check the add-on logs for any errors

### Camera shows as unavailable

- Check your internet connection
- Ensure the camera is online in the Mi Home app
- Check that the Camera Proxy Add-on is running
- Try restarting the integration

### Authentication failed

- Make sure you copied the `code` and `state` values correctly
- The authorization code expires quickly, try the process again
- Check that you selected the correct cloud region

### Stream is laggy or not loading

- The stream quality depends on your network connection
- Try reducing the frame interval in options
- Ensure your Home Assistant server has sufficient resources
- Check the Camera Proxy Add-on logs for errors

## Architecture

```
┌─────────────────────────────────────┐
│  Home Assistant                     │
│  └── Camera Entity                  │
│      ├── WebRTC (WHEP) ─────────────┼──────────► Port 8889 (MediaMTX)
│      └── Snapshots ─────────────────┼──┐
└─────────────────────────────────────┘  │
                                         │ Port 8765 (HTTP API)
┌─────────────────────────────────────┐  │
│  Camera Proxy Add-on (Debian)       │◄─┘
│  ├── MediaMTX (WebRTC Server)       │
│  │   └── Instant playback           │
│  ├── FFmpeg (RTP encapsulation)     │
│  ├── miot_kit (camera library)      │
│  └── HTTP API Server                │
└─────────────────────────────────────┘
```

**Data Flow:**
```
Camera → miot_kit → FFmpeg → RTSP (internal) → MediaMTX → WebRTC (external)
```

**Key Features:**
- **Instant playback**: WebRTC provides <1s latency, no buffering
- **Low bandwidth**: H.264/H.265 direct streaming
- **Low CPU**: No transcoding in Home Assistant
- **Native HA support**: Uses Home Assistant's WebRTC camera support

**Ports:**
- **8765**: HTTP API (OAuth, device discovery, camera control, snapshots)
- **8889**: WebRTC streaming (WHEP protocol)

## Privacy Note

This integration connects to Xiaomi cloud services to access your camera streams. All video data is transmitted through Xiaomi's encrypted channels. Your Xiaomi account credentials are handled securely through OAuth2 and are never stored in plain text.

## License

This project uses a dual-license structure:

- **Main project code**: Licensed under the [Apache License 2.0](LICENSE)
- **`miot/` directory**: Contains code derived from the [Xiaomi Miloco](https://github.com/XiaoMi/xiaomi-miloco) project, licensed under the [Xiaomi Miloco License Agreement](custom_components/xiaomi_miot_camera/miot/LICENSE) (non-commercial use only)

Please review the respective licenses before using or distributing this software.

## Credits

This integration uses the `miot_kit` library from the [Xiaomi Miloco](https://github.com/XiaoMi/xiaomi-miloco) project.
