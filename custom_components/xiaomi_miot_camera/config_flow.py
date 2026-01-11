# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""Config flow for Xiaomi MIoT Camera integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

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
    CONF_UUID,
    CONF_SELECTED_CAMERAS,
    CLOUD_SERVERS,
    OAUTH2_REDIRECT_URI,
    OAUTH_CALLBACK_PATH,
)
from .miot.client import MIoTClient
from .miot.types import MIoTOauthInfo
from .auth_callback import (
    register_pending_flow,
    unregister_pending_flow,
    get_received_callback,
    clear_received_callback,
)

_LOGGER = logging.getLogger(__name__)


class XiaomiMiotCameraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Xiaomi MIoT Camera."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._uuid: str = ""
        self._cloud_server: str = "cn"
        self._oauth_info: dict | None = None
        self._cameras: dict = {}
        self._client: MIoTClient | None = None
        self._auth_url: str = ""
        self._oauth_state: str = ""
        self._ha_callback_url: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - select cloud server."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._cloud_server = user_input[CONF_CLOUD_SERVER]
            self._uuid = uuid4().hex

            # Create client and generate auth URL
            try:
                self._client = MIoTClient(
                    uuid=self._uuid,
                    redirect_uri=OAUTH2_REDIRECT_URI,
                    cloud_server=self._cloud_server,
                    loop=self.hass.loop,
                )
                await self._client.init_async()

                # Generate OAuth URL and get the state
                self._auth_url = await self._client.gen_oauth_url_async()
                
                # Extract state from the auth URL
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(self._auth_url)
                params = parse_qs(parsed.query)
                self._oauth_state = params.get("state", [""])[0]
                
                # Build the HA callback URL
                try:
                    ha_url = get_url(self.hass, prefer_external=True)
                except Exception:
                    ha_url = get_url(self.hass, prefer_external=False)
                self._ha_callback_url = f"{ha_url}{OAUTH_CALLBACK_PATH}"
                
                _LOGGER.info("Generated OAuth URL: %s", self._auth_url)
                _LOGGER.info("HA callback URL: %s", self._ha_callback_url)

                return await self.async_step_auth()

            except Exception as err:
                _LOGGER.error("Failed to initialize: %s", err)
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
        """Handle the auth step - wait for OAuth callback or manual input."""
        errors: dict[str, str] = {}

        # Register this flow for callback
        if self._oauth_state:
            register_pending_flow(self._oauth_state, self.flow_id)

        # Check if we received a callback
        if user_input is None and self._oauth_state:
            callback_data = get_received_callback(self._oauth_state)
            if callback_data:
                user_input = callback_data
                clear_received_callback(self._oauth_state)
                _LOGGER.info("Using received callback data")

        if user_input is not None:
            code = user_input.get("code", "").strip()
            state = user_input.get("state", "").strip()

            if code and state:
                try:
                    # Unregister pending flow
                    if self._oauth_state:
                        unregister_pending_flow(self._oauth_state)
                    
                    # Exchange code for token
                    oauth_info = await self._client.get_access_token_async(code, state)
                    self._oauth_info = oauth_info.model_dump()

                    _LOGGER.info("OAuth authentication successful")

                    # Get camera list
                    return await self.async_step_cameras()

                except Exception as err:
                    _LOGGER.error("OAuth authentication failed: %s", err)
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

    async def async_step_cameras(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle camera selection step."""
        errors: dict[str, str] = {}

        if not self._cameras:
            try:
                # Fetch cameras
                cameras = await self._client.get_cameras_async()
                self._cameras = {
                    did: info.name for did, info in cameras.items()
                }
                _LOGGER.info("Found %d cameras", len(self._cameras))
            except Exception as err:
                _LOGGER.error("Failed to get cameras: %s", err)
                errors["base"] = "cannot_connect"

        if user_input is not None:
            selected = user_input.get(CONF_SELECTED_CAMERAS, [])

            # Clean up client before finishing
            if self._client:
                try:
                    await self._client.deinit_async()
                except Exception:
                    pass

            # Create config entry
            return self.async_create_entry(
                title="Xiaomi MIoT Camera",
                data={
                    CONF_UUID: self._uuid,
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
