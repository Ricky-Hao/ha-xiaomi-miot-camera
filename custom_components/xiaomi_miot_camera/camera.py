# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""Camera platform for Xiaomi MIoT Camera integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import aiohttp
from aiohttp import web
from webrtc_models import RTCIceCandidateInit

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    StreamType,
    WebRTCAnswer,
    WebRTCError,
    WebRTCSendMessage,
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

# MediaMTX WebRTC endpoint (WHEP protocol)
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


class XiaomiMiotCamera(Camera):
    """Xiaomi MIoT Camera entity."""

    _attr_has_entity_name = True
    # Support STREAM feature (required for WebRTC)
    _attr_supported_features = CameraEntityFeature.STREAM
    # Use WebRTC for instant playback (no HA transcoding)
    _attr_frontend_stream_type = StreamType.WEB_RTC

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

        # Frame interval in seconds
        self._frame_interval = DEFAULT_FRAME_INTERVAL / 1000.0
        
        # WebRTC WHEP endpoint
        self._whep_url = f"{WEBRTC_BASE_URL}/camera/{self._did}/{self._channel}/whep"
        
        # Track active WebRTC sessions
        self._webrtc_sessions: dict[str, str] = {}  # session_id -> whep_resource_url

    async def stream_source(self) -> str | None:
        """Return the stream source.
        
        This camera only supports WebRTC streaming, not HLS/RTSP.
        Return None to indicate HLS streaming is not available.
        Services like play_stream that require HLS will not work.
        """
        return None

    async def async_handle_async_webrtc_offer(
        self, offer_sdp: str, session_id: str, send_message: WebRTCSendMessage
    ) -> None:
        """Handle the WebRTC offer and return the answer via callback.
        
        Uses MediaMTX's WHEP (WebRTC-HTTP Egress Protocol) endpoint for
        instant low-latency streaming without HA transcoding.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._whep_url,
                    data=offer_sdp,
                    headers={
                        "Content-Type": "application/sdp",
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 201:
                        answer_sdp = await resp.text()
                        # Store the resource URL for later cleanup
                        resource_url = resp.headers.get("Location")
                        if resource_url:
                            self._webrtc_sessions[session_id] = resource_url
                        _LOGGER.debug(
                            "WebRTC offer/answer exchange successful for camera %s (session: %s)",
                            self._did, session_id
                        )
                        send_message(WebRTCAnswer(answer_sdp))
                    else:
                        error = await resp.text()
                        _LOGGER.error(
                            "WebRTC WHEP request failed: %s - %s",
                            resp.status, error
                        )
                        send_message(WebRTCError("webrtc_offer_failed", f"WHEP error: {resp.status}"))
        except asyncio.TimeoutError:
            _LOGGER.error("WebRTC offer timeout for camera %s", self._did)
            send_message(WebRTCError("webrtc_offer_failed", "Connection timeout"))
        except Exception as err:
            _LOGGER.error("WebRTC offer handling failed for camera %s: %s", self._did, err)
            send_message(WebRTCError("webrtc_offer_failed", str(err)))

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: RTCIceCandidateInit
    ) -> None:
        """Handle a WebRTC ICE candidate.
        
        MediaMTX WHEP handles ICE negotiation internally, so we just log this.
        """
        _LOGGER.debug(
            "Received ICE candidate for camera %s session %s (handled by MediaMTX)",
            self._did, session_id
        )

    def close_webrtc_session(self, session_id: str) -> None:
        """Close a WebRTC session.
        
        Send DELETE to WHEP resource to clean up MediaMTX session.
        """
        resource_url = self._webrtc_sessions.pop(session_id, None)
        if resource_url:
            _LOGGER.debug("Closing WebRTC session %s for camera %s", session_id, self._did)
            # Fire and forget the cleanup - don't block
            asyncio.create_task(self._close_whep_session(resource_url))

    async def _close_whep_session(self, resource_url: str) -> None:
        """Send DELETE to WHEP resource to clean up session."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    resource_url,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status in (200, 204):
                        _LOGGER.debug("Closed WHEP session: %s", resource_url)
                    else:
                        _LOGGER.warning("Failed to close WHEP session: %s", resp.status)
        except Exception as err:
            _LOGGER.warning("Error closing WHEP session: %s", err)

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
        # The actual streaming state is indicated by is_streaming
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
        """Turn on camera (not supported - always on)."""
        _LOGGER.debug("Turn on requested for camera %s (not supported)", self._did)

    async def async_turn_off(self) -> None:
        """Turn off camera (not supported)."""
        _LOGGER.debug("Turn off requested for camera %s (not supported)", self._did)
