# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""Simplified config flow for Xiaomi MIoT Camera integration.

This version uses the Camera Proxy Add-on for OAuth and device discovery.
The flow is:
1. User selects cloud server
2. User authenticates via OAuth (handled by Add-on or manually)
3. Cameras are discovered via Add-on
4. User selects which cameras to use
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.network import get_url

from .const import (
    DOMAIN,
    CONF_CLOUD_SERVER,
    CONF_OAUTH_INFO,
    CONF_SELECTED_CAMERAS,
    CLOUD_SERVERS,
    OAUTH_CALLBACK_PATH,
)
from .miot.proxy_client import CameraProxyHttpClient

_LOGGER = logging.getLogger(__name__)

# Default Add-on URL
DEFAULT_PROXY_URL = "http://127.0.0.1:8765"


async def check_addon_available() -> bool:
    """Check if Camera Proxy Add-on is available."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{DEFAULT_PROXY_URL}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("status") == "ok"
    except Exception:
        pass
    return False


class XiaomiMiotCameraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Xiaomi MIoT Camera."""

    VERSION = 2  # New version for simplified flow

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._cloud_server: str = "cn"
        self._oauth_info: dict | None = None
        self._cameras: dict = {}
        self._proxy_client: CameraProxyHttpClient | None = None
        self._auth_url: str = ""
        self._ha_callback_url: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - check Add-on and select cloud server."""
        errors: dict[str, str] = {}

        # Check if Add-on is available
        addon_available = await check_addon_available()
        if not addon_available:
            return self.async_abort(
                reason="addon_not_available",
                description_placeholders={
                    "addon_url": "https://github.com/Ricky-Hao/ha-xiaomi-miot-camera"
                }
            )

        if user_input is not None:
            self._cloud_server = user_input[CONF_CLOUD_SERVER]

            # Initialize proxy client
            self._proxy_client = CameraProxyHttpClient(proxy_url=DEFAULT_PROXY_URL)

            # Build HA callback URL
            try:
                ha_url = get_url(self.hass, prefer_external=True)
            except Exception:
                ha_url = get_url(self.hass, prefer_external=False)
            self._ha_callback_url = f"{ha_url}{OAUTH_CALLBACK_PATH}"

            try:
                # Get auth URL from Add-on
                self._auth_url = await self._proxy_client.get_auth_url_async(
                    cloud_server=self._cloud_server,
                    redirect_uri=self._ha_callback_url,
                )
                _LOGGER.info("Generated OAuth URL via Add-on")
                return await self.async_step_auth()
            except Exception as err:
                _LOGGER.error("Failed to get auth URL: %s", err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_CLOUD_SERVER, default="cn"): vol.In(CLOUD_SERVERS),
            }),
            errors=errors,
            description_placeholders={
                "cloud_servers": ", ".join(CLOUD_SERVERS.values()),
            },
        )

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the auth step - user authenticates via OAuth."""
        errors: dict[str, str] = {}

        if user_input is not None:
            code = user_input.get("code", "").strip()
            state = user_input.get("state", "").strip()

            if code and state:
                try:
                    # Send callback to Add-on
                    success = await self._proxy_client.handle_oauth_callback_async(code, state)
                    
                    if success:
                        _LOGGER.info("OAuth authentication successful")
                        
                        # Store minimal oauth info (Add-on manages the actual tokens)
                        self._oauth_info = {
                            "access_token": "managed_by_addon",
                            "refresh_token": "managed_by_addon",
                            "expires_ts": 0,
                        }
                        
                        return await self.async_step_cameras()
                    else:
                        errors["base"] = "invalid_auth"
                except Exception as err:
                    _LOGGER.error("OAuth callback failed: %s", err)
                    errors["base"] = "invalid_auth"
            else:
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="auth",
            data_schema=vol.Schema({
                vol.Optional("code"): str,
                vol.Optional("state"): str,
            }),
            errors=errors,
            description_placeholders={
                "auth_url": self._auth_url,
                "callback_url": self._ha_callback_url,
            },
        )

    async def async_step_auth_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual token input (alternative to OAuth)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            access_token = user_input.get("access_token", "").strip()
            refresh_token = user_input.get("refresh_token", "").strip()

            if access_token:
                try:
                    # Set tokens in Add-on
                    success = await self._proxy_client.set_tokens_async(
                        cloud_server=self._cloud_server,
                        access_token=access_token,
                        refresh_token=refresh_token,
                    )
                    
                    if success:
                        self._oauth_info = {
                            "access_token": access_token,
                            "refresh_token": refresh_token,
                            "expires_ts": 0,
                        }
                        return await self.async_step_cameras()
                    else:
                        errors["base"] = "invalid_auth"
                except Exception as err:
                    _LOGGER.error("Failed to set tokens: %s", err)
                    errors["base"] = "invalid_auth"
            else:
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="auth_manual",
            data_schema=vol.Schema({
                vol.Required("access_token"): str,
                vol.Optional("refresh_token"): str,
            }),
            errors=errors,
        )

    async def async_step_cameras(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle camera selection step."""
        errors: dict[str, str] = {}

        if not self._cameras:
            try:
                # Fetch cameras from Add-on
                cameras = await self._proxy_client.get_cameras_async()
                self._cameras = {
                    did: info.name for did, info in cameras.items()
                }
                _LOGGER.info("Found %d cameras via Add-on", len(self._cameras))
            except Exception as err:
                _LOGGER.error("Failed to get cameras: %s", err)
                errors["base"] = "cannot_connect"

        if user_input is not None:
            selected = user_input.get(CONF_SELECTED_CAMERAS, [])

            # Clean up
            if self._proxy_client:
                await self._proxy_client.close_async()

            # Create config entry
            return self.async_create_entry(
                title="Xiaomi MIoT Camera",
                data={
                    CONF_CLOUD_SERVER: self._cloud_server,
                    CONF_OAUTH_INFO: self._oauth_info,
                    CONF_SELECTED_CAMERAS: selected if selected else list(self._cameras.keys()),
                },
            )

        if not self._cameras:
            return self.async_abort(reason="no_cameras")

        # Let user select cameras
        camera_options = {did: name for did, name in self._cameras.items()}

        return self.async_show_form(
            step_id="cameras",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SELECTED_CAMERAS,
                    default=list(self._cameras.keys()),
                ): cv.multi_select(camera_options),
            }),
            errors=errors,
            description_placeholders={
                "camera_count": str(len(self._cameras)),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> XiaomiMiotCameraOptionsFlow:
        """Get the options flow for this handler."""
        return XiaomiMiotCameraOptionsFlow(config_entry)


class XiaomiMiotCameraOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Xiaomi MIoT Camera."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current cameras from coordinator
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
        if coordinator:
            camera_options = {
                did: data.camera_info.name
                for did, data in coordinator.cameras.items()
            }
        else:
            camera_options = {}

        current_selected = self._config_entry.data.get(CONF_SELECTED_CAMERAS, [])

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SELECTED_CAMERAS,
                    default=current_selected,
                ): cv.multi_select(camera_options) if camera_options else str,
            }),
        )
