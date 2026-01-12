# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""Xiaomi MIoT Camera integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_CLOUD_SERVER,
    CONF_OAUTH_INFO,
    CONF_SELECTED_CAMERAS,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Xiaomi MIoT Camera component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Set up Xiaomi MIoT Camera from a config entry."""
    # Use simplified coordinator that delegates to Add-on
    from .coordinator import XiaomiCameraCoordinator
    
    _LOGGER.info("Setting up Xiaomi MIoT Camera integration")

    # Extract configuration
    cloud_server = entry.data.get(CONF_CLOUD_SERVER, "cn")
    oauth_info = entry.data.get(CONF_OAUTH_INFO)
    selected_cameras = entry.data.get(CONF_SELECTED_CAMERAS, [])

    if not oauth_info:
        _LOGGER.error("Missing OAuth info in config entry")
        return False

    # Create simplified coordinator (uses Add-on for all operations)
    coordinator = XiaomiCameraCoordinator(
        hass=hass,
        cloud_server=cloud_server,
        oauth_info=oauth_info,
        selected_cameras=selected_cameras,
    )

    # Initialize the coordinator
    try:
        await coordinator.async_initialize()
    except Exception as err:
        _LOGGER.error("Failed to initialize Xiaomi MIoT Camera: %s", err)
        return False

    # Store coordinator
    entry.runtime_data = coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info("Xiaomi MIoT Camera integration setup complete")
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Xiaomi MIoT Camera integration")

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Clean up coordinator
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
