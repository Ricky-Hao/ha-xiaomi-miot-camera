# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""Constants for Xiaomi MIoT Camera integration."""

from typing import Final

DOMAIN: Final = "xiaomi_miot_camera"
PLATFORMS: Final = ["camera"]

# Configuration keys
CONF_CLOUD_SERVER: Final = "cloud_server"
CONF_OAUTH_INFO: Final = "oauth_info"
CONF_SELECTED_CAMERAS: Final = "selected_cameras"
CONF_VIDEO_QUALITY: Final = "video_quality"

# Default values
DEFAULT_FRAME_INTERVAL: Final = 500  # ms

# Video quality options
# 1 = LOW, 3 = HIGH, 4/5 = experimental (may not work on all cameras)
VIDEO_QUALITY_LOW: Final = 1
VIDEO_QUALITY_HIGH: Final = 3
VIDEO_QUALITY_SUPER: Final = 4  # Experimental
VIDEO_QUALITY_ULTRA: Final = 5  # Experimental
DEFAULT_VIDEO_QUALITY: Final = VIDEO_QUALITY_HIGH

# Default Add-on URL
DEFAULT_PROXY_URL: Final = "http://127.0.0.1:8765"

# Cloud server (only cn is supported)
CLOUD_SERVER: Final = "cn"
