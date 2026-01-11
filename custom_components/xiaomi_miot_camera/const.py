# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""Constants for Xiaomi MIoT Camera integration."""

from typing import Final

DOMAIN: Final = "xiaomi_miot_camera"
PLATFORMS: Final = ["camera"]

# Configuration keys
CONF_CLOUD_SERVER: Final = "cloud_server"
CONF_OAUTH_INFO: Final = "oauth_info"
CONF_UUID: Final = "uuid"
CONF_CAMERAS: Final = "cameras"
CONF_SELECTED_CAMERAS: Final = "selected_cameras"

# Default values
DEFAULT_FRAME_INTERVAL: Final = 500  # ms
DEFAULT_IMG_BUFFER_SIZE: Final = 20
DEFAULT_IMG_BUFFER_TTL: Final = 10  # seconds

# Cloud server options
CLOUD_SERVERS: Final = {
    "cn": "中国大陆",
    "de": "Europe",
    "i2": "India",
    "ru": "Russia",
    "sg": "Singapore",
    "us": "United States"
}

# OAuth2 redirect URI for Home Assistant
OAUTH2_REDIRECT_URI: Final = "https://my.home-assistant.io/redirect/oauth"
