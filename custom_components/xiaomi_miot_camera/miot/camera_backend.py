# -*- coding: utf-8 -*-
# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""Camera backend for Xiaomi Camera Proxy Add-on."""
import logging
from typing import Dict, List, Optional

from .types import MIoTCameraInfo, MIoTCameraStatus

_LOGGER = logging.getLogger(__name__)

DEFAULT_PROXY_URL = "http://127.0.0.1:8765"


class CameraBackend:
    """Camera backend using the Proxy Add-on HTTP API."""

    def __init__(self, proxy_url: str = DEFAULT_PROXY_URL):
        self._proxy_url = proxy_url.rstrip("/")
        self._client = None
        self._cameras: Dict[str, MIoTCameraInfo] = {}

    async def init_async(
        self,
        cloud_server: str,
        access_token: str,
        refresh_token: str = "",
        expires_ts: int = 0,
    ) -> str:
        """Initialize the camera backend. Returns version string."""
        from .proxy_client import CameraProxyHttpClient
        
        self._client = CameraProxyHttpClient(proxy_url=self._proxy_url)
        
        # Only set tokens if we have real tokens (not placeholder)
        if access_token and access_token != "managed_by_addon":
            await self._client.set_tokens_async(
                cloud_server=cloud_server,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_ts=expires_ts,
            )
        
        info = await self._client.get_info_async()
        return info.get("version", "unknown")

    async def deinit_async(self) -> None:
        """Deinitialize the camera backend."""
        if self._client:
            await self._client.close_async()
            self._client = None

    async def get_cameras_async(self) -> Dict[str, MIoTCameraInfo]:
        """Get discovered cameras from Add-on."""
        if self._client:
            self._cameras = await self._client.get_cameras_async()
        return self._cameras

    async def set_configured_cameras_async(self, camera_dids: List[str]) -> bool:
        """Set the list of configured cameras for auto-start."""
        if self._client:
            return await self._client.set_configured_cameras_async(camera_dids)
        return False

    async def start_camera_async(
        self,
        did: str,
        pin_code: Optional[str] = None,
        enable_audio: bool = False,
    ) -> bool:
        """Start camera streaming."""
        if not self._client:
            raise RuntimeError("Backend not initialized")
        
        return await self._client.start_camera_async(
            did=did,
            pin_code=pin_code,
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
    except Exception:
        pass
    
    return False
