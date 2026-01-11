# -*- coding: utf-8 -*-
"""
Proxy client for connecting to the Camera Proxy Add-on.

This module provides a client that connects to the Camera Proxy Add-on via WebSocket,
allowing the custom component to work on Home Assistant OS (Alpine/musl) by delegating
the native library calls to a glibc-based container.
"""
import asyncio
import base64
import json
import logging
import uuid
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

import aiohttp

from .types import MIoTCameraInfo, MIoTCameraStatus, MIoTCameraVideoQuality

_LOGGER = logging.getLogger(__name__)

# Default Add-on WebSocket URL
DEFAULT_PROXY_URL = "ws://127.0.0.1:8765/ws"


class CameraProxyClient:
    """Client for Camera Proxy Add-on."""

    def __init__(
        self,
        proxy_url: str = DEFAULT_PROXY_URL,
        loop: Optional[asyncio.AbstractEventLoop] = None
    ):
        """Initialize the proxy client."""
        self._proxy_url = proxy_url
        self._loop = loop or asyncio.get_event_loop()
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._frame_callbacks: Dict[str, Dict[int, List[Callable]]] = {}
        self._status_callbacks: Dict[str, List[Callable]] = {}
        self._receive_task: Optional[asyncio.Task] = None
        self._connected = False

    @property
    def connected(self) -> bool:
        """Return connection status."""
        return self._connected and self._ws is not None and not self._ws.closed

    async def connect_async(self) -> bool:
        """Connect to the proxy server."""
        if self._connected:
            return True

        try:
            self._session = aiohttp.ClientSession()
            self._ws = await self._session.ws_connect(self._proxy_url)
            self._connected = True
            self._receive_task = asyncio.create_task(self._receive_loop())
            _LOGGER.info("Connected to camera proxy: %s", self._proxy_url)
            return True
        except Exception as e:
            _LOGGER.error("Failed to connect to camera proxy: %s", e)
            await self._cleanup()
            return False

    async def disconnect_async(self):
        """Disconnect from the proxy server."""
        await self._cleanup()

    async def _cleanup(self):
        """Clean up resources."""
        self._connected = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self._session:
            await self._session.close()
            self._session = None

        # Cancel pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()

    async def _receive_loop(self):
        """Receive messages from WebSocket."""
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("WebSocket error: %s", self._ws.exception())
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.exception("Error in receive loop: %s", e)
        finally:
            self._connected = False

    async def _handle_message(self, data: str):
        """Handle incoming WebSocket message."""
        try:
            message = json.loads(data)
            msg_type = message.get("type")
            msg_id = message.get("id")

            # Frame message
            if msg_type == "frame":
                await self._handle_frame(message)
                return

            # Response to a request
            if msg_id and msg_id in self._pending_requests:
                future = self._pending_requests.pop(msg_id)
                if not future.done():
                    if message.get("success"):
                        future.set_result(message)
                    else:
                        future.set_exception(Exception(message.get("error", "Unknown error")))

        except json.JSONDecodeError as e:
            _LOGGER.error("Invalid JSON from proxy: %s", e)
        except Exception as e:
            _LOGGER.exception("Error handling message: %s", e)

    async def _handle_frame(self, message: dict):
        """Handle frame message."""
        did = message.get("did")
        channel = message.get("channel", 0)
        frame_type = message.get("frame_type")
        timestamp = message.get("timestamp", 0)
        sequence = message.get("sequence", 0)
        data_b64 = message.get("data")

        if not did or not data_b64:
            return

        # Decode base64 data
        try:
            data = base64.b64decode(data_b64)
        except Exception as e:
            _LOGGER.warning("Failed to decode frame data: %s", e)
            return

        # Call registered callbacks
        if did in self._frame_callbacks:
            callbacks = self._frame_callbacks[did].get(channel, [])
            for callback in callbacks:
                try:
                    if frame_type in ("jpg", "pcm"):
                        await callback(did, data, timestamp, channel)
                    else:  # raw_video, raw_audio
                        await callback(did, data, timestamp, sequence, channel)
                except Exception as e:
                    _LOGGER.warning("Error in frame callback: %s", e)

    async def _send_request(self, msg_type: str, **params) -> dict:
        """Send a request and wait for response."""
        if not self.connected:
            raise ConnectionError("Not connected to proxy")

        msg_id = str(uuid.uuid4())
        message = {"type": msg_type, "id": msg_id, **params}

        future = asyncio.get_event_loop().create_future()
        self._pending_requests[msg_id] = future

        try:
            await self._ws.send_json(message)
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending_requests.pop(msg_id, None)
            raise TimeoutError(f"Request {msg_type} timed out")

    # Public API - mirrors MIoTCamera interface

    async def init_async(self, cloud_server: str, access_token: str) -> str:
        """Initialize the camera library via proxy."""
        if not self.connected:
            await self.connect_async()

        result = await self._send_request(
            "init",
            cloud_server=cloud_server,
            access_token=access_token
        )
        return result.get("version", "unknown")

    async def update_access_token_async(self, access_token: str):
        """Update access token."""
        await self._send_request("update_token", access_token=access_token)

    async def create_camera_async(self, camera_info: MIoTCameraInfo | dict):
        """Create a camera instance."""
        if isinstance(camera_info, MIoTCameraInfo):
            camera_info = camera_info.model_dump()
        await self._send_request("create_camera", camera_info=camera_info)

    async def destroy_camera_async(self, did: str):
        """Destroy a camera instance."""
        await self._send_request("destroy_camera", did=did)

    async def start_camera_async(
        self,
        did: str,
        pin_code: Optional[str] = None,
        qualities: MIoTCameraVideoQuality | List[MIoTCameraVideoQuality] = MIoTCameraVideoQuality.LOW,
        enable_audio: bool = False,
        enable_reconnect: bool = False
    ):
        """Start camera streaming."""
        # Convert qualities to list of ints
        if isinstance(qualities, MIoTCameraVideoQuality):
            quality_list = [qualities.value]
        else:
            quality_list = [q.value if isinstance(q, MIoTCameraVideoQuality) else q for q in qualities]

        await self._send_request(
            "start_camera",
            did=did,
            pin_code=pin_code,
            qualities=quality_list,
            enable_audio=enable_audio,
            enable_reconnect=enable_reconnect
        )

    async def stop_camera_async(self, did: str):
        """Stop camera streaming."""
        await self._send_request("stop_camera", did=did)

    async def get_camera_status_async(self, did: str) -> MIoTCameraStatus:
        """Get camera status."""
        result = await self._send_request("get_status", did=did)
        status_value = result.get("camera_status", -1)
        return MIoTCameraStatus(status_value)

    async def register_decode_jpg_async(
        self,
        did: str,
        callback: Callable[[str, bytes, int, int], Coroutine],
        channel: int = 0
    ):
        """Register decoded JPG callback."""
        # Track callback locally
        if did not in self._frame_callbacks:
            self._frame_callbacks[did] = {}
        if channel not in self._frame_callbacks[did]:
            self._frame_callbacks[did][channel] = []
        self._frame_callbacks[did][channel].append(callback)

        # Subscribe to frames from proxy
        await self._send_request(
            "subscribe_frames",
            did=did,
            channel=channel,
            frame_type="jpg"
        )

    async def unregister_decode_jpg_async(self, did: str, channel: int = 0):
        """Unregister decoded JPG callback."""
        if did in self._frame_callbacks and channel in self._frame_callbacks[did]:
            self._frame_callbacks[did][channel].clear()

        await self._send_request("unsubscribe_frames", did=did, channel=channel)

    async def register_raw_video_async(
        self,
        did: str,
        callback: Callable[[str, bytes, int, int, int], Coroutine],
        channel: int = 0
    ):
        """Register raw video callback."""
        if did not in self._frame_callbacks:
            self._frame_callbacks[did] = {}
        if channel not in self._frame_callbacks[did]:
            self._frame_callbacks[did][channel] = []
        self._frame_callbacks[did][channel].append(callback)

        await self._send_request(
            "subscribe_frames",
            did=did,
            channel=channel,
            frame_type="raw_video"
        )

    async def unregister_raw_video_async(self, did: str, channel: int = 0):
        """Unregister raw video callback."""
        if did in self._frame_callbacks and channel in self._frame_callbacks[did]:
            self._frame_callbacks[did][channel].clear()

        await self._send_request("unsubscribe_frames", did=did, channel=channel)


async def check_proxy_available(proxy_url: str = DEFAULT_PROXY_URL) -> bool:
    """Check if the camera proxy add-on is available."""
    try:
        async with aiohttp.ClientSession() as session:
            # Try health endpoint first
            health_url = proxy_url.replace("/ws", "/health").replace("ws://", "http://")
            async with session.get(health_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return True
    except Exception:
        pass

    # Try WebSocket connection
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(proxy_url, timeout=5) as ws:
                await ws.close()
                return True
    except Exception:
        pass

    return False
