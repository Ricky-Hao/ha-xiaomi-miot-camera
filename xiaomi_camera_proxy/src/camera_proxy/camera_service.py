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
ACTIVE_CAMERAS_FILE = CONFIG_PATH / "active_cameras.json"


class CameraService:
    """Camera service that manages all cameras."""

    def __init__(self):
        """Initialize camera service."""
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
        self._camera_qualities: Dict[str, int] = {}  # Track quality per camera

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
        
        # Load saved tokens
        await self._load_tokens_async()
        
        _LOGGER.info("Camera service initialized")
        
        # Auto-start previously active cameras (after a brief delay for service stability)
        if self._oauth_info:
            asyncio.create_task(self._delayed_auto_start_async())

    async def deinit_async(self) -> None:
        """Deinitialize the service."""
        # Stop all cameras
        for did in list(self._active_cameras.keys()):
            await self.stop_camera_async(did)

        # Cleanup
        if self._camera_manager:
            await self._camera_manager.deinit_async()
            self._camera_manager = None

        if self._http_client:
            await self._http_client.deinit_async()
            self._http_client = None

        if self._oauth_client:
            await self._oauth_client.deinit_async()
            self._oauth_client = None

        _LOGGER.info("Camera service deinitialized")

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
        
        _LOGGER.info("OAuth authentication successful")
        return True

    async def set_tokens_async(
        self,
        cloud_server: str,
        access_token: str,
        refresh_token: str,
        expires_ts: int,
    ) -> None:
        """Set tokens directly (from HA integration)."""
        # Validate token is not a placeholder
        if access_token in ("managed_by_addon", "", None):
            _LOGGER.warning("Ignoring invalid placeholder token")
            return
            
        self._cloud_server = cloud_server
        self._oauth_info = MIoTOauthInfo(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_ts=expires_ts,
        )
        
        await self._save_tokens_async()
        await self._init_camera_manager_async()
        
        _LOGGER.info("Tokens set successfully for server: %s", cloud_server)

    async def refresh_tokens_async(self) -> bool:
        """Refresh access token."""
        if not self._oauth_client or not self._oauth_info:
            return False

        try:
            self._oauth_info = await self._oauth_client.refresh_access_token_async(
                self._oauth_info.refresh_token
            )
            await self._save_tokens_async()
            
            # Update camera manager
            if self._camera_manager:
                await self._camera_manager.update_access_token_async(
                    self._oauth_info.access_token
                )
            
            _LOGGER.info("Tokens refreshed successfully")
            return True
        except Exception as e:
            _LOGGER.error("Failed to refresh tokens: %s", e)
            return False

    # ==================== Device Discovery ====================

    async def discover_devices_async(self) -> Dict[str, MIoTDeviceInfo]:
        """Discover devices from cloud."""
        if not self._http_client:
            raise ValueError("Not authenticated")

        # Get all devices
        self._device_list = await self._http_client.get_devices_async()
        _LOGGER.info("Total devices from cloud: %d", len(self._device_list))
        
        # Filter cameras
        extra_info = await get_camera_extra_info()
        self._camera_list = {}
        
        for did, device in self._device_list.items():
            # Check if device is a camera
            if self._is_camera_device(device, extra_info):
                channel_count = self._get_channel_count(device.model, extra_info)
                self._camera_list[did] = MIoTCameraInfo(
                    **device.model_dump(),
                    channel_count=channel_count,
                    camera_status=MIoTCameraStatus.DISCONNECTED,
                )
                _LOGGER.info("Found camera: %s (%s) with %d channel(s)", 
                            device.name, device.model, channel_count)
        
        _LOGGER.info("Discovered %d cameras out of %d devices", 
                    len(self._camera_list), len(self._device_list))
        return self._device_list

    async def get_cameras_async(self) -> Dict[str, MIoTCameraInfo]:
        """Get discovered cameras."""
        if not self._camera_list:
            await self.discover_devices_async()
        return self._camera_list

    # ==================== Camera Control ====================

    async def start_camera_async(
        self,
        did: str,
        pin_code: Optional[str] = None,
        quality: int = 3,  # 1=LOW, 3=HIGH, 4/5=experimental
        enable_audio: bool = False,
    ) -> None:
        """Start streaming a camera.
        
        Behavior:
        - If camera is already active with SAME quality: returns immediately (0 delay)
        - If camera is already active with DIFFERENT quality: restarts with new quality
        - If camera is not active: starts camera and waits for stream to be ready
        
        This ensures WebRTC stream is ready when user opens camera.
        """
        if not self._camera_manager:
            raise ValueError("Camera manager not initialized")

        if did not in self._camera_list:
            raise ValueError(f"Camera not found: {did}")

        camera_info = self._camera_list[did]
        
        # Check if camera is already active
        if did in self._active_cameras:
            # Check if quality has changed
            current_quality = self._camera_qualities.get(did)
            if current_quality != quality:
                _LOGGER.info("Camera %s quality changed from %s to %d, restarting...", 
                            did, current_quality, quality)
                await self.stop_camera_async(did)
                # Continue to start with new quality
            else:
                # Same quality, check if stream is ready
                stream_ready = await self._check_stream_ready_async(did, 0)
                if stream_ready:
                    _LOGGER.info("Camera %s already streaming with quality=%d, returning immediately", 
                                did, quality)
                    return
                else:
                    _LOGGER.info("Camera %s active but stream not ready, waiting...", did)
                    # Wait for stream to be ready
                    if self._rtsp_streamer:
                        for channel in range(camera_info.channel_count):
                            await self._wait_for_stream_ready_async(did, channel)
                    _LOGGER.info("Camera %s stream now ready", did)
                    return
        
        # Create camera instance (first time)
        _LOGGER.info("Starting new camera: %s", did)
        instance = await self._camera_manager.create_camera_async(camera_info)
        self._active_cameras[did] = instance
        
        # Start RTSP streams first (before registering callbacks)
        if self._rtsp_streamer:
            for channel in range(camera_info.channel_count):
                await self._rtsp_streamer.start_stream(did, channel)
                _LOGGER.info("Started RTSP stream for %s channel %d", did, channel)
        
        # Register callbacks for each channel
        for channel in range(camera_info.channel_count):
            # Raw video -> RTSP
            await self._camera_manager.register_raw_video_async(
                did=did,
                channel=channel,
                callback=self._on_raw_video_frame,
            )
            
            # Decoded JPG -> Snapshot
            await self._camera_manager.register_decode_jpg_async(
                did=did,
                channel=channel,
                callback=self._on_decoded_jpg,
            )
            
            # Status changed
            await self._camera_manager.register_status_changed_async(
                did=did,
                callback=self._on_camera_status_changed,
            )
        
        # Start streaming
        # Use a list of QualityValue to allow any integer (including experimental 4/5)
        quality_list = [QualityValue(quality) for _ in range(camera_info.channel_count)]
        _LOGGER.info("Starting camera %s with quality=%d (list=%s)", did, quality, quality_list)
        
        await self._camera_manager.start_camera_async(
            did=did,
            pin_code=pin_code,
            qualities=quality_list,
            enable_audio=enable_audio,
            enable_reconnect=True,
        )
        
        # Record the quality for this camera
        self._camera_qualities[did] = quality
        
        # Save active cameras for auto-restart on Add-on reboot
        await self._save_active_cameras_async()
        
        # Always wait for stream to be ready for new cameras
        # This ensures WebRTC can start immediately when user opens camera
        if self._rtsp_streamer:
            for channel in range(camera_info.channel_count):
                await self._wait_for_stream_ready_async(did, channel)
        
        _LOGGER.info("Started camera: %s (stream ready)", did)

    async def stop_camera_async(self, did: str) -> None:
        """Stop streaming a camera and release connection."""
        if not self._camera_manager:
            return

        if did in self._active_cameras:
            # Stop streaming first
            try:
                await self._camera_manager.stop_camera_async(did)
            except Exception as e:
                _LOGGER.warning("Error stopping camera %s: %s", did, e)
            
            # IMPORTANT: Destroy camera instance to release connection
            # Without this, connections accumulate and cause "too many connections" error
            try:
                await self._camera_manager.destroy_camera_async(did)
                _LOGGER.info("Destroyed camera instance: %s", did)
            except Exception as e:
                _LOGGER.warning("Error destroying camera %s: %s", did, e)
            
            # Stop RTSP streams
            camera_info = self._camera_list.get(did)
            if camera_info and self._rtsp_streamer:
                for channel in range(camera_info.channel_count):
                    await self._rtsp_streamer.stop_stream(did, channel)
            
            del self._active_cameras[did]
            
            # Clear quality record
            if did in self._camera_qualities:
                del self._camera_qualities[did]
            
            # Update saved active cameras
            await self._save_active_cameras_async()
            
            _LOGGER.info("Stopped camera: %s (connection released)", did)

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
                    _LOGGER.warning("Invalid saved tokens (placeholder), ignoring")
                    # Delete invalid tokens file
                    TOKENS_FILE.unlink()
                    return
                
                self._oauth_info = oauth_info
                await self._init_camera_manager_async()
                _LOGGER.info("Loaded saved tokens")
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
            
            _LOGGER.info("Saved tokens")
        except Exception as e:
            _LOGGER.error("Failed to save tokens: %s", e)

    async def _save_active_cameras_async(self) -> None:
        """Save active cameras list for auto-restart on boot."""
        try:
            import aiofiles
            CONFIG_PATH.mkdir(parents=True, exist_ok=True)
            
            data = {
                "active_dids": list(self._active_cameras.keys()),
            }
            
            async with aiofiles.open(ACTIVE_CAMERAS_FILE, "w") as f:
                await f.write(json.dumps(data, indent=2))
            
            _LOGGER.debug("Saved active cameras: %s", list(self._active_cameras.keys()))
        except Exception as e:
            _LOGGER.error("Failed to save active cameras: %s", e)

    async def _load_and_start_active_cameras_async(self) -> None:
        """Load and auto-start previously active cameras."""
        if not ACTIVE_CAMERAS_FILE.exists():
            return

        try:
            import aiofiles
            async with aiofiles.open(ACTIVE_CAMERAS_FILE, "r") as f:
                data = json.loads(await f.read())
            
            active_dids = data.get("active_dids", [])
            if not active_dids:
                return
            
            _LOGGER.info("Found %d previously active cameras to auto-start", len(active_dids))
            
            # Discover cameras first
            if not self._camera_list:
                await self.discover_devices_async()
            
            # Start each camera
            for did in active_dids:
                if did in self._camera_list:
                    try:
                        _LOGGER.info("Auto-starting camera: %s", did)
                        await self.start_camera_async(did)
                    except Exception as e:
                        _LOGGER.warning("Failed to auto-start camera %s: %s", did, e)
                else:
                    _LOGGER.warning("Previously active camera %s not found, skipping", did)
            
            _LOGGER.info("Auto-start complete, %d cameras active", len(self._active_cameras))
        except Exception as e:
            _LOGGER.warning("Failed to load active cameras: %s", e)

    def _is_camera_device(self, device: MIoTDeviceInfo, extra_info) -> bool:
        """Check if device is a camera."""
        _LOGGER.debug("Checking device: %s (model: %s)", device.did, device.model)
        
        # Check by model prefix
        if device.model.startswith(("chuangmi.camera", "isa.camera", "xiaomi.camera", "mxiang.camera")):
            # Check denylist
            denylist = extra_info.denylist.get("camera", {})
            if device.model in denylist:
                _LOGGER.debug("Camera %s is in denylist", device.model)
                return False
            _LOGGER.debug("Device %s is a camera (model prefix match)", device.did)
            return True
        
        # Check allowlist for other device types (wifispeaker with camera)
        for cls_name, models in extra_info.allowlist.items():
            if device.model in models:
                _LOGGER.debug("Device %s is in allowlist (%s)", device.did, cls_name)
                return True
        
        _LOGGER.debug("Device %s is not a camera", device.did)
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
            
            # Log frame count periodically for debugging
            key = f"{did}_{channel}"
            frame_count = self._rtsp_streamer._frame_counts.get(key, 0)
            # Log first frame, then every 30 frames (about once per second at 30fps)
            if frame_count == 1:
                _LOGGER.info("Camera %s channel %d: first frame received (size=%d)", did, channel, len(data))
            elif frame_count > 0 and frame_count % 30 == 0:
                _LOGGER.info("Camera %s channel %d: %d frames pushed", did, channel, frame_count)

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
        _LOGGER.info("Camera %s status changed: %s", did, status)
        
        if did in self._camera_list:
            self._camera_list[did].camera_status = status
        
        # Log detailed info for debugging
        if status == MIoTCameraStatus.DISCONNECTED:
            _LOGGER.warning("Camera %s disconnected, miot_kit will attempt to reconnect", did)
        elif status == MIoTCameraStatus.CONNECTED:
            _LOGGER.info("Camera %s connected/reconnected, frames should start flowing", did)
        
        if self._on_status_changed:
            await self._on_status_changed(did, status)

    async def _delayed_auto_start_async(self) -> None:
        """Auto-start cameras after a brief delay for service stability."""
        try:
            # Wait for service to be fully ready
            await asyncio.sleep(2)
            await self._load_and_start_active_cameras_async()
        except Exception as e:
            _LOGGER.error("Error in delayed auto-start: %s", e)

    async def _check_stream_ready_async(self, did: str, channel: int) -> bool:
        """Check if RTSP stream is currently ready (non-blocking).
        
        Args:
            did: Device ID
            channel: Camera channel
            
        Returns:
            True if stream is ready and publishing, False otherwise
        """
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
        except Exception as e:
            _LOGGER.debug("Error checking MediaMTX: %s", e)
        
        return False

    async def _wait_for_stream_ready_async(
        self,
        did: str,
        channel: int,
        timeout: float = 10.0,
    ) -> bool:
        """Wait for RTSP stream to be publishing to MediaMTX.
        
        This prevents the "frozen first frame" issue by ensuring the stream
        is actually ready before returning from start_camera.
        
        Args:
            did: Device ID
            channel: Camera channel
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if stream is ready, False if timeout
        """
        stream_key = f"{did}_{channel}"
        start_time = asyncio.get_event_loop().time()
        
        _LOGGER.info("Waiting for RTSP stream %s to be ready...", stream_key)
        
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            if await self._check_stream_ready_async(did, channel):
                _LOGGER.info("RTSP stream %s is ready", stream_key)
                return True
            await asyncio.sleep(0.5)
        
        _LOGGER.warning("Timeout waiting for RTSP stream %s to be ready", stream_key)
        return False
