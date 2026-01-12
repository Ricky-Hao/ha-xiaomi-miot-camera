# -*- coding: utf-8 -*-
"""Camera manager - wraps native library."""
import asyncio
import logging
from ctypes import (
    CDLL, CFUNCTYPE, POINTER, Structure, byref, string_at,
    c_bool, c_char_p, c_int, c_uint8, c_uint32, c_uint64, c_void_p
)
from pathlib import Path
import platform
from typing import Any, Callable, Coroutine, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

# OAuth2 constants
PROJECT_CODE = "mico"
OAUTH2_API_HOST_DEFAULT = f"{PROJECT_CODE}.api.mijia.tech"
OAUTH2_CLIENT_ID = "2882303761520431603"

# Callback types
_MIOT_CAMERA_LOG_HANDLER = CFUNCTYPE(None, c_int, c_char_p)
_MIOT_CAMERA_ON_STATUS_CHANGED = CFUNCTYPE(None, c_int)


class _MIoTCameraFrameHeaderC(Structure):
    """MIoT Camera Raw Data C."""
    _fields_ = [
        ("codec_id", c_uint32),
        ("length", c_uint32),
        ("timestamp", c_uint64),
        ("sequence", c_uint32),
        ("frame_type", c_uint32),
        ("channel", c_uint8)
    ]


_MIOT_CAMERA_ON_RAW_DATA = CFUNCTYPE(None, POINTER(_MIoTCameraFrameHeaderC), POINTER(c_uint8))


class _MIoTCameraInfoC(Structure):
    """MIoT Camera Info C."""
    _fields_ = [
        ("did", c_char_p),
        ("model", c_char_p),
        ("channel_count", c_uint8)
    ]


class _MIoTCameraConfigC(Structure):
    """MIoT Camera Config C."""
    _fields_ = [
        ("video_qualities", POINTER(c_uint8)),
        ("enable_audio", c_bool),
        ("pin_code", c_char_p),
    ]


class _MIoTCameraInstanceC(c_void_p):
    """MIoT Camera Clang Instance."""


def _load_dynamic_lib() -> CDLL:
    """Load the native camera library."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    # In Docker container, libs are at /app/libs/
    # Locally, they're relative to this file's location
    lib_base = Path("/app/libs")
    if not lib_base.exists():
        # Fallback for local development
        lib_base = Path(__file__).parent.parent.parent / "libs"

    if system == "linux":
        if machine in ("x86_64", "amd64"):
            lib_path = lib_base / "linux" / "x86_64"
        elif machine in ("arm64", "aarch64"):
            lib_path = lib_base / "linux" / "arm64"
        else:
            raise RuntimeError(f"Unsupported Linux architecture: {machine}")
        lib_path = lib_path / "libmiot_camera_lite.so"
    else:
        raise RuntimeError(f"Unsupported system: {system}")

    if not lib_path.exists():
        raise FileNotFoundError(f"Library not found: {lib_path}")

    _LOGGER.info("Loading native library: %s", lib_path)
    lib = CDLL(str(lib_path))

    # Setup function signatures
    lib.miot_camera_set_log_handler.argtypes = [_MIOT_CAMERA_LOG_HANDLER]
    lib.miot_camera_set_log_handler.restype = None

    lib.miot_camera_init.argtypes = [c_char_p, c_char_p, c_char_p]
    lib.miot_camera_init.restype = c_int

    lib.miot_camera_deinit.argtypes = []
    lib.miot_camera_deinit.restype = None

    lib.miot_camera_update_access_token.argtypes = [c_char_p]
    lib.miot_camera_update_access_token.restype = c_int

    lib.miot_camera_new.argtypes = [POINTER(_MIoTCameraInfoC)]
    lib.miot_camera_new.restype = _MIoTCameraInstanceC

    lib.miot_camera_free.argtypes = [_MIoTCameraInstanceC]
    lib.miot_camera_free.restype = None

    lib.miot_camera_start.argtypes = [_MIoTCameraInstanceC, POINTER(_MIoTCameraConfigC)]
    lib.miot_camera_start.restype = c_int

    lib.miot_camera_stop.argtypes = [_MIoTCameraInstanceC]
    lib.miot_camera_stop.restype = c_int

    lib.miot_camera_status.argtypes = [_MIoTCameraInstanceC]
    lib.miot_camera_status.restype = c_int

    lib.miot_camera_version.argtypes = []
    lib.miot_camera_version.restype = c_char_p

    lib.miot_camera_register_status_changed.argtypes = [
        _MIoTCameraInstanceC, _MIOT_CAMERA_ON_STATUS_CHANGED]
    lib.miot_camera_register_status_changed.restype = c_int

    lib.miot_camera_unregister_status_changed.argtypes = [_MIoTCameraInstanceC]
    lib.miot_camera_unregister_status_changed.restype = c_int

    lib.miot_camera_register_raw_data.argtypes = [_MIoTCameraInstanceC, _MIOT_CAMERA_ON_RAW_DATA, c_uint8]
    lib.miot_camera_register_raw_data.restype = c_int

    lib.miot_camera_unregister_raw_data.argtypes = [_MIoTCameraInstanceC, c_uint8]
    lib.miot_camera_unregister_raw_data.restype = c_int

    return lib


class CameraInstance:
    """Individual camera instance."""

    def __init__(
        self,
        manager: "CameraManager",
        did: str,
        model: str,
        channel_count: int = 1,
        rtsp_streamer: Optional["RTSPStreamer"] = None
    ):
        self._manager = manager
        self._did = did
        self._model = model
        self._channel_count = channel_count
        self._c_instance: Optional[_MIoTCameraInstanceC] = None
        self._callback_refs: Dict[str, Any] = {}
        self._main_loop = asyncio.get_event_loop()

        # Decoder for JPG output (for camera_image)
        from .decoder import MIoTMediaDecoder
        self._decoder = MIoTMediaDecoder(enable_hw_accel=False)

        # RTSP streamer (for live streaming)
        self._rtsp_streamer = rtsp_streamer

        # Callbacks
        self._status_callbacks: List[Callable] = []
        self._raw_video_callbacks: Dict[int, List[Callable]] = {}
        self._raw_audio_callbacks: Dict[int, List[Callable]] = {}
        self._jpg_callbacks: Dict[int, List[Callable]] = {}
        self._pcm_callbacks: Dict[int, List[Callable]] = {}

    @property
    def did(self) -> str:
        return self._did

    async def create_async(self):
        """Create the C camera instance."""
        lib = self._manager.lib

        info = _MIoTCameraInfoC(
            did=self._did.encode("utf-8"),
            model=self._model.encode("utf-8"),
            channel_count=self._channel_count
        )

        self._c_instance = lib.miot_camera_new(byref(info))
        if not self._c_instance:
            raise RuntimeError(f"Failed to create camera instance: {self._did}")

        _LOGGER.info("Created camera instance: %s", self._did)

    async def destroy_async(self):
        """Destroy the camera instance."""
        if self._c_instance:
            await self.stop_async()
            self._manager.lib.miot_camera_free(self._c_instance)
            self._c_instance = None
            _LOGGER.info("Destroyed camera instance: %s", self._did)

    async def start_async(
        self,
        pin_code: Optional[str] = None,
        qualities: List[int] = None,
        enable_audio: bool = False,
        enable_reconnect: bool = False
    ):
        """Start camera streaming."""
        if not self._c_instance:
            raise RuntimeError("Camera instance not created")

        qualities = qualities or [1]  # LOW quality default

        # Create quality array
        quality_array = (c_uint8 * (len(qualities) + 1))()
        for i, q in enumerate(qualities):
            quality_array[i] = q
        quality_array[len(qualities)] = 0  # Null terminator

        config = _MIoTCameraConfigC(
            video_qualities=quality_array,
            enable_audio=enable_audio,
            pin_code=pin_code.encode("utf-8") if pin_code else None
        )

        # Register raw data callback
        self._callback_refs["raw_data"] = _MIOT_CAMERA_ON_RAW_DATA(self._on_raw_data)
        _LOGGER.info("Registering raw data callback for camera %s", self._did)
        self._manager.lib.miot_camera_register_raw_data(
            self._c_instance,
            self._callback_refs["raw_data"],
            0  # channel
        )

        _LOGGER.info("Starting camera %s with qualities=%s", self._did, qualities)
        result = self._manager.lib.miot_camera_start(self._c_instance, byref(config))
        if result != 0:
            raise RuntimeError(f"Failed to start camera: {result}")

        # Start RTSP stream for live streaming
        if self._rtsp_streamer:
            await self._rtsp_streamer.start_stream(self._did, channel=0)

        _LOGGER.info("Started camera: %s", self._did)

    async def stop_async(self):
        """Stop camera streaming."""
        if self._c_instance:
            # Stop RTSP stream
            if self._rtsp_streamer:
                await self._rtsp_streamer.stop_stream(self._did, channel=0)
            
            self._manager.lib.miot_camera_stop(self._c_instance)
            _LOGGER.info("Stopped camera: %s", self._did)

    async def get_status_async(self) -> int:
        """Get camera status."""
        if not self._c_instance:
            return -1
        return self._manager.lib.miot_camera_status(self._c_instance)

    def _on_raw_data(self, header: _MIoTCameraFrameHeaderC, data: POINTER(c_uint8)):
        """Handle raw data from camera.
        
        MIoT Camera Codec IDs (from native library):
        - VIDEO_H264 = 4
        - VIDEO_HEVC/VIDEO_H265 = 5
        - AUDIO_PCM = 1024
        - AUDIO_G711U = 1026
        - AUDIO_G711A = 1027
        - AUDIO_OPUS = 1032
        """
        from .decoder import MIoTCameraCodec
        
        try:
            frame_data = string_at(data, header.contents.length)
            timestamp = header.contents.timestamp
            sequence = header.contents.sequence
            channel = header.contents.channel
            codec_id = header.contents.codec_id
            frame_type = header.contents.frame_type

            _LOGGER.debug(
                "Received raw frame: did=%s, codec=%d, channel=%d, type=%d, len=%d",
                self._did, codec_id, channel, frame_type, len(frame_data)
            )

            # Check if video codec (H.264=4 or H.265=5)
            is_video = codec_id in (MIoTCameraCodec.VIDEO_H264, MIoTCameraCodec.VIDEO_H265)
            
            # Check if audio codec
            is_audio = codec_id in (
                MIoTCameraCodec.AUDIO_PCM,
                MIoTCameraCodec.AUDIO_G711U,
                MIoTCameraCodec.AUDIO_G711A,
                MIoTCameraCodec.AUDIO_OPUS
            )
            
            # Also detect format by data header for fallback
            is_jpeg = len(frame_data) >= 2 and frame_data[:2] == b'\xff\xd8'

            # JPEG data (already decoded, just forward)
            if is_jpeg:
                _LOGGER.debug(
                    "Valid JPEG frame: %d bytes, jpg_callbacks channels: %s",
                    len(frame_data), list(self._jpg_callbacks.keys())
                )
                for cb in self._jpg_callbacks.get(channel, []):
                    asyncio.run_coroutine_threadsafe(
                        cb(self._did, frame_data, timestamp, channel),
                        self._main_loop
                    )

            # Video frame (H.264/H.265)
            elif is_video:
                # Push to RTSP stream (for live streaming)
                if self._rtsp_streamer:
                    asyncio.run_coroutine_threadsafe(
                        self._rtsp_streamer.push_frame(self._did, frame_data, channel),
                        self._main_loop
                    )
                
                # Raw video callbacks
                for cb in self._raw_video_callbacks.get(channel, []):
                    asyncio.run_coroutine_threadsafe(
                        cb(self._did, frame_data, timestamp, sequence, channel),
                        self._main_loop
                    )

                # Decode to JPG (for camera_image / snapshots)
                # Only decode periodically to save CPU
                _LOGGER.debug(
                    "Video frame: codec=%d, len=%d, frame_type=%d",
                    codec_id, len(frame_data), frame_type
                )
                
                # Only decode I-frames for snapshots (save CPU)
                if frame_type == 1 and self._jpg_callbacks.get(channel):  # I-frame
                    try:
                        jpg_data = self._decoder.decode_to_jpg(
                            frame_data, codec_id, stream_id=f"{self._did}_{channel}"
                        )
                        if jpg_data:
                            _LOGGER.debug("Decoded I-frame to JPG: %d bytes", len(jpg_data))
                            for cb in self._jpg_callbacks.get(channel, []):
                                asyncio.run_coroutine_threadsafe(
                                    cb(self._did, jpg_data, timestamp, channel),
                                    self._main_loop
                                )
                    except Exception as e:
                        _LOGGER.debug("Failed to decode I-frame: %s", e)

            # Audio frame
            elif is_audio:
                for cb in self._raw_audio_callbacks.get(channel, []):
                    asyncio.run_coroutine_threadsafe(
                        cb(self._did, frame_data, timestamp, sequence, channel),
                        self._main_loop
                    )

            else:
                _LOGGER.debug(
                    "Unknown frame format: codec=%d, len=%d, header=%s",
                    codec_id, len(frame_data),
                    frame_data[:4].hex() if len(frame_data) >= 4 else "too short"
                )

        except Exception as e:
            _LOGGER.exception("Error in raw data callback: %s", e)

    async def register_raw_video_async(self, channel: int, callback: Callable):
        """Register raw video callback."""
        if channel not in self._raw_video_callbacks:
            self._raw_video_callbacks[channel] = []
        self._raw_video_callbacks[channel].append(callback)

    async def register_raw_audio_async(self, channel: int, callback: Callable):
        """Register raw audio callback."""
        if channel not in self._raw_audio_callbacks:
            self._raw_audio_callbacks[channel] = []
        self._raw_audio_callbacks[channel].append(callback)

    async def register_decode_jpg_async(self, channel: int, callback: Callable):
        """Register decoded JPG callback."""
        if channel not in self._jpg_callbacks:
            self._jpg_callbacks[channel] = []
        self._jpg_callbacks[channel].append(callback)

    async def register_decode_pcm_async(self, channel: int, callback: Callable):
        """Register decoded PCM callback."""
        if channel not in self._pcm_callbacks:
            self._pcm_callbacks[channel] = []
        self._pcm_callbacks[channel].append(callback)


class CameraManager:
    """Manager for all camera instances."""

    def __init__(self):
        self._lib: Optional[CDLL] = None
        self._cameras: Dict[str, CameraInstance] = {}
        self._log_handler: Optional[Any] = None
        self._initialized = False
        
        # RTSP streamer for live streaming
        from .rtsp_streamer import RTSPStreamer
        self._rtsp_streamer = RTSPStreamer()

    @property
    def lib(self) -> CDLL:
        if not self._lib:
            raise RuntimeError("Camera library not initialized")
        return self._lib

    async def init_async(self, cloud_server: str, access_token: str):
        """Initialize the camera library."""
        if self._initialized:
            _LOGGER.warning("Camera manager already initialized")
            return

        self._lib = _load_dynamic_lib()

        # Setup log handler
        self._log_handler = _MIOT_CAMERA_LOG_HANDLER(self._on_log)
        self._lib.miot_camera_set_log_handler(self._log_handler)

        # Build host
        host = OAUTH2_API_HOST_DEFAULT
        if cloud_server != "cn":
            host = f"{cloud_server}.{OAUTH2_API_HOST_DEFAULT}"

        result = self._lib.miot_camera_init(
            host.encode("utf-8"),
            OAUTH2_CLIENT_ID.encode("utf-8"),
            access_token.encode("utf-8")
        )

        if result != 0:
            raise RuntimeError(f"Failed to initialize camera library: {result}")

        self._initialized = True
        _LOGGER.info("Camera library initialized")

    async def deinit_async(self):
        """Deinitialize the camera library."""
        if not self._initialized:
            return

        for did in list(self._cameras.keys()):
            await self.destroy_camera_async(did)

        if self._lib:
            self._lib.miot_camera_deinit()
            self._lib = None

        self._initialized = False
        _LOGGER.info("Camera library deinitialized")

    async def update_access_token_async(self, access_token: str):
        """Update access token."""
        if not self._lib:
            raise RuntimeError("Camera library not initialized")
        self._lib.miot_camera_update_access_token(access_token.encode("utf-8"))

    async def get_version_async(self) -> str:
        """Get library version."""
        if not self._lib:
            raise RuntimeError("Camera library not initialized")
        result: bytes = self._lib.miot_camera_version()
        return result.decode("utf-8")

    async def create_camera_async(self, camera_info: dict) -> CameraInstance:
        """Create a camera instance."""
        did = camera_info.get("did")
        if not did:
            raise ValueError("did is required")

        if did in self._cameras:
            return self._cameras[did]

        camera = CameraInstance(
            manager=self,
            did=did,
            model=camera_info.get("model", "unknown"),
            channel_count=camera_info.get("channel_count", 1),
            rtsp_streamer=self._rtsp_streamer
        )
        await camera.create_async()
        self._cameras[did] = camera
        return camera

    async def destroy_camera_async(self, did: str):
        """Destroy a camera instance."""
        if did not in self._cameras:
            return
        camera = self._cameras.pop(did)
        await camera.destroy_async()

    async def start_camera_async(
        self,
        did: str,
        pin_code: Optional[str] = None,
        qualities: List[int] = None,
        enable_audio: bool = False,
        enable_reconnect: bool = False
    ):
        """Start camera streaming."""
        if did not in self._cameras:
            raise ValueError(f"Camera not found: {did}")
        await self._cameras[did].start_async(
            pin_code=pin_code,
            qualities=qualities,
            enable_audio=enable_audio,
            enable_reconnect=enable_reconnect
        )

    async def stop_camera_async(self, did: str):
        """Stop camera streaming."""
        if did not in self._cameras:
            raise ValueError(f"Camera not found: {did}")
        await self._cameras[did].stop_async()

    async def get_status_async(self, did: str) -> int:
        """Get camera status."""
        if did not in self._cameras:
            raise ValueError(f"Camera not found: {did}")
        return await self._cameras[did].get_status_async()

    async def register_raw_video_async(self, did: str, channel: int, callback: Callable):
        """Register raw video callback."""
        if did not in self._cameras:
            raise ValueError(f"Camera not found: {did}")
        await self._cameras[did].register_raw_video_async(channel, callback)

    async def register_raw_audio_async(self, did: str, channel: int, callback: Callable):
        """Register raw audio callback."""
        if did not in self._cameras:
            raise ValueError(f"Camera not found: {did}")
        await self._cameras[did].register_raw_audio_async(channel, callback)

    async def register_decode_jpg_async(self, did: str, channel: int, callback: Callable):
        """Register decoded JPG callback."""
        if did not in self._cameras:
            raise ValueError(f"Camera not found: {did}")
        await self._cameras[did].register_decode_jpg_async(channel, callback)

    async def register_decode_pcm_async(self, did: str, channel: int, callback: Callable):
        """Register decoded PCM callback."""
        if did not in self._cameras:
            raise ValueError(f"Camera not found: {did}")
        await self._cameras[did].register_decode_pcm_async(channel, callback)

    def _on_log(self, level: int, msg: bytes):
        """Handle log from native library."""
        _LOGGER.info("[Native] %s", msg.decode("utf-8"))
