# -*- coding: utf-8 -*-
# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""
HTTP Proxy Client for Camera Proxy Add-on.

This module provides an HTTP client that connects to the Camera Proxy Add-on,
allowing the custom component to work on Home Assistant OS (Alpine/musl) by
delegating camera operations to the glibc-based Add-on container.

The Add-on provides:
- OAuth authentication
- Device discovery
- Camera control
- RTSP streaming URLs
- Snapshot images
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp

from .types import MIoTCameraInfo, MIoTCameraStatus, MIoTCameraVideoQuality, MIoTOauthInfo

_LOGGER = logging.getLogger(__name__)

# Default Add-on HTTP URL
DEFAULT_PROXY_URL = "http://127.0.0.1:8765"


class CameraProxyHttpClient:
    """HTTP Client for Camera Proxy Add-on.
    
    This client uses the new HTTP API instead of WebSocket.
    """

    def __init__(
        self,
        proxy_url: str = DEFAULT_PROXY_URL,
        timeout: int = 30,
    ):
        """Initialize the proxy client."""
        self._proxy_url = proxy_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close_async(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _get(self, path: str) -> Dict[str, Any]:
        """Make GET request."""
        session = await self._get_session()
        url = f"{self._proxy_url}{path}"
        
        async with session.get(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"HTTP {resp.status}: {text}")
            return await resp.json()

    async def _post(self, path: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make POST request."""
        session = await self._get_session()
        url = f"{self._proxy_url}{path}"
        
        async with session.post(url, json=data or {}) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"HTTP {resp.status}: {text}")
            return await resp.json()

    # ==================== Health & Info ====================

    async def check_health_async(self) -> Dict[str, Any]:
        """Check if Add-on is healthy."""
        return await self._get("/health")

    async def get_info_async(self) -> Dict[str, Any]:
        """Get Add-on info."""
        return await self._get("/info")

    # ==================== OAuth ====================

    async def get_servers_async(self) -> Dict[str, str]:
        """Get supported cloud servers."""
        result = await self._get("/oauth/servers")
        return result.get("servers", {})

    async def get_auth_url_async(
        self,
        cloud_server: str,
        redirect_uri: str,
    ) -> str:
        """Get OAuth authorization URL."""
        result = await self._post("/oauth/auth_url", {
            "cloud_server": cloud_server,
            "redirect_uri": redirect_uri,
        })
        return result["auth_url"]

    async def handle_oauth_callback_async(
        self,
        code: str,
        state: str,
    ) -> bool:
        """Handle OAuth callback."""
        result = await self._post("/oauth/callback", {
            "code": code,
            "state": state,
        })
        return result.get("status") == "ok"

    async def set_tokens_async(
        self,
        cloud_server: str,
        access_token: str,
        refresh_token: str,
        expires_ts: int = 0,
    ) -> bool:
        """Set tokens directly."""
        result = await self._post("/oauth/set_tokens", {
            "cloud_server": cloud_server,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_ts": expires_ts,
        })
        return result.get("status") == "ok"

    async def refresh_tokens_async(self) -> bool:
        """Refresh access token."""
        result = await self._post("/oauth/refresh")
        return result.get("status") == "ok"

    # ==================== Device Discovery ====================

    async def discover_devices_async(self) -> Dict[str, Dict]:
        """Discover all devices."""
        result = await self._get("/devices")
        return result.get("devices", {})

    async def get_cameras_async(self) -> Dict[str, MIoTCameraInfo]:
        """Get discovered cameras."""
        result = await self._get("/cameras")
        cameras = {}
        for did, data in result.get("cameras", {}).items():
            cameras[did] = MIoTCameraInfo.model_validate(data)
        return cameras

    # ==================== Camera Control ====================

    async def start_camera_async(
        self,
        did: str,
        pin_code: Optional[str] = None,
        quality: int = 2,  # HIGH = 2
        enable_audio: bool = False,
    ) -> str:
        """Start camera streaming. Returns RTSP URL."""
        result = await self._post(f"/camera/{did}/start", {
            "pin_code": pin_code,
            "quality": quality,
            "enable_audio": enable_audio,
        })
        return result.get("rtsp_url", "")

    async def stop_camera_async(self, did: str) -> bool:
        """Stop camera streaming."""
        result = await self._post(f"/camera/{did}/stop")
        return result.get("status") == "ok"

    async def get_camera_status_async(self, did: str) -> MIoTCameraStatus:
        """Get camera status."""
        result = await self._get(f"/camera/{did}/status")
        return MIoTCameraStatus(result.get("status", 1))

    async def get_rtsp_url_async(self, did: str, channel: int = 0) -> str:
        """Get RTSP URL for camera."""
        result = await self._get(f"/camera/{did}/rtsp_url?channel={channel}")
        return result.get("rtsp_url", "")

    # ==================== Snapshots ====================

    async def get_snapshot_async(self, did: str, channel: int = 0) -> Optional[bytes]:
        """Get camera snapshot as JPEG bytes."""
        session = await self._get_session()
        url = f"{self._proxy_url}/snapshot/{did}/{channel}"
        
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.read()
            elif resp.status == 404:
                return None
            else:
                text = await resp.text()
                raise Exception(f"HTTP {resp.status}: {text}")


# Legacy WebSocket client for backward compatibility
# Keep the old CameraProxyClient class name as alias
CameraProxyClient = CameraProxyHttpClient
