# -*- coding: utf-8 -*-
# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""
Camera backend for Xiaomi Camera Proxy Add-on.

This module provides a unified interface that works with the Camera Proxy Add-on
for Home Assistant OS compatibility. It uses the new HTTP API.
"""
import asyncio
import logging
from typing import Callable, Coroutine, Dict, List, Optional, Union

from .types import MIoTCameraInfo, MIoTCameraStatus, MIoTCameraVideoQuality

_LOGGER = logging.getLogger(__name__)

# Default proxy URL for the Camera Proxy Add-on
DEFAULT_PROXY_URL = "http://127.0.0.1:8765"


class CameraBackend:
    """Camera backend using the Proxy Add-on HTTP API."""

    def __init__(
        self,
        proxy_url: str = DEFAULT_PROXY_URL,
        loop: Optional[asyncio.AbstractEventLoop] = None
    ):
        self._proxy_url = proxy_url.rstrip("/")
        self._loop = loop or asyncio.get_event_loop()
        self._client = None
        self._cameras: Dict[str, MIoTCameraInfo] = {}

    async def init_async(
        self,
        cloud_server: str,
        access_token: str,
        refresh_token: str = "",
        expires_ts: int = 0,
        frame_interval: int = 500,
        enable_hw_accel: bool = False
    ) -> str:
        """Initialize the camera backend. Returns version string."""
        from .proxy_client import CameraProxyHttpClient
        
        self._client = CameraProxyHttpClient(proxy_url=self._proxy_url)
        
        # Set tokens in the Add-on
        await self._client.set_tokens_async(
            cloud_server=cloud_server,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_ts=expires_ts,
        )
        
        # Get info to return version
        info = await self._client.get_info_async()
        return info.get("version", "unknown")

    async def deinit_async(self) -> None:
        """Deinitialize the camera backend."""
        if self._client:
            await self._client.close_async()
            self._client = None

    async def update_access_token_async(
        self,
        access_token: str,
        refresh_token: str = "",
        expires_ts: int = 0,
    ) -> None:
        """Update access token."""
        if self._client:
            # Re-set tokens (Add-on handles the update)
            await self._client.set_tokens_async(
                cloud_server="",  # Will use existing
                access_token=access_token,
                refresh_token=refresh_token,
                expires_ts=expires_ts,
            )

    async def get_cameras_async(self) -> Dict[str, MIoTCameraInfo]:
        """Get discovered cameras from Add-on."""
        if self._client:
            self._cameras = await self._client.get_cameras_async()
        return self._cameras

    async def start_camera_async(
        self,
        did: str,
        pin_code: Optional[str] = None,
        quality: MIoTCameraVideoQuality = MIoTCameraVideoQuality.HIGH,
        enable_audio: bool = False,
    ) -> str:
        """Start camera streaming. Returns RTSP URL."""
        if not self._client:
            raise RuntimeError("Backend not initialized")
        
        return await self._client.start_camera_async(
            did=did,
            pin_code=pin_code,
            quality=quality.value if isinstance(quality, MIoTCameraVideoQuality) else quality,
            enable_audio=enable_audio,
        )

    async def stop_camera_async(self, did: str) -> None:
        """Stop camera streaming."""
        if self._client:
            await self._client.stop_camera_async(did)

    async def get_camera_status_async(self, did: str) -> MIoTCameraStatus:
        """Get camera status."""
        if self._client:
            return await self._client.get_camera_status_async(did)
        return MIoTCameraStatus.DISCONNECTED

    async def get_rtsp_url_async(self, did: str, channel: int = 0) -> str:
        """Get RTSP URL for camera."""
        if self._client:
            return await self._client.get_rtsp_url_async(did, channel)
        return ""

    async def get_snapshot_async(self, did: str, channel: int = 0) -> Optional[bytes]:
        """Get camera snapshot as JPEG bytes."""
        if self._client:
            return await self._client.get_snapshot_async(did, channel)
        return None


async def check_proxy_available(proxy_url: str = DEFAULT_PROXY_URL) -> bool:
    """Check if the camera proxy add-on is available."""
    import aiohttp
    
    try:
        url = f"{proxy_url.rstrip('/')}/health"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("status") == "ok"
    except Exception as e:
        _LOGGER.debug("Proxy not available: %s", e)
    
    return False


async def create_camera_backend(
    proxy_url: str = DEFAULT_PROXY_URL,
    loop: Optional[asyncio.AbstractEventLoop] = None
) -> CameraBackend:
    """
    Create the camera backend.
    
    Args:
        proxy_url: URL of the proxy add-on HTTP API
        loop: Event loop
    
    Returns:
        CameraBackend instance
    
    Raises:
        RuntimeError: If the proxy add-on is not available
    """
    loop = loop or asyncio.get_event_loop()

    if await check_proxy_available(proxy_url):
        _LOGGER.info("Using camera proxy backend at %s", proxy_url)
        return CameraBackend(proxy_url=proxy_url, loop=loop)
    else:
        raise RuntimeError(
            "Camera Proxy Add-on not available. "
            "Please install and start the 'Xiaomi Camera Proxy' add-on. "
            "Go to Settings → Add-ons → Add-on Store → Repositories → Add: "
            "https://github.com/Ricky-Hao/ha-xiaomi-miot-camera"
        )
