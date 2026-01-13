# -*- coding: utf-8 -*-
# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""
Camera Service - Main service that manages cameras using miot_kit.

This service handles:
- OAuth authentication flow
- Device discovery from cloud
- Camera streaming via WebRTC (FFmpeg → RTSP → MediaMTX → WebRTC)
- Snapshot generation
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from miot.camera import MIoTCamera, MIoTCameraInstance, get_camera_extra_info
from miot.cloud import MIoTOAuth2Client, MIoTHttpClient
from miot.types import (
    MIoTCameraInfo,
    MIoTCameraStatus,
    MIoTCameraVideoQuality,
    MIoTDeviceInfo,
    MIoTOauthInfo,
)
from miot.const import CLOUD_SERVERS


class QualityValue:
    """Wrapper to allow any integer quality value.
    
    This mimics MIoTCameraVideoQuality enum behavior but accepts any int.
    Used for testing experimental quality values like 4 or 5.
    """
    def __init__(self, value: int):
        self.value = value
    
    def __repr__(self):
        return f"QualityValue({self.value})"

from .rtsp_streamer import RTSPStreamer

_LOGGER = logging.getLogger(__name__)

# Persistent storage path
CONFIG_PATH = Path("/data")
TOKENS_FILE = CONFIG_PATH / "tokens.json"
CONFIGURED_CAMERAS_FILE = CONFIG_PATH / "configured_cameras.json"  # Set by HA Integration


class CameraService:
    """Camera service that manages all cameras."""

    def __init__(self, video_quality: int = 3):
        """Initialize camera service.
        
        Args:
            video_quality: Video quality (1=LOW, 3=HIGH, 4/5=experimental)
        """
        self._oauth_client: Optional[MIoTOAuth2Client] = None
        self._http_client: Optional[MIoTHttpClient] = None
        self._camera_manager: Optional[MIoTCamera] = None
        self._rtsp_streamer: Optional[RTSPStreamer] = None

        # State
        self._cloud_server: str = "cn"
        self._oauth_info: Optional[MIoTOauthInfo] = None
        self._device_list: Dict[str, MIoTDeviceInfo] = {}
        self._camera_list: Dict[str, MIoTCameraInfo] = {}
        self._active_cameras: Dict[str, MIoTCameraInstance] = {}
        self._default_video_quality: int = video_quality  # Default quality from config

        # Snapshots cache: {did_channel: bytes}
        self._snapshots: Dict[str, bytes] = {}

        # Callbacks
        self._on_status_changed: Optional[Callable] = None

    @property
    def initialized(self) -> bool:
        """Check if service is initialized."""
        return self._camera_manager is not None

    @property
    def authenticated(self) -> bool:
        """Check if user is authenticated."""
        return self._oauth_info is not None

    @property
    def cloud_server(self) -> str:
        """Get current cloud server."""
        return self._cloud_server

    @property
    def cameras(self) -> Dict[str, MIoTCameraInfo]:
        """Get camera list."""
        return self._camera_list

    async def init_async(self, rtsp_streamer: Optional[RTSPStreamer] = None) -> None:
        """Initialize the service."""
        self._rtsp_streamer = rtsp_streamer or RTSPStreamer()
        
        # Load saved tokens and initialize camera manager
        await self._load_tokens_async()
        
        # Auto-start previously active cameras
        if self._camera_manager:
            asyncio.create_task(self._delayed_auto_start_async())

    async def deinit_async(self) -> None:
        """Deinitialize the service."""
        # Stop all cameras
        for did in list(self._active_cameras.keys()):
            await self.stop_camera_async(did)

        if self._camera_manager:
            await self._camera_manager.deinit_async()
            self._camera_manager = None

        if self._http_client:
            await self._http_client.deinit_async()
            self._http_client = None

        if self._oauth_client:
            await self._oauth_client.deinit_async()
            self._oauth_client = None

    # ==================== OAuth ====================

    def get_supported_servers(self) -> Dict[str, str]:
        """Get supported cloud servers."""
        return CLOUD_SERVERS

    async def get_auth_url_async(
        self,
        cloud_server: str,
        redirect_uri: str,
    ) -> str:
        """Get OAuth authorization URL."""
        import uuid
        
        self._cloud_server = cloud_server
        
        # Create OAuth client
        self._oauth_client = MIoTOAuth2Client(
            redirect_uri=redirect_uri,
            cloud_server=cloud_server,
            uuid=str(uuid.uuid4()),
        )
        
        return self._oauth_client.gen_auth_url(redirect_uri=redirect_uri)

    async def handle_oauth_callback_async(
        self,
        code: str,
        state: str,
    ) -> bool:
        """Handle OAuth callback and get tokens."""
        if not self._oauth_client:
            raise ValueError("OAuth client not initialized. Call get_auth_url_async first.")

        # Verify state
        if not await self._oauth_client.check_state_async(state):
            raise ValueError("Invalid OAuth state")

        # Exchange code for tokens
        self._oauth_info = await self._oauth_client.get_access_token_async(code)
        
        # Save tokens
        await self._save_tokens_async()
        
        # Initialize camera manager with new tokens
        await self._init_camera_manager_async()
        
        return True

    async def set_tokens_async(
        self,
        cloud_server: str,
        access_token: str,
        refresh_token: str,
        expires_ts: int,
    ) -> None:
        """Set tokens directly (from HA integration)."""
        # Check if this is a placeholder token
        is_placeholder = access_token in ("managed_by_addon", "", None)
        
        if is_placeholder:
            # Trigger auto-start if we have initialized camera manager
            if self._camera_manager:
                asyncio.create_task(self._delayed_auto_start_async())
            return
        
        # Real tokens received - update and save
        self._cloud_server = cloud_server
        self._oauth_info = MIoTOauthInfo(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_ts=expires_ts,
        )
        
        await self._save_tokens_async()
        await self._init_camera_manager_async()
        
        # Auto-start previously active cameras after token refresh
        asyncio.create_task(self._delayed_auto_start_async())

    async def refresh_tokens_async(self) -> bool:
        """Refresh access token."""
        if not self._oauth_client or not self._oauth_info:
            return False

        try:
            self._oauth_info = await self._oauth_client.refresh_access_token_async(
                self._oauth_info.refresh_token
            )
            await self._save_tokens_async()
            
            if self._camera_manager:
                await self._camera_manager.update_access_token_async(
                    self._oauth_info.access_token
                )
            
            return True
        except Exception as e:
            _LOGGER.error("Failed to refresh tokens: %s", e)
            return False

    # ==================== Device Discovery ====================

    async def discover_devices_async(self) -> Dict[str, MIoTDeviceInfo]:
        """Discover devices from cloud."""
        if not self._http_client:
            raise ValueError("Not authenticated")

        self._device_list = await self._http_client.get_devices_async()
        
        # Filter cameras
        extra_info = await get_camera_extra_info()
        self._camera_list = {}
        
        for did, device in self._device_list.items():
            if self._is_camera_device(device, extra_info):
                channel_count = self._get_channel_count(device.model, extra_info)
                self._camera_list[did] = MIoTCameraInfo(
                    **device.model_dump(),
                    channel_count=channel_count,
                    camera_status=MIoTCameraStatus.DISCONNECTED,
                )
        
        _LOGGER.info("Discovered %d cameras out of %d devices", 
                    len(self._camera_list), len(self._device_list))
        return self._device_list

    async def get_cameras_async(self) -> Dict[str, MIoTCameraInfo]:
        """Get discovered cameras."""
        if not self._camera_list:
            await self.discover_devices_async()
        return self._camera_list

    async def set_configured_cameras_async(self, camera_dids: List[str]) -> None:
        """Set and save configured cameras (from HA Integration)."""
        # Save to file for auto-start on Add-on boot
        try:
            import aiofiles
            CONFIG_PATH.mkdir(parents=True, exist_ok=True)
            
            data = {"configured_dids": camera_dids}
            
            async with aiofiles.open(CONFIGURED_CAMERAS_FILE, "w") as f:
                await f.write(json.dumps(data, indent=2))
        except Exception as e:
            _LOGGER.error("Failed to save configured cameras: %s", e)
            return
        
        # Auto-start cameras if camera manager is ready
        if self._camera_manager and camera_dids:
            asyncio.create_task(self._restart_cameras_async(camera_dids))

    async def _restart_cameras_async(self, camera_dids: List[str]) -> None:
        """Stop all cameras, wait for cleanup, then start configured cameras."""
        try:
            # Stop all currently active cameras first
            if self._active_cameras:
                for did in list(self._active_cameras.keys()):
                    try:
                        await self.stop_camera_async(did)
                    except Exception as e:
                        _LOGGER.warning("Error stopping camera %s: %s", did, e)
                
                # Wait for camera instances to fully release
                await asyncio.sleep(3)
            
            # Start the configured cameras
            await self._start_cameras_by_dids_async(camera_dids)
        except Exception as e:
            _LOGGER.error("Error in camera restart: %s", e)

    # ==================== Camera Control ====================

    async def start_camera_async(
        self,
        did: str,
        pin_code: Optional[str] = None,
        enable_audio: bool = False,
    ) -> None:
        """Start streaming a camera."""
        if not self._camera_manager:
            raise ValueError("Camera manager not initialized")

        if did not in self._camera_list:
            raise ValueError(f"Camera not found: {did}")

        camera_info = self._camera_list[did]
        
        # Check if camera is already active
        if did in self._active_cameras:
            stream_ready = await self._check_stream_ready_async(did, 0)
            if stream_ready:
                return
            # Wait for stream to be ready
            if self._rtsp_streamer:
                for channel in range(camera_info.channel_count):
                    await self._wait_for_stream_ready_async(did, channel)
            return
        
        # Create camera instance
        instance = await self._camera_manager.create_camera_async(camera_info)
        self._active_cameras[did] = instance
        
        # Start RTSP streams first
        if self._rtsp_streamer:
            for channel in range(camera_info.channel_count):
                await self._rtsp_streamer.start_stream(did, channel)
        
        # Register callbacks for each channel
        for channel in range(camera_info.channel_count):
            await self._camera_manager.register_raw_video_async(
                did=did,
                channel=channel,
                callback=self._on_raw_video_frame,
            )
            await self._camera_manager.register_decode_jpg_async(
                did=did,
                channel=channel,
                callback=self._on_decoded_jpg,
            )
            await self._camera_manager.register_status_changed_async(
                did=did,
                callback=self._on_camera_status_changed,
            )
        
        # Start streaming with configured quality
        quality = self._default_video_quality
        quality_list = [QualityValue(quality) for _ in range(camera_info.channel_count)]
        
        await self._camera_manager.start_camera_async(
            did=did,
            pin_code=pin_code,
            qualities=quality_list,
            enable_audio=enable_audio,
            enable_reconnect=True,
        )
        
        # Wait for stream to be ready
        if self._rtsp_streamer:
            for channel in range(camera_info.channel_count):
                await self._wait_for_stream_ready_async(did, channel)
        
        _LOGGER.info("Started camera: %s", did)

    async def stop_camera_async(self, did: str) -> None:
        """Stop streaming a camera and release connection."""
        if not self._camera_manager:
            return

        if did in self._active_cameras:
            try:
                await self._camera_manager.stop_camera_async(did)
            except Exception as e:
                _LOGGER.warning("Error stopping camera %s: %s", did, e)
            
            # Destroy camera instance to release connection
            try:
                await self._camera_manager.destroy_camera_async(did)
            except Exception as e:
                _LOGGER.warning("Error destroying camera %s: %s", did, e)
            
            # Stop RTSP streams
            camera_info = self._camera_list.get(did)
            if camera_info and self._rtsp_streamer:
                for channel in range(camera_info.channel_count):
                    await self._rtsp_streamer.stop_stream(did, channel)
            
            del self._active_cameras[did]
            _LOGGER.info("Stopped camera: %s", did)

    async def get_camera_status_async(self, did: str) -> MIoTCameraStatus:
        """Get camera status."""
        if not self._camera_manager or did not in self._active_cameras:
            return MIoTCameraStatus.DISCONNECTED
        return await self._camera_manager.get_camera_status_async(did)

    async def get_snapshot_async(self, did: str, channel: int = 0) -> Optional[bytes]:
        """Get latest snapshot for a camera."""
        key = f"{did}_{channel}"
        return self._snapshots.get(key)

    def get_rtsp_url(self, did: str, channel: int = 0) -> str:
        """Get RTSP URL for a camera."""
        return f"rtsp://127.0.0.1:8554/camera/{did}/{channel}"

    # ==================== Internal Methods ====================

    async def _init_camera_manager_async(self) -> None:
        """Initialize camera manager with current tokens."""
        if not self._oauth_info:
            return

        # Create HTTP client
        self._http_client = MIoTHttpClient(
            cloud_server=self._cloud_server,
            access_token=self._oauth_info.access_token,
        )

        # Create camera manager
        self._camera_manager = MIoTCamera(
            cloud_server=self._cloud_server,
            access_token=self._oauth_info.access_token,
            frame_interval=500,
            enable_hw_accel=False,
        )
        
        version = await self._camera_manager.get_camera_version_async()
        _LOGGER.info("Camera library version: %s", version)

    async def _load_tokens_async(self) -> None:
        """Load tokens from persistent storage."""
        if not TOKENS_FILE.exists():
            return

        try:
            import aiofiles
            async with aiofiles.open(TOKENS_FILE, "r") as f:
                data = json.loads(await f.read())
            
            self._cloud_server = data.get("cloud_server", "cn")
            if "oauth_info" in data:
                oauth_info = MIoTOauthInfo(**data["oauth_info"])
                
                # Validate token is not a placeholder
                if oauth_info.access_token in ("managed_by_addon", "", None):
                    TOKENS_FILE.unlink()
                    return
                
                self._oauth_info = oauth_info
                await self._init_camera_manager_async()
        except Exception as e:
            _LOGGER.warning("Failed to load tokens: %s", e)

    async def _save_tokens_async(self) -> None:
        """Save tokens to persistent storage."""
        if not self._oauth_info:
            return

        try:
            import aiofiles
            CONFIG_PATH.mkdir(parents=True, exist_ok=True)
            
            data = {
                "cloud_server": self._cloud_server,
                "oauth_info": self._oauth_info.model_dump(),
            }
            
            async with aiofiles.open(TOKENS_FILE, "w") as f:
                await f.write(json.dumps(data, indent=2))
        except Exception as e:
            _LOGGER.error("Failed to save tokens: %s", e)

    async def _load_and_start_configured_cameras_async(self) -> None:
        """Load and auto-start configured cameras."""
        if not CONFIGURED_CAMERAS_FILE.exists():
            return
        
        try:
            import aiofiles
            async with aiofiles.open(CONFIGURED_CAMERAS_FILE, "r") as f:
                data = json.loads(await f.read())
            
            camera_dids = data.get("configured_dids", [])
            
            if camera_dids:
                await self._start_cameras_by_dids_async(camera_dids)
        except Exception as e:
            _LOGGER.warning("Failed to load configured cameras: %s", e)

    async def _start_cameras_by_dids_async(self, camera_dids: List[str]) -> None:
        """Start cameras by device IDs."""
        # Discover cameras first
        if not self._camera_list:
            await self.discover_devices_async()
        
        # Start each camera
        for did in camera_dids:
            if did in self._camera_list:
                try:
                    await self.start_camera_async(did)
                except Exception as e:
                    _LOGGER.warning("Failed to auto-start camera %s: %s", did, e)
        
        _LOGGER.info("Auto-started %d cameras", len(self._active_cameras))

    def _is_camera_device(self, device: MIoTDeviceInfo, extra_info) -> bool:
        """Check if device is a camera."""
        # Check by model prefix
        if device.model.startswith(("chuangmi.camera", "isa.camera", "xiaomi.camera", "mxiang.camera")):
            denylist = extra_info.denylist.get("camera", {})
            return device.model not in denylist
        
        # Check allowlist for other device types (wifispeaker with camera)
        for cls_name, models in extra_info.allowlist.items():
            if device.model in models:
                return True
        
        return False

    def _get_channel_count(self, model: str, extra_info) -> int:
        """Get channel count for a camera model."""
        if model in extra_info.extra_info:
            item = extra_info.extra_info[model]
            # MIoTCameraExtraItem is a Pydantic model, access attribute directly
            return item.channel_count if item.channel_count else 1
        return 1

    async def _on_raw_video_frame(
        self,
        did: str,
        data: bytes,
        timestamp: int,
        sequence: int,
        channel: int,
    ) -> None:
        """Handle raw video frame - push to RTSP."""
        if self._rtsp_streamer:
            await self._rtsp_streamer.push_frame(did, data, channel)

    async def _on_decoded_jpg(
        self,
        did: str,
        data: bytes,
        timestamp: int,
        channel: int,
    ) -> None:
        """Handle decoded JPG - cache as snapshot."""
        key = f"{did}_{channel}"
        self._snapshots[key] = data

    async def _on_camera_status_changed(
        self,
        did: str,
        status: MIoTCameraStatus,
    ) -> None:
        """Handle camera status change."""
        if did in self._camera_list:
            self._camera_list[did].camera_status = status
        
        if status == MIoTCameraStatus.DISCONNECTED:
            _LOGGER.warning("Camera %s disconnected", did)
        elif status == MIoTCameraStatus.CONNECTED:
            _LOGGER.info("Camera %s connected", did)
        
        if self._on_status_changed:
            await self._on_status_changed(did, status)

    async def _delayed_auto_start_async(self) -> None:
        """Auto-start cameras after a brief delay for service stability."""
        try:
            await asyncio.sleep(2)
            
            if not self._camera_manager:
                return
            
            await self._load_and_start_configured_cameras_async()
        except Exception as e:
            _LOGGER.error("Error in delayed auto-start: %s", e)

    async def _check_stream_ready_async(self, did: str, channel: int) -> bool:
        """Check if RTSP stream is currently ready."""
        import aiohttp
        
        rtsp_path = f"camera/{did}/{channel}"
        mediamtx_api = "http://localhost:9997/v3/paths/list"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(mediamtx_api, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        paths = data.get("items", [])
                        
                        for path_info in paths:
                            if path_info.get("name") == rtsp_path:
                                return path_info.get("ready", False)
        except Exception:
            pass
        
        return False

    async def _wait_for_stream_ready_async(
        self,
        did: str,
        channel: int,
        timeout: float = 10.0,
    ) -> bool:
        """Wait for RTSP stream to be publishing to MediaMTX."""
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            if await self._check_stream_ready_async(did, channel):
                return True
            await asyncio.sleep(0.5)
        
        _LOGGER.warning("Timeout waiting for stream %s_%d", did, channel)
        return False
