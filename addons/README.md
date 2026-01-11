# Xiaomi MIoT Camera Add-ons Repository

Home Assistant Add-ons for Xiaomi MIoT Camera integration.

## Add-ons

### Xiaomi Camera Proxy

A camera streaming proxy that runs the native `libmiot_camera_lite` library in a glibc-based container (Debian), enabling compatibility with Home Assistant OS which uses Alpine Linux (musl libc).

## Installation

1. Add this repository to your Home Assistant Add-on Store:
   - Go to **Settings** → **Add-ons** → **Add-on Store**
   - Click the **⋮** menu → **Repositories**
   - Add: `https://github.com/Ricky-Hao/ha-xiaomi-miot-camera`

2. Install the **Xiaomi Camera Proxy** add-on

3. Start the add-on

4. Install the **Xiaomi MIoT Camera** custom component (HACS)

The custom component will automatically detect and connect to the proxy add-on.
