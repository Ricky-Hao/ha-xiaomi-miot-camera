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
    from .coordinator import XiaomiCameraCoordinator

    # Extract configuration
    cloud_server = entry.data.get(CONF_CLOUD_SERVER, "cn")
    oauth_info = entry.data.get(CONF_OAUTH_INFO)
    selected_cameras = entry.data.get(CONF_SELECTED_CAMERAS, [])

    if not oauth_info:
        _LOGGER.error("Missing OAuth info in config entry")
        return False

    # Create coordinator (uses Add-on for all operations)
    coordinator = XiaomiCameraCoordinator(
        hass=hass,
        cloud_server=cloud_server,
        oauth_info=oauth_info,
        selected_cameras=selected_cameras,
    )

    try:
        await coordinator.async_initialize()
    except Exception as err:
        _LOGGER.error("Failed to initialize: %s", err)
        return False

    entry.runtime_data = coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info("Xiaomi MIoT Camera setup complete with %d cameras", len(selected_cameras))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry
) -> bool:
    """Remove a config entry from a device."""
    # Allow removal of devices that are no longer selected
    return True
