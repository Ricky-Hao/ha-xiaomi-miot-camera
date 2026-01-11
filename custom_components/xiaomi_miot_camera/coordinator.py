# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""Data coordinator for Xiaomi MIoT Camera integration."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .miot.client import MIoTClient
from .miot.camera_backend import CameraBackend, create_camera_backend, FORCE_PROXY_MODE
from .miot.types import MIoTOauthInfo, MIoTCameraInfo, MIoTCameraStatus

from .const import (
    DOMAIN,
    DEFAULT_IMG_BUFFER_SIZE,
    DEFAULT_IMG_BUFFER_TTL,
    OAUTH2_REDIRECT_URI,
    CONF_PROXY_URL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class CameraFrameBuffer:
    """Buffer for camera frames."""
    max_size: int = DEFAULT_IMG_BUFFER_SIZE
    ttl: int = DEFAULT_IMG_BUFFER_TTL
    _buffer: deque = field(default_factory=lambda: deque(maxlen=DEFAULT_IMG_BUFFER_SIZE))
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self):
        self._buffer = deque(maxlen=self.max_size)

    async def put(self, frame: bytes) -> None:
        """Add a frame to the buffer."""
        async with self._lock:
            self._buffer.append((frame, time.time()))

    async def get_latest(self) -> Optional[bytes]:
        """Get the latest frame."""
        async with self._lock:
            self._filter_old()
            if self._buffer:
                return self._buffer[-1][0]
            return None

    async def get_recent(self, n: int) -> List[bytes]:
        """Get the most recent n frames."""
        async with self._lock:
            self._filter_old()
            actual_n = min(n, len(self._buffer))
            return [frame for frame, _ in list(self._buffer)[-actual_n:]]

    def _filter_old(self) -> None:
        """Filter out old frames."""
        current_time = time.time()
        while self._buffer and current_time - self._buffer[0][1] > self.ttl:
            self._buffer.popleft()


@dataclass
class CameraData:
    """Data for a single camera."""
    camera_info: MIoTCameraInfo
    frame_buffers: Dict[int, CameraFrameBuffer] = field(default_factory=dict)
    status: MIoTCameraStatus = MIoTCameraStatus.DISCONNECTED
    is_streaming: bool = False


class XiaomiCameraCoordinator(DataUpdateCoordinator):
    """Coordinator for Xiaomi MIoT Camera."""

    def __init__(
        self,
        hass: HomeAssistant,
        uuid: str,
        cloud_server: str,
        oauth_info: dict,
        selected_cameras: List[str],
        frame_interval: int,
        proxy_url: Optional[str] = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
        )
        self._uuid = uuid
        self._cloud_server = cloud_server
        self._oauth_info = MIoTOauthInfo.model_validate(oauth_info)
        self._selected_cameras = selected_cameras
        self._frame_interval = frame_interval
        self._proxy_url = proxy_url or "ws://127.0.0.1:8765/ws"

        self._client: Optional[MIoTClient] = None
        self._camera_backend: Optional[CameraBackend] = None
        self._cameras: Dict[str, CameraData] = {}
        self._initialized = False

    @property
    def cameras(self) -> Dict[str, CameraData]:
        """Return camera data."""
        return self._cameras

    @property
    def client(self) -> Optional[MIoTClient]:
        """Return MIoT client."""
        return self._client

    async def async_initialize(self) -> None:
        """Initialize the coordinator and connect to cameras."""
        if self._initialized:
            return

        _LOGGER.info("Initializing Xiaomi MIoT Camera coordinator")

        # Check if we should use proxy mode (skip native camera client)
        import os
        skip_camera = FORCE_PROXY_MODE or os.environ.get("XIAOMI_CAMERA_FORCE_PROXY", "").lower() in ("1", "true", "yes")
        
        # Create MIoT client
        self._client = MIoTClient(
            uuid=self._uuid,
            redirect_uri=OAUTH2_REDIRECT_URI,
            oauth_info=self._oauth_info.model_dump(),
            cloud_server=self._cloud_server,
            loop=self.hass.loop,
        )

        # Initialize client (skip camera if using proxy mode)
        await self._client.init_async(skip_camera=skip_camera)

        # Create camera backend (auto-detects native vs proxy)
        try:
            self._camera_backend = await create_camera_backend(
                proxy_url=self._proxy_url,
                loop=self.hass.loop
            )
            version = await self._camera_backend.init_async(
                cloud_server=self._cloud_server,
                access_token=self._oauth_info.access_token,
                frame_interval=self._frame_interval
            )
            _LOGGER.info("Camera backend initialized, version: %s", version)
        except Exception as err:
            _LOGGER.error("Failed to initialize camera backend: %s", err)
            raise

        # Get camera list
        cameras = await self._client.get_cameras_async()
        _LOGGER.info("Found %d cameras", len(cameras))

        # Filter selected cameras
        for did, camera_info in cameras.items():
            if not self._selected_cameras or did in self._selected_cameras:
                self._cameras[did] = CameraData(camera_info=camera_info)
                _LOGGER.info("Added camera: %s (%s)", camera_info.name, did)

        # Start camera streams
        for did, camera_data in self._cameras.items():
            await self._start_camera_stream(did, camera_data)

        self._initialized = True
        _LOGGER.info("Coordinator initialization complete")

    async def _start_camera_stream(self, did: str, camera_data: CameraData) -> None:
        """Start streaming for a camera."""
        try:
            camera_info = camera_data.camera_info

            # Create camera instance via backend
            await self._camera_backend.create_camera_async(
                camera_info=camera_info,
                frame_interval=self._frame_interval,
            )

            # Start the camera with auto-reconnect
            await self._camera_backend.start_camera_async(
                did=did,
                enable_reconnect=True
            )

            # Create frame buffers for each channel
            channel_count = camera_info.channel_count or 1
            for channel in range(channel_count):
                camera_data.frame_buffers[channel] = CameraFrameBuffer()

                # Register frame callback
                async def on_frame(
                    frame_did: str, data: bytes, ts: int, ch: int,
                    target_did: str = did, target_channel: int = channel
                ) -> None:
                    if target_did in self._cameras:
                        buffer = self._cameras[target_did].frame_buffers.get(target_channel)
                        if buffer:
                            await buffer.put(data)

                await self._camera_backend.register_decode_jpg_async(
                    did=did,
                    callback=on_frame,
                    channel=channel,
                )

            # Register status callback
            async def on_status_changed(status_did: str, status: MIoTCameraStatus) -> None:
                if status_did in self._cameras:
                    self._cameras[status_did].status = status
                    self._cameras[status_did].is_streaming = (
                        status == MIoTCameraStatus.CONNECTED
                    )
                    _LOGGER.info("Camera %s status changed to %s", status_did, status)

            await self._camera_backend.register_status_changed_async(
                did=did,
                callback=on_status_changed
            )

            camera_data.is_streaming = True
            _LOGGER.info("Started streaming for camera %s", did)

        except Exception as err:
            _LOGGER.error("Failed to start camera stream for %s: %s", did, err)
            camera_data.is_streaming = False

    async def async_get_frame(self, did: str, channel: int = 0) -> Optional[bytes]:
        """Get the latest frame for a camera."""
        camera_data = self._cameras.get(did)
        if not camera_data:
            return None

        buffer = camera_data.frame_buffers.get(channel)
        if not buffer:
            return None

        return await buffer.get_latest()

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        _LOGGER.info("Shutting down Xiaomi MIoT Camera coordinator")

        # Stop all camera instances via backend
        for did in self._cameras.keys():
            try:
                await self._camera_backend.stop_camera_async(did)
                await self._camera_backend.destroy_camera_async(did)
            except Exception as err:
                _LOGGER.error("Error stopping camera %s: %s", did, err)

        # Deinit camera backend
        if self._camera_backend:
            try:
                await self._camera_backend.deinit_async()
            except Exception as err:
                _LOGGER.error("Error deinitializing camera backend: %s", err)

        # Deinit client
        if self._client:
            try:
                await self._client.deinit_async()
            except Exception as err:
                _LOGGER.error("Error deinitializing client: %s", err)

        self._cameras.clear()
        self._initialized = False

    async def async_refresh_token(self) -> bool:
        """Refresh OAuth token."""
        if not self._client or not self._oauth_info.refresh_token:
            return False

        try:
            new_oauth_info = await self._client.refresh_access_token_async(
                self._oauth_info.refresh_token
            )
            self._oauth_info = new_oauth_info
            _LOGGER.info("OAuth token refreshed successfully")
            return True
        except Exception as err:
            _LOGGER.error("Failed to refresh OAuth token: %s", err)
            return False

    async def _async_update_data(self) -> Dict[str, Any]:
        """Update data (called by DataUpdateCoordinator)."""
        # Return current camera states
        return {
            did: {
                "name": data.camera_info.name,
                "status": data.status,
                "is_streaming": data.is_streaming,
                "channel_count": data.camera_info.channel_count or 1,
            }
            for did, data in self._cameras.items()
        }
