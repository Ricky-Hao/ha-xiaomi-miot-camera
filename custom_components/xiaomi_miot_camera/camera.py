# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""Camera platform for Xiaomi MIoT Camera integration.

This integration uses direct WebRTC streaming from the Add-on:
- Add-on provides WebRTC streams via WHEP at http://<host>:8889/camera/{did}/{channel}/whep
- Integration handles WebRTC signaling directly
- No HA go2rtc dependency - direct low-latency WebRTC
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import aiohttp
from aiohttp import web

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    async_get_still_stream,
)
from homeassistant.components.camera.webrtc import (
    WebRTCAnswer,
    WebRTCError,
    WebRTCSendMessage,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEFAULT_FRAME_INTERVAL
from .coordinator import XiaomiCameraCoordinator, CameraData

_LOGGER = logging.getLogger(__name__)

# Add-on WebRTC WHEP endpoint
# When running as HA Add-on with host_network, it's accessible at localhost
WEBRTC_BASE_URL = "http://127.0.0.1:8889"


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


class XiaomiMiotCamera(CoordinatorEntity, Camera):
    """Xiaomi MIoT Camera entity with direct WebRTC support.
    
    Streaming architecture:
    - Add-on runs MediaMTX with WebRTC enabled on port 8889
    - FFmpeg transcodes H.265→H.264 and pushes to MediaMTX RTSP
    - MediaMTX converts RTSP to WebRTC (WHEP protocol)
    - This entity handles WebRTC signaling directly via WHEP
    
    Status updates:
    - Inherits from CoordinatorEntity for automatic status polling
    - Coordinator polls Add-on every 10 seconds for camera status
    - is_recording reflects actual streaming status from Add-on
    """

    _attr_has_entity_name = True
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self,
        coordinator: XiaomiCameraCoordinator,
        did: str,
        channel: int,
        camera_data: CameraData,
    ) -> None:
        """Initialize the camera."""
        # Initialize CoordinatorEntity first
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        
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
        
        # WebRTC WHEP URL
        self._whep_url = f"{WEBRTC_BASE_URL}/camera/{self._did}/{self._channel}/whep"

    @property
    def frontend_stream_type(self) -> str:
        """Return the frontend stream type."""
        return "web_rtc"

    async def async_handle_async_webrtc_offer(
        self, offer_sdp: str, session_id: str, send_message: WebRTCSendMessage
    ) -> None:
        """Handle the async WebRTC offer.
        
        This is the new HA WebRTC API. We forward the SDP offer to MediaMTX WHEP
        endpoint and send the answer via the callback.
        """
        # Ensure camera stream is started
        if not self._camera_data.is_streaming:
            _LOGGER.info("Starting camera %s for WebRTC stream", self._did)
            try:
                await self._coordinator.async_start_camera(self._did)
            except Exception as err:
                _LOGGER.error("Failed to start camera %s: %s", self._did, err)
                send_message(WebRTCError("webrtc_offer_failed", f"Failed to start camera: {err}"))
                return
        
        # Send SDP offer to MediaMTX WHEP endpoint
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._whep_url,
                    data=offer_sdp,
                    headers={"Content-Type": "application/sdp"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 201:
                        answer_sdp = await resp.text()
                        _LOGGER.debug("WebRTC answer received for camera %s", self._did)
                        send_message(WebRTCAnswer(answer_sdp))
                    else:
                        error_text = await resp.text()
                        _LOGGER.error(
                            "WebRTC WHEP failed for camera %s: %s %s",
                            self._did, resp.status, error_text
                        )
                        send_message(WebRTCError("webrtc_offer_failed", f"WHEP error: {resp.status}"))
        except Exception as err:
            _LOGGER.error("WebRTC error for camera %s: %s", self._did, err)
            send_message(WebRTCError("webrtc_offer_failed", str(err)))

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
        return True

    @property
    def is_streaming(self) -> bool:
        """Return True if camera is streaming."""
        return self._camera_data.is_streaming

    @property
    def is_recording(self) -> bool:
        """Return True if camera is recording (streaming).
        
        This affects the camera state shown in HA UI:
        - True: shows as 'Recording' (监控中)
        - False: shows as 'Idle' (空闲)
        """
        return self._camera_data.is_streaming

    @property
    def is_on(self) -> bool:
        """Return True if camera is on."""
        return True

    @property
    def frame_interval(self) -> float:
        """Return the interval between frames."""
        return self._frame_interval

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image from the camera."""
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
        """Generate an HTTP MJPEG stream from the camera."""
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
