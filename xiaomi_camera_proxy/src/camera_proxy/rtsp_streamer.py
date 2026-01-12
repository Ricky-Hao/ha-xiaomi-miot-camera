# -*- coding: utf-8 -*-
# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""RTSP streamer - pushes H.264 to mediamtx."""
import asyncio
import logging
import subprocess
from typing import Dict, Optional

_LOGGER = logging.getLogger(__name__)


class RTSPStreamer:
    """Push H.264 streams to mediamtx RTSP server.
    
    Each camera gets its own ffmpeg process that:
    1. Receives raw H.264 NAL units via stdin
    2. Remuxes to RTSP format (no transcoding!)
    3. Publishes to mediamtx at rtsp://localhost:8554/camera/{did}/{channel}
    """

    def __init__(self):
        """Initialize RTSP streamer."""
        self._streamers: Dict[str, subprocess.Popen] = {}
        self._stream_queues: Dict[str, asyncio.Queue] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._error_tasks: Dict[str, asyncio.Task] = {}
        self._frame_counts: Dict[str, int] = {}
        self._stream_configs: Dict[str, dict] = {}  # Store config for restart

    def _is_stream_running(self, stream_key: str) -> bool:
        """Check if FFmpeg process is still running."""
        if stream_key not in self._streamers:
            return False
        process = self._streamers[stream_key]
        return process.poll() is None

    async def start_stream(self, did: str, channel: int = 0, codec_id: int = 4) -> bool:
        """Start RTSP stream for a camera.
        
        Args:
            did: Device ID
            channel: Camera channel number
            codec_id: Video codec (4=H.264, 5=H.265/HEVC)
            
        Returns:
            True if started successfully
        """
        stream_key = f"{did}_{channel}"
        
        # Store config for later restart
        self._stream_configs[stream_key] = {"codec_id": codec_id}
        
        if self._is_stream_running(stream_key):
            _LOGGER.debug("Stream already running: %s", stream_key)
            return True

        return await self._start_ffmpeg(stream_key, codec_id)

    async def _start_ffmpeg(self, stream_key: str, codec_id: int) -> bool:
        """Start FFmpeg process for streaming."""
        try:
            did, channel = stream_key.rsplit("_", 1)
            
            # RTSP URL: rtsp://localhost:8554/camera/{did}/{channel}
            rtsp_url = f"rtsp://localhost:8554/camera/{did}/{channel}"
            
            # Determine input format based on codec
            # MIoT codec IDs: VIDEO_H264=4, VIDEO_H265/HEVC=5
            if codec_id == 5:
                input_format = "hevc"
            else:
                input_format = "h264"
            
            _LOGGER.info("Using codec: %s (codec_id=%d)", input_format, codec_id)
            
            # FFmpeg command: stdin (H.264/H.265) -> RTSP (no transcoding)
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                # Input: raw video from stdin
                "-f", input_format,
                "-i", "pipe:0",
                # Output: copy codec (no transcoding!), RTSP
                "-c:v", "copy",
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                rtsp_url
            ]
            
            _LOGGER.info("Starting FFmpeg: %s", " ".join(cmd))
            
            # Start ffmpeg process
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0  # Unbuffered
            )
            
            self._streamers[stream_key] = process
            self._stream_queues[stream_key] = asyncio.Queue(maxsize=100)
            self._frame_counts[stream_key] = 0
            
            # Start writer task
            self._tasks[stream_key] = asyncio.create_task(
                self._write_loop(stream_key, process)
            )
            
            # Start error monitor task
            self._error_tasks[stream_key] = asyncio.create_task(
                self._error_monitor(stream_key, process)
            )
            
            _LOGGER.info("Started RTSP stream: %s -> %s", stream_key, rtsp_url)
            return True
            
        except Exception as e:
            _LOGGER.error("Failed to start RTSP stream %s: %s", stream_key, e)
            return False

    async def _error_monitor(self, stream_key: str, process: subprocess.Popen):
        """Monitor FFmpeg stderr for errors."""
        try:
            loop = asyncio.get_event_loop()
            while process.poll() is None:
                # Read stderr in executor to not block
                line = await loop.run_in_executor(
                    None, process.stderr.readline
                )
                if line:
                    _LOGGER.warning("FFmpeg [%s]: %s", stream_key, line.decode().strip())
        except Exception as e:
            _LOGGER.debug("Error monitor ended for %s: %s", stream_key, e)

    async def stop_stream(self, did: str, channel: int = 0):
        """Stop RTSP stream for a camera."""
        stream_key = f"{did}_{channel}"
        
        # Cancel tasks
        if stream_key in self._tasks:
            self._tasks[stream_key].cancel()
            try:
                await self._tasks[stream_key]
            except asyncio.CancelledError:
                pass
            del self._tasks[stream_key]
        
        if stream_key in self._error_tasks:
            self._error_tasks[stream_key].cancel()
            try:
                await self._error_tasks[stream_key]
            except asyncio.CancelledError:
                pass
            del self._error_tasks[stream_key]
        
        # Kill ffmpeg process
        if stream_key in self._streamers:
            process = self._streamers[stream_key]
            if process.stdin:
                process.stdin.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            del self._streamers[stream_key]
        
        # Cleanup queue
        if stream_key in self._stream_queues:
            del self._stream_queues[stream_key]
        
        if stream_key in self._frame_counts:
            del self._frame_counts[stream_key]
        
        _LOGGER.info("Stopped RTSP stream: %s", stream_key)

    async def push_frame(self, did: str, frame_data: bytes, channel: int = 0):
        """Push H.264 frame to stream.
        
        Args:
            did: Device ID
            frame_data: Raw H.264 NAL unit
            channel: Camera channel
        """
        stream_key = f"{did}_{channel}"
        
        # Check if FFmpeg process is still running, restart if needed
        if not self._is_stream_running(stream_key):
            _LOGGER.warning("FFmpeg process not running for %s, restarting...", stream_key)
            config = self._stream_configs.get(stream_key, {"codec_id": 4})
            await self._start_ffmpeg(stream_key, config["codec_id"])
        
        if stream_key not in self._stream_queues:
            _LOGGER.warning("No stream queue for %s, frame dropped", stream_key)
            return
        
        # Count frames
        self._frame_counts[stream_key] = self._frame_counts.get(stream_key, 0) + 1
        count = self._frame_counts[stream_key]
        
        # Log every 100 frames
        if count == 1 or count % 100 == 0:
            _LOGGER.info("RTSP push_frame [%s]: frame #%d, size=%d bytes", 
                        stream_key, count, len(frame_data))
        
        try:
            # Non-blocking put (drop frame if queue full)
            self._stream_queues[stream_key].put_nowait(frame_data)
        except asyncio.QueueFull:
            _LOGGER.warning("Stream queue full, dropping frame: %s", stream_key)

    async def _write_loop(self, stream_key: str, process: subprocess.Popen):
        """Write frames from queue to ffmpeg stdin."""
        queue = self._stream_queues[stream_key]
        
        try:
            while True:
                # Get frame from queue
                frame_data = await queue.get()
                
                # Write to ffmpeg stdin
                if process.stdin:
                    process.stdin.write(frame_data)
                    process.stdin.flush()
                    
        except asyncio.CancelledError:
            _LOGGER.debug("Write loop cancelled: %s", stream_key)
        except Exception as e:
            _LOGGER.error("Write loop error %s: %s", stream_key, e)

    async def stop_all(self):
        """Stop all streams."""
        for stream_key in list(self._streamers.keys()):
            did, channel = stream_key.rsplit("_", 1)
            await self.stop_stream(did, int(channel))

    def get_rtsp_url(self, did: str, channel: int = 0) -> str:
        """Get RTSP URL for a camera stream."""
        return f"rtsp://127.0.0.1:8554/camera/{did}/{channel}"
