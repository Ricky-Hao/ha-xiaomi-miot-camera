# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""Camera platform for Xiaomi MIoT Camera integration.

This integration uses HA's native go2rtc for WebRTC streaming:
- Add-on provides RTSP streams at rtsp://<host>:8554/camera/{did}/{channel}
- Integration returns RTSP URL via stream_source()
- HA go2rtc handles WebRTC conversion automatically
"""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    async_get_still_stream,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEFAULT_FRAME_INTERVAL
# Use the simplified coordinator that delegates to Add-on
from .coordinator import XiaomiCameraCoordinator, CameraData

_LOGGER = logging.getLogger(__name__)

# Add-on RTSP server address
# When running as HA Add-on with host_network, it's accessible at localhost
RTSP_BASE_URL = "rtsp://127.0.0.1:8554"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Xiaomi MIoT Camera from a config entry."""
    coordinator: XiaomiCameraCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []

    for did, camera_data in coordinator.cameras.items():
        camera_info = camera_data.camera_info
        channel_count = camera_info.channel_count or 1

        for channel in range(channel_count):
            entities.append(
                XiaomiMiotCamera(
                    coordinator=coordinator,
                    did=did,
                    channel=channel,
                    camera_data=camera_data,
                )
            )

    async_add_entities(entities)
    _LOGGER.info("Added %d camera entities", len(entities))


class XiaomiMiotCamera(Camera):
    """Xiaomi MIoT Camera entity.
    
    Streaming architecture:
    - Add-on runs MediaMTX as RTSP server on port 8554
    - FFmpeg pushes camera H.265/H.264 streams to MediaMTX
    - This entity returns RTSP URL via stream_source()
    - HA's go2rtc converts RTSP to WebRTC for low-latency playback
    """

    _attr_has_entity_name = True
    # Support STREAM feature for go2rtc integration
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self,
        coordinator: XiaomiCameraCoordinator,
        did: str,
        channel: int,
        camera_data: CameraData,
    ) -> None:
        """Initialize the camera."""
        super().__init__()
        self._coordinator = coordinator
        self._did = did
        self._channel = channel
        self._camera_data = camera_data
        self._camera_info = camera_data.camera_info

        # Set unique ID
        self._attr_unique_id = f"{did}_{channel}"

        # Set name
        if self._camera_info.channel_count and self._camera_info.channel_count > 1:
            self._attr_name = f"{self._camera_info.name} Channel {channel + 1}"
        else:
            self._attr_name = self._camera_info.name

        # Frame interval in seconds (for MJPEG fallback)
        self._frame_interval = DEFAULT_FRAME_INTERVAL / 1000.0
        
        # RTSP stream URL for go2rtc
        self._rtsp_url = f"{RTSP_BASE_URL}/camera/{self._did}/{self._channel}"

    async def stream_source(self) -> str | None:
        """Return the RTSP stream source for go2rtc.
        
        HA's go2rtc will:
        1. Connect to this RTSP URL
        2. Auto-detect codec (H.265/H.264)
        3. Convert to WebRTC for browser playback
        
        The camera stream is started automatically when needed.
        """
        # Ensure camera stream is started
        if not self._camera_data.is_streaming:
            _LOGGER.info("Starting camera %s for stream access", self._did)
            try:
                await self._coordinator.async_start_camera(self._did)
            except Exception as err:
                _LOGGER.error("Failed to start camera %s: %s", self._did, err)
                return None
        
        _LOGGER.debug("Returning RTSP URL for camera %s: %s", self._did, self._rtsp_url)
        return self._rtsp_url

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._did)},
            name=self._camera_info.name,
            manufacturer="Xiaomi",
            model=self._camera_info.model,
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Camera is available as long as we're connected to the backend
        return True

    @property
    def is_streaming(self) -> bool:
        """Return True if camera is streaming."""
        return self._camera_data.is_streaming

    @property
    def is_on(self) -> bool:
        """Return True if camera is on."""
        return True  # Camera is always on

    @property
    def frame_interval(self) -> float:
        """Return the interval between frames."""
        return self._frame_interval

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image from the camera.
        
        Uses the Add-on's snapshot API endpoint.
        """
        try:
            frame = await self._coordinator.async_get_frame(self._did, self._channel)
            if frame:
                _LOGGER.debug(
                    "Got frame for camera %s channel %d: %d bytes",
                    self._did, self._channel, len(frame)
                )
                return frame
            else:
                _LOGGER.debug(
                    "No frame available for camera %s channel %d",
                    self._did, self._channel
                )
                return None
        except Exception as err:
            _LOGGER.error("Error getting frame for camera %s: %s", self._did, err)
            return None

    async def handle_async_mjpeg_stream(
        self, request: web.Request
    ) -> web.StreamResponse | None:
        """Generate an HTTP MJPEG stream from the camera.
        
        This is a fallback for clients that don't support WebRTC.
        """
        if not self.available:
            _LOGGER.warning("Camera %s is not available for streaming", self._did)
            return None

        return await async_get_still_stream(
            request,
            self._async_get_image,
            "image/jpeg",
            self._frame_interval,
        )

    async def _async_get_image(self) -> bytes | None:
        """Get image for MJPEG stream."""
        return await self.async_camera_image()

    async def async_turn_on(self) -> None:
        """Turn on camera (start streaming)."""
        _LOGGER.debug("Turn on requested for camera %s", self._did)
        try:
            await self._coordinator.async_start_camera(self._did)
        except Exception as err:
            _LOGGER.error("Failed to turn on camera %s: %s", self._did, err)

    async def async_turn_off(self) -> None:
        """Turn off camera (stop streaming)."""
        _LOGGER.debug("Turn off requested for camera %s", self._did)
        try:
            await self._coordinator.async_stop_camera(self._did)
        except Exception as err:
            _LOGGER.error("Failed to turn off camera %s: %s", self._did, err)
