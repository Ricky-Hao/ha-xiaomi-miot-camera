# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""Xiaomi MIoT Camera integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

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

    # Clean up entities for cameras that are no longer selected
    _cleanup_removed_cameras(hass, entry, selected_cameras)

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


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry
) -> bool:
    """Remove a config entry from a device."""
    # Allow removal of devices that are no longer selected
    return True


def _cleanup_removed_cameras(
    hass: HomeAssistant, entry: ConfigEntry, selected_cameras: list[str]
) -> None:
    """Remove entities for cameras that are no longer selected."""
    entity_registry = er.async_get(hass)
    
    # Find all entities for this config entry
    entities_to_remove = []
    for entity_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        # Entity unique_id format is "{did}_{channel}"
        unique_id = entity_entry.unique_id
        if unique_id:
            # Extract did from unique_id (format: "did_channel")
            did = unique_id.rsplit("_", 1)[0] if "_" in unique_id else unique_id
            
            # If this camera is no longer selected, mark for removal
            if did not in selected_cameras:
                entities_to_remove.append(entity_entry.entity_id)
                _LOGGER.info("Marking entity %s for removal (camera %s no longer selected)", 
                           entity_entry.entity_id, did)
    
    # Remove the entities
    for entity_id in entities_to_remove:
        entity_registry.async_remove(entity_id)
        _LOGGER.info("Removed entity: %s", entity_id)
