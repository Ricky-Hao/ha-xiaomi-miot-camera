# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""Simplified coordinator for Xiaomi MIoT Camera integration.

This version relies on the Camera Proxy Add-on for all camera operations.
The Add-on handles:
- OAuth authentication
- Device discovery  
- Camera streaming (WebRTC)
- Snapshot generation

The Integration just needs to:
- Pass OAuth tokens to Add-on
- Get camera list from Add-on
- Handle WebRTC signaling
- Fetch snapshots via HTTP
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .miot.camera_backend import CameraBackend, check_proxy_available
from .miot.types import MIoTOauthInfo, MIoTCameraInfo, MIoTCameraStatus, MIoTCameraVideoQuality

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Default Add-on URL
DEFAULT_PROXY_URL = "http://127.0.0.1:8765"


@dataclass
class CameraData:
    """Data for a single camera."""
    camera_info: MIoTCameraInfo
    status: MIoTCameraStatus = MIoTCameraStatus.DISCONNECTED
    is_streaming: bool = False


class XiaomiCameraCoordinator(DataUpdateCoordinator):
    """Simplified coordinator for Xiaomi MIoT Camera.
    
    All camera logic is delegated to the Camera Proxy Add-on.
    This coordinator just manages the connection and provides data to entities.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        cloud_server: str,
        oauth_info: dict,
        selected_cameras: List[str],
        proxy_url: Optional[str] = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
        )
        self._cloud_server = cloud_server
        self._oauth_info = MIoTOauthInfo.model_validate(oauth_info)
        self._selected_cameras = selected_cameras
        self._proxy_url = proxy_url or DEFAULT_PROXY_URL

        self._backend: Optional[CameraBackend] = None
        self._cameras: Dict[str, CameraData] = {}
        self._initialized = False

    @property
    def cameras(self) -> Dict[str, CameraData]:
        """Return camera data."""
        return self._cameras

    @property
    def proxy_url(self) -> str:
        """Return proxy URL."""
        return self._proxy_url

    async def async_initialize(self) -> None:
        """Initialize the coordinator."""
        if self._initialized:
            return

        _LOGGER.info("Initializing Xiaomi MIoT Camera coordinator")

        # Check if Add-on is available
        if not await check_proxy_available(self._proxy_url):
            raise RuntimeError(
                "Camera Proxy Add-on not available. "
                "Please install and start the 'Xiaomi Camera Proxy' add-on."
            )

        # Create backend
        self._backend = CameraBackend(proxy_url=self._proxy_url)
        
        # Initialize backend with tokens
        version = await self._backend.init_async(
            cloud_server=self._cloud_server,
            access_token=self._oauth_info.access_token,
            refresh_token=self._oauth_info.refresh_token,
            expires_ts=self._oauth_info.expires_ts,
        )
        _LOGGER.info("Camera Proxy Add-on version: %s", version)

        # Get cameras from Add-on (it handles discovery)
        cameras = await self._backend.get_cameras_async()
        _LOGGER.info("Found %d cameras from Add-on", len(cameras))

        # Filter selected cameras
        for did, camera_info in cameras.items():
            if not self._selected_cameras or did in self._selected_cameras:
                self._cameras[did] = CameraData(camera_info=camera_info)
                _LOGGER.info("Added camera: %s (%s)", camera_info.name, did)

        # Don't start cameras here - they will be started on-demand when WebRTC stream is requested
        # This makes integration setup much faster
        
        self._initialized = True
        _LOGGER.info("Coordinator initialization complete (cameras will start on-demand)")

    async def _start_camera(self, did: str) -> None:
        """Start streaming a camera."""
        if did not in self._cameras:
            return

        try:
            # Start camera via Add-on (ensures WebRTC stream is ready)
            await self._backend.start_camera_async(
                did=did,
                quality=MIoTCameraVideoQuality.HIGH,
            )
            
            self._cameras[did].is_streaming = True
            self._cameras[did].status = MIoTCameraStatus.CONNECTED
            
            _LOGGER.info("Started camera %s", did)
            
        except Exception as err:
            _LOGGER.error("Failed to start camera %s: %s", did, err)
            self._cameras[did].status = MIoTCameraStatus.ERROR

    async def async_start_camera(self, did: str) -> None:
        """Start streaming a camera (public method for entities to call)."""
        await self._start_camera(did)

    async def async_stop_camera(self, did: str) -> None:
        """Stop streaming a camera."""
        if did not in self._cameras:
            _LOGGER.warning("Camera %s not found", did)
            return
        
        try:
            if self._backend:
                await self._backend.stop_camera_async(did)
            
            self._cameras[did].is_streaming = False
            self._cameras[did].status = MIoTCameraStatus.DISCONNECTED
            
            _LOGGER.info("Stopped camera %s", did)
            
        except Exception as err:
            _LOGGER.error("Failed to stop camera %s: %s", did, err)

    async def async_get_frame(self, did: str, channel: int = 0) -> Optional[bytes]:
        """Get a snapshot frame for a camera."""
        if self._backend:
            return await self._backend.get_snapshot_async(did, channel)
        return None

    async def async_get_status(self, did: str) -> MIoTCameraStatus:
        """Get camera status."""
        if self._backend:
            return await self._backend.get_camera_status_async(did)
        return MIoTCameraStatus.DISCONNECTED

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        _LOGGER.info("Shutting down Xiaomi MIoT Camera coordinator")

        # Stop all cameras
        for did in self._cameras:
            try:
                if self._backend:
                    await self._backend.stop_camera_async(did)
            except Exception as err:
                _LOGGER.debug("Error stopping camera %s: %s", did, err)

        # Close backend
        if self._backend:
            await self._backend.deinit_async()

        self._cameras.clear()
        self._initialized = False

    async def async_refresh_token(self) -> bool:
        """Refresh OAuth token via Add-on."""
        # The Add-on handles token refresh internally
        # We can just tell it to refresh
        try:
            from .miot.proxy_client import CameraProxyHttpClient
            client = CameraProxyHttpClient(proxy_url=self._proxy_url)
            result = await client.refresh_tokens_async()
            await client.close_async()
            return result
        except Exception as err:
            _LOGGER.error("Failed to refresh token: %s", err)
            return False

    async def _async_update_data(self) -> Dict[str, Any]:
        """Update data (called by DataUpdateCoordinator)."""
        # Update status for each camera
        if self._backend:
            for did, camera_data in self._cameras.items():
                try:
                    status = await self._backend.get_camera_status_async(did)
                    camera_data.status = status
                    camera_data.is_streaming = (status == MIoTCameraStatus.CONNECTED)
                except Exception:
                    pass

        return {
            did: {
                "name": data.camera_info.name,
                "status": data.status.value,
                "is_streaming": data.is_streaming,
                "channel_count": data.camera_info.channel_count or 1,
            }
            for did, data in self._cameras.items()
        }
