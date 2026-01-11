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
CONF_PROXY_URL: Final = "proxy_url"

# Default values
DEFAULT_FRAME_INTERVAL: Final = 500  # ms
DEFAULT_IMG_BUFFER_SIZE: Final = 20
DEFAULT_IMG_BUFFER_TTL: Final = 10  # seconds
DEFAULT_PROXY_URL: Final = "ws://127.0.0.1:8765/ws"

# Cloud server options
CLOUD_SERVERS: Final = {
    "cn": "中国大陆",
    "de": "Europe",
    "i2": "India",
    "ru": "Russia",
    "sg": "Singapore",
    "us": "United States"
}

# OAuth2 redirect URI - uses Xiaomi's official redirect page
# This page allows users to jump to their local HA instance with code/state
OAUTH2_REDIRECT_URI: Final = "https://mico.api.mijia.tech/login_redirect"

# OAuth callback path in Home Assistant
OAUTH_CALLBACK_PATH: Final = "/api/xiaomi_miot_camera/callback"
