# -*- coding: utf-8 -*-
"""WebSocket server for camera proxy."""
import asyncio
import base64
import json
import logging
from typing import Any, Callable, Coroutine, Dict, Optional, Set

from aiohttp import web, WSMsgType

from .camera_manager import CameraManager

_LOGGER = logging.getLogger(__name__)


class CameraProxyServer:
    """Camera Proxy WebSocket Server."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        """Initialize server."""
        self._host = host
        self._port = port
        self._app: Optional[web.Application] = None
        self._camera_manager: Optional[CameraManager] = None
        # WebSocket connections: {ws: {did: set of channels}}
        self._ws_connections: Dict[web.WebSocketResponse, Dict[str, Set[int]]] = {}
        # Frame subscriptions: {did: {channel: set of ws}}
        self._frame_subscriptions: Dict[str, Dict[int, Set[web.WebSocketResponse]]] = {}

    async def run(self):
        """Run the server."""
        self._app = web.Application()
        self._app.router.add_get("/ws", self._handle_websocket)
        self._app.router.add_get("/health", self._handle_health)

        self._camera_manager = CameraManager()

        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, self._host, self._port)
        _LOGGER.info("Starting server on %s:%d", self._host, self._port)
        await site.start()

        # Keep running
        while True:
            await asyncio.sleep(3600)

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({"status": "ok"})

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connection."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        _LOGGER.info("New WebSocket connection from %s", request.remote)

        self._ws_connections[ws] = {}

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_message(ws, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    _LOGGER.error("WebSocket error: %s", ws.exception())
        finally:
            await self._cleanup_connection(ws)

        return ws

    async def _handle_message(self, ws: web.WebSocketResponse, data: str):
        """Handle incoming WebSocket message."""
        try:
            message = json.loads(data)
            msg_type = message.get("type")
            msg_id = message.get("id")

            _LOGGER.debug("Received message: %s", msg_type)

            handler = getattr(self, f"_handle_{msg_type}", None)
            if handler:
                result = await handler(ws, message)
                await self._send_response(ws, msg_id, result)
            else:
                await self._send_error(ws, msg_id, f"Unknown message type: {msg_type}")

        except json.JSONDecodeError as e:
            _LOGGER.error("Invalid JSON: %s", e)
            await self._send_error(ws, None, "Invalid JSON")
        except Exception as e:
            _LOGGER.exception("Error handling message: %s", e)
            await self._send_error(ws, message.get("id"), str(e))

    async def _handle_init(self, ws: web.WebSocketResponse, message: dict) -> dict:
        """Handle init message - initialize camera library."""
        cloud_server = message.get("cloud_server", "cn")
        access_token = message.get("access_token")
        
        if not access_token:
            raise ValueError("access_token is required")

        _LOGGER.info("Initializing camera library for cloud server: %s", cloud_server)
        _LOGGER.debug("Access token length: %d", len(access_token) if access_token else 0)

        await self._camera_manager.init_async(
            cloud_server=cloud_server,
            access_token=access_token
        )
        
        version = await self._camera_manager.get_version_async()
        return {"status": "ok", "version": version}

    async def _handle_update_token(self, ws: web.WebSocketResponse, message: dict) -> dict:
        """Handle update token message."""
        access_token = message.get("access_token")
        if not access_token:
            raise ValueError("access_token is required")

        await self._camera_manager.update_access_token_async(access_token)
        return {"status": "ok"}

    async def _handle_create_camera(self, ws: web.WebSocketResponse, message: dict) -> dict:
        """Handle create camera message."""
        camera_info = message.get("camera_info")
        if not camera_info:
            raise ValueError("camera_info is required")

        await self._camera_manager.create_camera_async(camera_info)
        return {"status": "ok", "did": camera_info.get("did")}

    async def _handle_destroy_camera(self, ws: web.WebSocketResponse, message: dict) -> dict:
        """Handle destroy camera message."""
        did = message.get("did")
        if not did:
            raise ValueError("did is required")

        await self._camera_manager.destroy_camera_async(did)
        return {"status": "ok"}

    async def _handle_start_camera(self, ws: web.WebSocketResponse, message: dict) -> dict:
        """Handle start camera message."""
        did = message.get("did")
        if not did:
            raise ValueError("did is required")

        await self._camera_manager.start_camera_async(
            did=did,
            pin_code=message.get("pin_code"),
            qualities=message.get("qualities", [1]),  # LOW quality default
            enable_audio=message.get("enable_audio", False),
            enable_reconnect=message.get("enable_reconnect", False)
        )
        return {"status": "ok"}

    async def _handle_stop_camera(self, ws: web.WebSocketResponse, message: dict) -> dict:
        """Handle stop camera message."""
        did = message.get("did")
        if not did:
            raise ValueError("did is required")

        await self._camera_manager.stop_camera_async(did)
        return {"status": "ok"}

    async def _handle_get_status(self, ws: web.WebSocketResponse, message: dict) -> dict:
        """Handle get status message."""
        did = message.get("did")
        if not did:
            raise ValueError("did is required")

        status = await self._camera_manager.get_status_async(did)
        return {"status": "ok", "camera_status": status}

    async def _handle_subscribe_frames(self, ws: web.WebSocketResponse, message: dict) -> dict:
        """Handle subscribe to frames message."""
        did = message.get("did")
        channel = message.get("channel", 0)
        frame_type = message.get("frame_type", "jpg")  # jpg, raw_video, raw_audio, pcm

        if not did:
            raise ValueError("did is required")

        # Track subscription
        if did not in self._ws_connections[ws]:
            self._ws_connections[ws][did] = set()
        self._ws_connections[ws][did].add(channel)

        if did not in self._frame_subscriptions:
            self._frame_subscriptions[did] = {}
        if channel not in self._frame_subscriptions[did]:
            self._frame_subscriptions[did][channel] = set()
        self._frame_subscriptions[did][channel].add(ws)

        # Register callback based on frame type
        if frame_type == "jpg":
            await self._camera_manager.register_decode_jpg_async(
                did=did,
                channel=channel,
                callback=lambda d, data, ts, ch: self._on_frame(d, data, ts, ch, "jpg")
            )
        elif frame_type == "raw_video":
            await self._camera_manager.register_raw_video_async(
                did=did,
                channel=channel,
                callback=lambda d, data, ts, seq, ch: self._on_raw_frame(d, data, ts, seq, ch, "raw_video")
            )
        elif frame_type == "raw_audio":
            await self._camera_manager.register_raw_audio_async(
                did=did,
                channel=channel,
                callback=lambda d, data, ts, seq, ch: self._on_raw_frame(d, data, ts, seq, ch, "raw_audio")
            )
        elif frame_type == "pcm":
            await self._camera_manager.register_decode_pcm_async(
                did=did,
                channel=channel,
                callback=lambda d, data, ts, ch: self._on_frame(d, data, ts, ch, "pcm")
            )

        return {"status": "ok"}

    async def _handle_unsubscribe_frames(self, ws: web.WebSocketResponse, message: dict) -> dict:
        """Handle unsubscribe from frames message."""
        did = message.get("did")
        channel = message.get("channel", 0)

        if not did:
            raise ValueError("did is required")

        # Remove subscription tracking
        if ws in self._ws_connections and did in self._ws_connections[ws]:
            self._ws_connections[ws][did].discard(channel)

        if did in self._frame_subscriptions and channel in self._frame_subscriptions[did]:
            self._frame_subscriptions[did][channel].discard(ws)

        return {"status": "ok"}

    async def _on_frame(self, did: str, data: bytes, timestamp: int, channel: int, frame_type: str):
        """Handle decoded frame callback."""
        _LOGGER.debug(
            "_on_frame called: did=%s, channel=%d, type=%s, data_len=%d",
            did, channel, frame_type, len(data)
        )
        
        if did not in self._frame_subscriptions:
            _LOGGER.debug("No subscriptions for did=%s", did)
            return
        if channel not in self._frame_subscriptions[did]:
            _LOGGER.debug("No subscriptions for did=%s channel=%d", did, channel)
            return

        # Validate JPEG data
        if frame_type == "jpg" and len(data) > 2:
            if data[:2] != b'\xff\xd8':
                _LOGGER.warning(
                    "Invalid JPEG header: %s (expected FFD8), len=%d",
                    data[:2].hex(), len(data)
                )
            else:
                _LOGGER.debug("Valid JPEG frame: %d bytes", len(data))

        # Send to all subscribed WebSocket connections
        subscribers = self._frame_subscriptions[did][channel]
        _LOGGER.debug("Sending frame to %d subscribers", len(subscribers))
        
        frame_msg = {
            "type": "frame",
            "did": did,
            "channel": channel,
            "frame_type": frame_type,
            "timestamp": timestamp,
            "data": base64.b64encode(data).decode("ascii")
        }
        frame_json = json.dumps(frame_msg)

        for ws in list(self._frame_subscriptions[did][channel]):
            if not ws.closed:
                try:
                    await ws.send_str(frame_json)
                except Exception as e:
                    _LOGGER.warning("Failed to send frame to ws: %s", e)

    async def _on_raw_frame(self, did: str, data: bytes, timestamp: int, seq: int, channel: int, frame_type: str):
        """Handle raw frame callback."""
        if did not in self._frame_subscriptions:
            return
        if channel not in self._frame_subscriptions[did]:
            return

        frame_msg = {
            "type": "frame",
            "did": did,
            "channel": channel,
            "frame_type": frame_type,
            "timestamp": timestamp,
            "sequence": seq,
            "data": base64.b64encode(data).decode("ascii")
        }
        frame_json = json.dumps(frame_msg)

        for ws in list(self._frame_subscriptions[did][channel]):
            if not ws.closed:
                try:
                    await ws.send_str(frame_json)
                except Exception as e:
                    _LOGGER.warning("Failed to send frame to ws: %s", e)

    async def _cleanup_connection(self, ws: web.WebSocketResponse):
        """Clean up when WebSocket disconnects."""
        _LOGGER.info("WebSocket connection closed")

        # Remove from subscriptions
        if ws in self._ws_connections:
            for did, channels in self._ws_connections[ws].items():
                if did in self._frame_subscriptions:
                    for channel in channels:
                        if channel in self._frame_subscriptions[did]:
                            self._frame_subscriptions[did][channel].discard(ws)
            del self._ws_connections[ws]

    async def _send_response(self, ws: web.WebSocketResponse, msg_id: Optional[str], result: dict):
        """Send success response."""
        response = {"id": msg_id, "success": True, **result}
        await ws.send_json(response)

    async def _send_error(self, ws: web.WebSocketResponse, msg_id: Optional[str], error: str):
        """Send error response."""
        response = {"id": msg_id, "success": False, "error": error}
        await ws.send_json(response)
