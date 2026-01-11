# -*- coding: utf-8 -*-
"""
Camera backend abstraction.

Provides a unified interface that works with either:
1. Native library (on glibc systems like Ubuntu)
2. Proxy Add-on (on musl systems like Home Assistant OS)
"""
import asyncio
import logging
import os
import platform
from typing import Callable, Coroutine, Dict, List, Optional, Union

from .types import MIoTCameraInfo, MIoTCameraStatus, MIoTCameraVideoQuality

_LOGGER = logging.getLogger(__name__)

# Force proxy mode - set to True for HAOS compatibility
# Can also be controlled via environment variable XIAOMI_CAMERA_FORCE_PROXY=1
FORCE_PROXY_MODE = True


class CameraBackend:
    """Abstract camera backend interface."""

    async def init_async(
        self,
        cloud_server: str,
        access_token: str,
        frame_interval: int = 500,
        enable_hw_accel: bool = False
    ) -> str:
        """Initialize the camera backend. Returns version string."""
        raise NotImplementedError

    async def deinit_async(self) -> None:
        """Deinitialize the camera backend."""
        raise NotImplementedError

    async def update_access_token_async(self, access_token: str) -> None:
        """Update access token."""
        raise NotImplementedError

    async def create_camera_async(
        self,
        camera_info: MIoTCameraInfo,
        frame_interval: Optional[int] = None,
        enable_hw_accel: Optional[bool] = None
    ) -> None:
        """Create a camera instance."""
        raise NotImplementedError

    async def destroy_camera_async(self, did: str) -> None:
        """Destroy a camera instance."""
        raise NotImplementedError

    async def start_camera_async(
        self,
        did: str,
        pin_code: Optional[str] = None,
        qualities: Union[MIoTCameraVideoQuality, List[MIoTCameraVideoQuality]] = MIoTCameraVideoQuality.LOW,
        enable_audio: bool = False,
        enable_reconnect: bool = False
    ) -> None:
        """Start camera streaming."""
        raise NotImplementedError

    async def stop_camera_async(self, did: str) -> None:
        """Stop camera streaming."""
        raise NotImplementedError

    async def get_camera_status_async(self, did: str) -> MIoTCameraStatus:
        """Get camera status."""
        raise NotImplementedError

    async def register_status_changed_async(
        self,
        did: str,
        callback: Callable[[str, MIoTCameraStatus], Coroutine]
    ) -> int:
        """Register status change callback."""
        raise NotImplementedError

    async def unregister_status_changed_async(self, did: str, reg_id: int = 0) -> None:
        """Unregister status change callback."""
        raise NotImplementedError

    async def register_decode_jpg_async(
        self,
        did: str,
        callback: Callable[[str, bytes, int, int], Coroutine],
        channel: int = 0
    ) -> int:
        """Register decoded JPG callback."""
        raise NotImplementedError

    async def unregister_decode_jpg_async(self, did: str, channel: int = 0, reg_id: int = 0) -> None:
        """Unregister decoded JPG callback."""
        raise NotImplementedError


class NativeCameraBackend(CameraBackend):
    """Native library backend (for glibc systems)."""

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        self._loop = loop or asyncio.get_event_loop()
        self._camera_client = None

    async def init_async(
        self,
        cloud_server: str,
        access_token: str,
        frame_interval: int = 500,
        enable_hw_accel: bool = False
    ) -> str:
        from .camera import MIoTCamera
        self._camera_client = MIoTCamera(
            cloud_server=cloud_server,
            access_token=access_token,
            frame_interval=frame_interval,
            enable_hw_accel=enable_hw_accel,
            loop=self._loop
        )
        await self._camera_client.init_async(
            frame_interval=frame_interval,
            enable_hw_accel=enable_hw_accel
        )
        return await self._camera_client.get_camera_version_async()

    async def deinit_async(self) -> None:
        if self._camera_client:
            await self._camera_client.deinit_async()
            self._camera_client = None

    async def update_access_token_async(self, access_token: str) -> None:
        if self._camera_client:
            await self._camera_client.update_access_token_async(access_token)

    async def create_camera_async(
        self,
        camera_info: MIoTCameraInfo,
        frame_interval: Optional[int] = None,
        enable_hw_accel: Optional[bool] = None
    ) -> None:
        await self._camera_client.create_camera_async(
            camera_info=camera_info,
            frame_interval=frame_interval,
            enable_hw_accel=enable_hw_accel
        )

    async def destroy_camera_async(self, did: str) -> None:
        await self._camera_client.destroy_camera_async(did)

    async def start_camera_async(
        self,
        did: str,
        pin_code: Optional[str] = None,
        qualities: Union[MIoTCameraVideoQuality, List[MIoTCameraVideoQuality]] = MIoTCameraVideoQuality.LOW,
        enable_audio: bool = False,
        enable_reconnect: bool = False
    ) -> None:
        await self._camera_client.start_camera_async(
            did=did,
            pin_code=pin_code,
            qualities=qualities,
            enable_audio=enable_audio,
            enable_reconnect=enable_reconnect
        )

    async def stop_camera_async(self, did: str) -> None:
        await self._camera_client.stop_camera_async(did)

    async def get_camera_status_async(self, did: str) -> MIoTCameraStatus:
        return await self._camera_client.get_camera_status_async(did)

    async def register_status_changed_async(
        self,
        did: str,
        callback: Callable[[str, MIoTCameraStatus], Coroutine]
    ) -> int:
        return await self._camera_client.register_status_changed_async(did, callback)

    async def unregister_status_changed_async(self, did: str, reg_id: int = 0) -> None:
        await self._camera_client.unregister_status_changed_async(did, reg_id)

    async def register_decode_jpg_async(
        self,
        did: str,
        callback: Callable[[str, bytes, int, int], Coroutine],
        channel: int = 0
    ) -> int:
        return await self._camera_client.register_decode_jpg_async(did, callback, channel)

    async def unregister_decode_jpg_async(self, did: str, channel: int = 0, reg_id: int = 0) -> None:
        await self._camera_client.unregister_decode_jpg_async(did, channel, reg_id)


class ProxyCameraBackend(CameraBackend):
    """Proxy Add-on backend (for musl systems like HAOS)."""

    def __init__(
        self,
        proxy_url: str = "ws://127.0.0.1:8765/ws",
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
        from .proxy_client import CameraProxyClient
        self._client = CameraProxyClient(proxy_url=self._proxy_url, loop=self._loop)
        return await self._client.init_async(cloud_server, access_token)

    async def deinit_async(self) -> None:
        if self._client:
            await self._client.disconnect_async()
            self._client = None

    async def update_access_token_async(self, access_token: str) -> None:
        if self._client:
            await self._client.update_access_token_async(access_token)

    async def create_camera_async(
        self,
        camera_info: MIoTCameraInfo,
        frame_interval: Optional[int] = None,
        enable_hw_accel: Optional[bool] = None
    ) -> None:
        await self._client.create_camera_async(camera_info)

    async def destroy_camera_async(self, did: str) -> None:
        await self._client.destroy_camera_async(did)

    async def start_camera_async(
        self,
        did: str,
        pin_code: Optional[str] = None,
        qualities: Union[MIoTCameraVideoQuality, List[MIoTCameraVideoQuality]] = MIoTCameraVideoQuality.LOW,
        enable_audio: bool = False,
        enable_reconnect: bool = False
    ) -> None:
        await self._client.start_camera_async(
            did=did,
            pin_code=pin_code,
            qualities=qualities,
            enable_audio=enable_audio,
            enable_reconnect=enable_reconnect
        )

    async def stop_camera_async(self, did: str) -> None:
        await self._client.stop_camera_async(did)

    async def get_camera_status_async(self, did: str) -> MIoTCameraStatus:
        return await self._client.get_camera_status_async(did)

    async def register_status_changed_async(
        self,
        did: str,
        callback: Callable[[str, MIoTCameraStatus], Coroutine]
    ) -> int:
        # Proxy doesn't support status callbacks yet, return 0
        _LOGGER.warning("Status callbacks not yet supported via proxy")
        return 0

    async def unregister_status_changed_async(self, did: str, reg_id: int = 0) -> None:
        pass

    async def register_decode_jpg_async(
        self,
        did: str,
        callback: Callable[[str, bytes, int, int], Coroutine],
        channel: int = 0
    ) -> int:
        await self._client.register_decode_jpg_async(did, callback, channel)
        return 0

    async def unregister_decode_jpg_async(self, did: str, channel: int = 0, reg_id: int = 0) -> None:
        await self._client.unregister_decode_jpg_async(did, channel)


def _is_musl_libc() -> bool:
    """Check if running on musl libc (Alpine Linux)."""
    try:
        # Check for Alpine Linux
        with open("/etc/os-release", "r") as f:
            content = f.read().lower()
            if "alpine" in content:
                return True
    except FileNotFoundError:
        pass

    # Check libc type
    try:
        import subprocess
        result = subprocess.run(
            ["ldd", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        output = (result.stdout + result.stderr).lower()
        if "musl" in output:
            return True
    except Exception:
        pass

    return False


async def _is_proxy_available(proxy_url: str = "ws://127.0.0.1:8765/ws") -> bool:
    """Check if the camera proxy add-on is available."""
    from .proxy_client import check_proxy_available
    return await check_proxy_available(proxy_url)


async def create_camera_backend(
    proxy_url: str = "ws://127.0.0.1:8765/ws",
    force_proxy: bool = False,
    loop: Optional[asyncio.AbstractEventLoop] = None
) -> CameraBackend:
    """
    Create the appropriate camera backend.
    
    Args:
        proxy_url: URL of the proxy add-on WebSocket
        force_proxy: Force using proxy even on glibc systems
        loop: Event loop
    
    Returns:
        CameraBackend instance (either Native or Proxy)
    """
    loop = loop or asyncio.get_event_loop()

    # Check if we should force proxy mode
    use_proxy = force_proxy or FORCE_PROXY_MODE or os.environ.get("XIAOMI_CAMERA_FORCE_PROXY", "").lower() in ("1", "true", "yes")
    
    if use_proxy:
        _LOGGER.info("Force proxy mode enabled")

    # Also check if on musl (Alpine/HAOS)
    if not use_proxy and _is_musl_libc():
        _LOGGER.info("Detected musl libc (Alpine/HAOS), will use proxy backend")
        use_proxy = True

    # If proxy mode, check availability and use it
    if use_proxy:
        if await _is_proxy_available(proxy_url):
            _LOGGER.info("Using proxy backend at %s", proxy_url)
            return ProxyCameraBackend(proxy_url=proxy_url, loop=loop)
        else:
            raise RuntimeError(
                "Camera streaming not available. "
                "Please install and start the 'Xiaomi Camera Proxy' add-on. "
                "Go to Settings → Add-ons → Add-on Store → Repositories → Add: "
                "https://github.com/Ricky-Hao/ha-xiaomi-miot-camera"
            )

    # Try to load native library (only on glibc systems)
    try:
        from .camera import _load_dynamic_lib
        _load_dynamic_lib()
        _LOGGER.info("Native library available, using native backend")
        return NativeCameraBackend(loop=loop)
    except Exception as e:
        _LOGGER.warning("Native library not available: %s", e)
        # Check proxy again as fallback
        if await _is_proxy_available(proxy_url):
            _LOGGER.info("Falling back to proxy backend at %s", proxy_url)
            return ProxyCameraBackend(proxy_url=proxy_url, loop=loop)
        raise RuntimeError(
            f"Camera streaming not available. Native library error: {e}. "
            "On Home Assistant OS, please install the 'Xiaomi Camera Proxy' add-on."
        )
