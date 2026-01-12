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

import base64
import json
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    CONF_CLOUD_SERVER,
    CONF_OAUTH_INFO,
    CONF_SELECTED_CAMERAS,
    CONF_VIDEO_QUALITY,
    CLOUD_SERVER,
    DEFAULT_VIDEO_QUALITY,
    VIDEO_QUALITY_LOW,
    VIDEO_QUALITY_HIGH,
    VIDEO_QUALITY_SUPER,
    VIDEO_QUALITY_ULTRA,
)
from .miot.proxy_client import CameraProxyHttpClient

_LOGGER = logging.getLogger(__name__)

# Default Add-on URL
DEFAULT_PROXY_URL = "http://127.0.0.1:8765"

# Video quality options for selector
VIDEO_QUALITY_OPTIONS = {
    VIDEO_QUALITY_LOW: "Low (1)",
    VIDEO_QUALITY_HIGH: "High (3)",
    VIDEO_QUALITY_SUPER: "Super (4) - Experimental",
    VIDEO_QUALITY_ULTRA: "Ultra (5) - Experimental",
}


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
        self._oauth_redirect_uri: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - check Add-on and proceed to auth."""
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
            # Only cn region is supported
            self._cloud_server = CLOUD_SERVER

            # Initialize proxy client
            self._proxy_client = CameraProxyHttpClient(proxy_url=DEFAULT_PROXY_URL)

            # Use Xiaomi's official redirect URI (required by OAuth server)
            # Users will be redirected to Xiaomi's page which shows the code
            self._oauth_redirect_uri = "https://mico.api.mijia.tech/login_redirect"

            try:
                # Get auth URL from Add-on
                self._auth_url = await self._proxy_client.get_auth_url_async(
                    cloud_server=self._cloud_server,
                    redirect_uri=self._oauth_redirect_uri,
                )
                _LOGGER.info("Generated OAuth URL via Add-on")
                return await self.async_step_auth()
            except Exception as err:
                _LOGGER.error("Failed to get auth URL: %s", err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the auth step - user pastes base64 OAuth result."""
        errors: dict[str, str] = {}

        if user_input is not None:
            oauth_result = user_input.get("oauth_result", "").strip()

            if oauth_result:
                try:
                    # Decode base64 string
                    decoded = base64.b64decode(oauth_result).decode("utf-8")
                    oauth_data = json.loads(decoded)
                    
                    code = oauth_data.get("code", "").strip()
                    state = oauth_data.get("state", "").strip()
                    
                    if code and state:
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
                    else:
                        _LOGGER.error("Missing code or state in OAuth result")
                        errors["base"] = "invalid_auth"
                except (ValueError, json.JSONDecodeError) as err:
                    _LOGGER.error("Failed to decode OAuth result: %s", err)
                    errors["base"] = "invalid_oauth_result"
                except Exception as err:
                    _LOGGER.error("OAuth callback failed: %s", err)
                    errors["base"] = "invalid_auth"
            else:
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="auth",
            data_schema=vol.Schema({
                vol.Required("oauth_result"): str,
            }),
            errors=errors,
            description_placeholders={
                "auth_url": self._auth_url,
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
        errors: dict[str, str] = {}
        
        # Get ALL cameras from Add-on (not just selected ones)
        camera_options = {}
        try:
            proxy_client = CameraProxyHttpClient(proxy_url=DEFAULT_PROXY_URL)
            all_cameras = await proxy_client.get_cameras_async()
            await proxy_client.close_async()
            
            camera_options = {
                did: camera.name
                for did, camera in all_cameras.items()
            }
            _LOGGER.debug("Options flow: found %d cameras from Add-on", len(camera_options))
        except Exception as err:
            _LOGGER.error("Failed to get cameras from Add-on: %s", err)
            errors["base"] = "cannot_connect"
        
        if user_input is not None and not errors:
            new_selected = user_input.get(CONF_SELECTED_CAMERAS, [])
            new_quality = user_input.get(CONF_VIDEO_QUALITY, DEFAULT_VIDEO_QUALITY)
            _LOGGER.debug("Options flow: user submitted, new_selected = %s, quality = %d", new_selected, new_quality)
            
            # Remove entities and devices for cameras that are no longer selected
            await self._cleanup_removed_cameras(new_selected)
            
            # Update config entry data with new selection
            new_data = dict(self._config_entry.data)
            new_data[CONF_SELECTED_CAMERAS] = new_selected
            _LOGGER.debug("Options flow: updating config entry data")
            
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data=new_data,
                options={CONF_VIDEO_QUALITY: new_quality},
            )
            
            # Reload the integration to apply changes
            _LOGGER.debug("Options flow: reloading integration")
            await self.hass.config_entries.async_reload(self._config_entry.entry_id)
            
            return self.async_create_entry(title="", data={})

        current_selected = self._config_entry.data.get(CONF_SELECTED_CAMERAS, [])
        current_quality = self._config_entry.options.get(CONF_VIDEO_QUALITY, DEFAULT_VIDEO_QUALITY)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SELECTED_CAMERAS,
                    default=current_selected,
                ): cv.multi_select(camera_options) if camera_options else str,
                vol.Optional(
                    CONF_VIDEO_QUALITY,
                    default=current_quality,
                ): vol.In(VIDEO_QUALITY_OPTIONS),
            }),
            errors=errors,
        )

    async def _cleanup_removed_cameras(self, new_selected: list[str]) -> None:
        """Remove entities and devices for cameras that are no longer selected."""
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        
        _LOGGER.debug("Cleanup: new_selected cameras = %s", new_selected)
        
        # Find all entities for this config entry
        entities_to_remove = []
        # Track which devices belong to removed cameras and all their entities
        device_entity_count: dict[str, int] = {}  # device_id -> total entity count
        device_removed_count: dict[str, int] = {}  # device_id -> removed entity count
        devices_to_remove: set[str] = set()
        
        all_entities = list(er.async_entries_for_config_entry(
            entity_registry, self._config_entry.entry_id
        ))
        _LOGGER.debug("Cleanup: found %d entities for this config entry", len(all_entities))
        
        # First pass: count entities per device and identify entities to remove
        for entity_entry in all_entities:
            device_id = entity_entry.device_id
            if device_id:
                device_entity_count[device_id] = device_entity_count.get(device_id, 0) + 1
            
            # Entity unique_id format is "{did}_{channel}"
            unique_id = entity_entry.unique_id
            if not unique_id:
                continue
                
            # Extract did from unique_id (format: "did_channel")
            # did is typically a number, channel is 0, 1, etc.
            parts = unique_id.rsplit("_", 1)
            did = parts[0] if len(parts) == 2 else unique_id
            
            # If this camera is no longer selected, mark for removal
            if did not in new_selected:
                entities_to_remove.append(entity_entry.entity_id)
                if device_id:
                    device_removed_count[device_id] = device_removed_count.get(device_id, 0) + 1
                _LOGGER.debug("Will remove entity %s (camera %s no longer selected)", 
                              entity_entry.entity_id, did)
        
        # Determine which devices should be removed (all their entities are being removed)
        for device_id, total_count in device_entity_count.items():
            removed_count = device_removed_count.get(device_id, 0)
            if removed_count >= total_count:
                devices_to_remove.add(device_id)
                _LOGGER.debug("Device %s will be removed (all %d entities removed)", 
                             device_id, total_count)
        
        _LOGGER.debug("Cleanup: %d entities to remove, %d devices to remove", 
                     len(entities_to_remove), len(devices_to_remove))
        
        # Remove the entities first
        for entity_id in entities_to_remove:
            _LOGGER.debug("Removing entity: %s", entity_id)
            entity_registry.async_remove(entity_id)
        
        # Remove devices that have no remaining entities
        for device_id in devices_to_remove:
            device_entry = device_registry.async_get(device_id)
            if device_entry:
                _LOGGER.info("Removing device: %s (%s)", device_entry.name, device_id)
                device_registry.async_remove_device(device_id)
