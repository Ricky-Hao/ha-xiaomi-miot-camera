# -*- coding: utf-8 -*-
"""
Camera backend for Xiaomi Camera Proxy Add-on.

This module provides a unified interface that works with the Camera Proxy Add-on
for Home Assistant OS compatibility.
"""
import asyncio
import logging
from typing import Callable, Coroutine, List, Optional, Union

from .types import MIoTCameraInfo, MIoTCameraStatus, MIoTCameraVideoQuality

_LOGGER = logging.getLogger(__name__)

# Default proxy URL for the Camera Proxy Add-on
DEFAULT_PROXY_URL = "ws://127.0.0.1:8765/ws"


class CameraBackend:
    """Camera backend using the Proxy Add-on."""

    def __init__(
        self,
        proxy_url: str = DEFAULT_PROXY_URL,
        loop: Optional[asyncio.AbstractEventLoop] = None
    ):
        self._proxy_url = proxy_url
        self._loop = loop or asyncio.get_event_loop()
        self._client = None

    async def init_async(
        self,
        cloud_server: str,
        access_token: str,
        frame_interval: int = 500,
        enable_hw_accel: bool = False
    ) -> str:
        """Initialize the camera backend. Returns version string."""
        from .proxy_client import CameraProxyClient
        self._client = CameraProxyClient(proxy_url=self._proxy_url, loop=self._loop)
        return await self._client.init_async(cloud_server, access_token)

    async def deinit_async(self) -> None:
        """Deinitialize the camera backend."""
        if self._client:
            await self._client.disconnect_async()
            self._client = None

    async def update_access_token_async(self, access_token: str) -> None:
        """Update access token."""
        if self._client:
            await self._client.update_access_token_async(access_token)

    async def create_camera_async(
        self,
        camera_info: MIoTCameraInfo,
        frame_interval: Optional[int] = None,
        enable_hw_accel: Optional[bool] = None
    ) -> None:
        """Create a camera instance."""
        await self._client.create_camera_async(camera_info)

    async def destroy_camera_async(self, did: str) -> None:
        """Destroy a camera instance."""
        await self._client.destroy_camera_async(did)

    async def start_camera_async(
        self,
        did: str,
        pin_code: Optional[str] = None,
        qualities: Union[MIoTCameraVideoQuality, List[MIoTCameraVideoQuality]] = MIoTCameraVideoQuality.LOW,
        enable_audio: bool = False,
        enable_reconnect: bool = False
    ) -> None:
        """Start camera streaming."""
        await self._client.start_camera_async(
            did=did,
            pin_code=pin_code,
            qualities=qualities,
            enable_audio=enable_audio,
            enable_reconnect=enable_reconnect
        )

    async def stop_camera_async(self, did: str) -> None:
        """Stop camera streaming."""
        await self._client.stop_camera_async(did)

    async def get_camera_status_async(self, did: str) -> MIoTCameraStatus:
        """Get camera status."""
        return await self._client.get_camera_status_async(did)

    async def register_status_changed_async(
        self,
        did: str,
        callback: Callable[[str, MIoTCameraStatus], Coroutine]
    ) -> int:
        """Register status change callback."""
        # Proxy doesn't support status callbacks yet
        _LOGGER.debug("Status callbacks not yet supported via proxy")
        return 0

    async def unregister_status_changed_async(self, did: str, reg_id: int = 0) -> None:
        """Unregister status change callback."""
        pass

    async def register_decode_jpg_async(
        self,
        did: str,
        callback: Callable[[str, bytes, int, int], Coroutine],
        channel: int = 0
    ) -> int:
        """Register decoded JPG callback."""
        await self._client.register_decode_jpg_async(did, callback, channel)
        return 0

    async def unregister_decode_jpg_async(self, did: str, channel: int = 0, reg_id: int = 0) -> None:
        """Unregister decoded JPG callback."""
        await self._client.unregister_decode_jpg_async(did, channel)


async def _is_proxy_available(proxy_url: str = DEFAULT_PROXY_URL) -> bool:
    """Check if the camera proxy add-on is available."""
    from .proxy_client import check_proxy_available
    return await check_proxy_available(proxy_url)


async def create_camera_backend(
    proxy_url: str = DEFAULT_PROXY_URL,
    loop: Optional[asyncio.AbstractEventLoop] = None
) -> CameraBackend:
    """
    Create the camera backend.
    
    Args:
        proxy_url: URL of the proxy add-on WebSocket
        loop: Event loop
    
    Returns:
        CameraBackend instance
    
    Raises:
        RuntimeError: If the proxy add-on is not available
    """
    loop = loop or asyncio.get_event_loop()

    if await _is_proxy_available(proxy_url):
        _LOGGER.info("Using camera proxy backend at %s", proxy_url)
        return CameraBackend(proxy_url=proxy_url, loop=loop)
    else:
        raise RuntimeError(
            "Camera streaming not available. "
            "Please install and start the 'Xiaomi Camera Proxy' add-on. "
            "Go to Settings → Add-ons → Add-on Store → Repositories → Add: "
            "https://github.com/Ricky-Hao/ha-xiaomi-miot-camera"
        )
