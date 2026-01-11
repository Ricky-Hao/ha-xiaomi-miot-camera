# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""OAuth callback handler for Xiaomi MIoT Camera integration."""
from __future__ import annotations

import logging
from typing import Any
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, OAUTH_CALLBACK_PATH

_LOGGER = logging.getLogger(__name__)

# Store pending OAuth flows: {state: flow_id}
PENDING_FLOWS: dict[str, str] = {}
# Store received callbacks: {state: {"code": code, "state": state}}
RECEIVED_CALLBACKS: dict[str, dict[str, str]] = {}


class XiaomiOAuthCallbackView(HomeAssistantView):
    """Handle OAuth callback from Xiaomi."""

    url = OAUTH_CALLBACK_PATH
    name = "api:xiaomi_miot_camera:callback"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request with OAuth callback."""
        hass: HomeAssistant = request.app["hass"]

        # Get code and state from query parameters
        code = request.query.get("code")
        state = request.query.get("state")

        _LOGGER.info("Received OAuth callback: code=%s, state=%s", 
                     code[:10] + "..." if code else None, state)

        if not code or not state:
            return web.Response(
                text=self._generate_error_html("Missing code or state parameter"),
                content_type="text/html",
                status=400,
            )

        # Store the callback data
        RECEIVED_CALLBACKS[state] = {"code": code, "state": state}
        _LOGGER.info("Stored callback for state: %s", state)

        # Check if there's a pending flow for this state
        if state in PENDING_FLOWS:
            flow_id = PENDING_FLOWS[state]
            _LOGGER.info("Found pending flow %s for state %s", flow_id, state)
            
            # Continue the config flow
            try:
                await hass.config_entries.flow.async_configure(
                    flow_id,
                    user_input={"code": code, "state": state}
                )
            except Exception as err:
                _LOGGER.warning("Failed to continue flow: %s", err)

        return web.Response(
            text=self._generate_success_html(),
            content_type="text/html",
        )

    def _generate_success_html(self) -> str:
        """Generate success HTML page."""
        return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Authorization Successful</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            text-align: center;
            max-width: 400px;
        }
        .icon {
            font-size: 64px;
            margin-bottom: 20px;
        }
        h1 {
            color: #333;
            margin-bottom: 16px;
        }
        p {
            color: #666;
            line-height: 1.6;
        }
        .close-btn {
            margin-top: 20px;
            padding: 12px 32px;
            background: #ff5c00;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            cursor: pointer;
            transition: background 0.3s;
        }
        .close-btn:hover {
            background: #e55200;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">✅</div>
        <h1>Authorization Successful!</h1>
        <p>Xiaomi account has been linked successfully.<br>
        You can close this window and return to Home Assistant.</p>
        <button class="close-btn" onclick="window.close()">Close Window</button>
    </div>
    <script>
        // Try to close after 3 seconds
        setTimeout(function() {
            window.close();
        }, 3000);
    </script>
</body>
</html>
"""

    def _generate_error_html(self, error: str) -> str:
        """Generate error HTML page."""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Authorization Failed</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            text-align: center;
            max-width: 400px;
        }}
        .icon {{
            font-size: 64px;
            margin-bottom: 20px;
        }}
        h1 {{
            color: #333;
            margin-bottom: 16px;
        }}
        p {{
            color: #666;
            line-height: 1.6;
        }}
        .error {{
            color: #f5576c;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">❌</div>
        <h1>Authorization Failed</h1>
        <p class="error">{error}</p>
        <p>Please close this window and try again in Home Assistant.</p>
    </div>
</body>
</html>
"""


@callback
def register_oauth_callback_view(hass: HomeAssistant) -> None:
    """Register the OAuth callback view."""
    hass.http.register_view(XiaomiOAuthCallbackView())
    _LOGGER.info("Registered Xiaomi OAuth callback view at %s", OAUTH_CALLBACK_PATH)


def register_pending_flow(state: str, flow_id: str) -> None:
    """Register a pending OAuth flow."""
    PENDING_FLOWS[state] = flow_id
    _LOGGER.debug("Registered pending flow: state=%s, flow_id=%s", state, flow_id)


def unregister_pending_flow(state: str) -> None:
    """Unregister a pending OAuth flow."""
    PENDING_FLOWS.pop(state, None)
    RECEIVED_CALLBACKS.pop(state, None)


def get_received_callback(state: str) -> dict[str, str] | None:
    """Get received callback data for a state."""
    return RECEIVED_CALLBACKS.get(state)


def clear_received_callback(state: str) -> None:
    """Clear received callback data."""
    RECEIVED_CALLBACKS.pop(state, None)
