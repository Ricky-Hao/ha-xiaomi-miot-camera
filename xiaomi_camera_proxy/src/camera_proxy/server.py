# -*- coding: utf-8 -*-
# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""
HTTP Server for Camera Proxy Add-on.

This server uses CameraService for all camera operations.
It provides:
- HTTP endpoints for OAuth, device discovery, camera control, snapshots
- WebRTC streaming via MediaMTX (port 8889)
"""
import asyncio
import logging
from typing import Optional

from aiohttp import web

from .camera_service import CameraService
from .rtsp_streamer import RTSPStreamer

_LOGGER = logging.getLogger(__name__)

__version__ = "0.6.23"


class CameraProxyServer:
    """Camera Proxy HTTP Server."""

    def __init__(
        self, 
        host: str = "0.0.0.0", 
        port: int = 8765, 
        transcode_h264: bool = True,
        video_quality: int = 3,
    ):
        """Initialize server.
        
        Args:
            host: Host to bind
            port: Port to bind  
            transcode_h264: If True, transcode H.265 to H.264 for browser compatibility
            video_quality: Video quality (1=LOW, 3=HIGH, 4/5=experimental)
        """
        self._host = host
        self._port = port
        self._video_quality = video_quality
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        
        # Core services
        self._rtsp_streamer = RTSPStreamer(transcode_h264=transcode_h264)
        self._camera_service = CameraService(video_quality=video_quality)

    async def start_async(self):
        """Start the server."""
        # Initialize camera service
        await self._camera_service.init_async(self._rtsp_streamer)
        
        # Setup web app
        self._app = web.Application()
        self._setup_routes()
        
        # Start server
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        
        _LOGGER.info("Server started on %s:%d (version %s)", self._host, self._port, __version__)

    async def stop_async(self):
        """Stop the server."""
        await self._camera_service.deinit_async()
        
        if self._runner:
            await self._runner.cleanup()
        
        _LOGGER.info("Server stopped")

    def _setup_routes(self):
        """Setup HTTP routes."""
        app = self._app
        
        # Health & Info
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/info", self._handle_info)
        
        # OAuth endpoints
        app.router.add_get("/oauth/servers", self._handle_get_servers)
        app.router.add_post("/oauth/auth_url", self._handle_get_auth_url)
        app.router.add_post("/oauth/callback", self._handle_oauth_callback)
        app.router.add_post("/oauth/set_tokens", self._handle_set_tokens)
        app.router.add_post("/oauth/refresh", self._handle_refresh_tokens)
        
        # Device discovery
        app.router.add_get("/devices", self._handle_get_devices)
        app.router.add_get("/cameras", self._handle_get_cameras)
        
        # Configuration
        app.router.add_post("/config/cameras", self._handle_set_configured_cameras)
        
        # Camera control
        app.router.add_post("/camera/{did}/start", self._handle_start_camera)
        app.router.add_post("/camera/{did}/stop", self._handle_stop_camera)
        app.router.add_get("/camera/{did}/status", self._handle_get_status)
        
        # Snapshots
        app.router.add_get("/snapshot/{did}", self._handle_get_snapshot)
        app.router.add_get("/snapshot/{did}/{channel}", self._handle_get_snapshot)

    # ==================== Health & Info ====================

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "ok",
            "version": __version__,
            "authenticated": self._camera_service.authenticated,
            "initialized": self._camera_service.initialized,
        })

    async def _handle_info(self, request: web.Request) -> web.Response:
        """Get server info."""
        return web.json_response({
            "version": __version__,
            "cloud_server": self._camera_service.cloud_server,
            "authenticated": self._camera_service.authenticated,
            "camera_count": len(self._camera_service.cameras),
        })

    # ==================== OAuth Endpoints ====================

    async def _handle_get_servers(self, request: web.Request) -> web.Response:
        """Get supported cloud servers."""
        servers = self._camera_service.get_supported_servers()
        return web.json_response({"servers": servers})

    async def _handle_get_auth_url(self, request: web.Request) -> web.Response:
        """Get OAuth authorization URL."""
        try:
            data = await request.json()
            cloud_server = data.get("cloud_server", "cn")
            redirect_uri = data.get("redirect_uri")
            
            if not redirect_uri:
                return web.json_response({"error": "redirect_uri required"}, status=400)
            
            auth_url = await self._camera_service.get_auth_url_async(
                cloud_server=cloud_server,
                redirect_uri=redirect_uri,
            )
            
            return web.json_response({"auth_url": auth_url})
        except Exception as e:
            _LOGGER.exception("Error getting auth URL")
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_oauth_callback(self, request: web.Request) -> web.Response:
        """Handle OAuth callback."""
        try:
            data = await request.json()
            code = data.get("code")
            state = data.get("state")
            
            if not code or not state:
                return web.json_response({"error": "code and state required"}, status=400)
            
            success = await self._camera_service.handle_oauth_callback_async(code, state)
            
            if success:
                return web.json_response({"status": "ok"})
            else:
                return web.json_response({"error": "OAuth failed"}, status=401)
        except Exception as e:
            _LOGGER.exception("Error handling OAuth callback")
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_set_tokens(self, request: web.Request) -> web.Response:
        """Set tokens directly (from HA integration)."""
        try:
            data = await request.json()
            
            await self._camera_service.set_tokens_async(
                cloud_server=data.get("cloud_server", "cn"),
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_ts=data.get("expires_ts", 0),
            )
            
            return web.json_response({"status": "ok"})
        except KeyError as e:
            return web.json_response({"error": f"Missing field: {e}"}, status=400)
        except Exception as e:
            _LOGGER.exception("Error setting tokens")
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_refresh_tokens(self, request: web.Request) -> web.Response:
        """Refresh access token."""
        try:
            success = await self._camera_service.refresh_tokens_async()
            if success:
                return web.json_response({"status": "ok"})
            else:
                return web.json_response({"error": "Refresh failed"}, status=401)
        except Exception as e:
            _LOGGER.exception("Error refreshing tokens")
            return web.json_response({"error": str(e)}, status=500)

    # ==================== Device Discovery ====================

    async def _handle_get_devices(self, request: web.Request) -> web.Response:
        """Get all devices."""
        try:
            devices = await self._camera_service.discover_devices_async()
            return web.json_response({
                "devices": {did: dev.model_dump() for did, dev in devices.items()}
            })
        except Exception as e:
            _LOGGER.exception("Error getting devices")
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_get_cameras(self, request: web.Request) -> web.Response:
        """Get discovered cameras."""
        try:
            cameras = await self._camera_service.get_cameras_async()
            return web.json_response({
                "cameras": {did: cam.model_dump() for did, cam in cameras.items()}
            })
        except Exception as e:
            _LOGGER.exception("Error getting cameras")
            return web.json_response({"error": str(e)}, status=500)

    # ==================== Configuration ====================

    async def _handle_set_configured_cameras(self, request: web.Request) -> web.Response:
        """Set configured cameras (from HA Integration).
        
        These cameras will be auto-started on Add-on boot.
        """
        try:
            data = await request.json()
            camera_dids = data.get("camera_dids", [])
            
            await self._camera_service.set_configured_cameras_async(camera_dids)
            
            return web.json_response({"status": "ok", "configured_count": len(camera_dids)})
        except Exception as e:
            _LOGGER.exception("Error setting configured cameras")
            return web.json_response({"error": str(e)}, status=500)

    # ==================== Camera Control ====================

    async def _handle_start_camera(self, request: web.Request) -> web.Response:
        """Start camera streaming.
        
        Always waits for stream to be ready before returning.
        If camera is already streaming and ready, returns immediately.
        
        Note: Video quality is configured in Add-on settings, not per-request.
        """
        did = request.match_info["did"]
        try:
            data = await request.json() if request.body_exists else {}
            
            await self._camera_service.start_camera_async(
                did=did,
                pin_code=data.get("pin_code"),
                enable_audio=data.get("enable_audio", False),
            )
            
            return web.json_response({
                "status": "ok",
            })
        except Exception as e:
            _LOGGER.exception("Error starting camera %s", did)
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_stop_camera(self, request: web.Request) -> web.Response:
        """Stop camera streaming."""
        did = request.match_info["did"]
        try:
            await self._camera_service.stop_camera_async(did)
            return web.json_response({"status": "ok"})
        except Exception as e:
            _LOGGER.exception("Error stopping camera %s", did)
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_get_status(self, request: web.Request) -> web.Response:
        """Get camera status."""
        did = request.match_info["did"]
        try:
            status = await self._camera_service.get_camera_status_async(did)
            return web.json_response({"status": status.value})
        except Exception as e:
            _LOGGER.exception("Error getting camera status %s", did)
            return web.json_response({"error": str(e)}, status=500)

    # ==================== Snapshots ==============================

    async def _handle_get_snapshot(self, request: web.Request) -> web.Response:
        """Get camera snapshot as JPEG."""
        did = request.match_info["did"]
        channel = int(request.match_info.get("channel", 0))
        
        try:
            snapshot = await self._camera_service.get_snapshot_async(did, channel)
            
            if snapshot:
                return web.Response(
                    body=snapshot,
                    content_type="image/jpeg",
                )
            else:
                return web.Response(status=404, text="No snapshot available")
        except Exception as e:
            _LOGGER.exception("Error getting snapshot for %s", did)
            return web.json_response({"error": str(e)}, status=500)


async def run_server():
    """Run the server."""
    server = CameraProxyServer()
    await server.start_async()
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        await server.stop_async()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_server())
