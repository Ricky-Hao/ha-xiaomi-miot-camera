# -*- coding: utf-8 -*-
"""RTSP streamer - pushes H.264 to mediamtx."""
import asyncio
import logging
import subprocess
from typing import Optional, Dict
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


class RTSPStreamer:
    """Push H.264 streams to mediamtx RTSP server.
    
    Each camera gets its own ffmpeg process that:
    1. Receives raw H.264 NAL units via stdin
    2. Remuxes to RTSP format (no transcoding!)
    3. Publishes to mediamtx at rtsp://localhost:8554/camera/{did}/{channel}
    
    mediamtx handles on-demand:
    - Stream starts when someone connects
    - Automatically stops when no viewers
    """

    def __init__(self):
        """Initialize RTSP streamer."""
        self._streamers: Dict[str, subprocess.Popen] = {}
        self._stream_queues: Dict[str, asyncio.Queue] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    async def start_stream(self, did: str, channel: int = 0) -> bool:
        """Start RTSP stream for a camera.
        
        Args:
            did: Device ID
            channel: Camera channel number
            
        Returns:
            True if started successfully
        """
        stream_key = f"{did}_{channel}"
        if stream_key in self._streamers:
            _LOGGER.debug("Stream already running: %s", stream_key)
            return True

        try:
            # RTSP URL: rtsp://localhost:8554/camera/{did}/{channel}
            rtsp_url = f"rtsp://localhost:8554/camera/{did}/{channel}"
            
            # FFmpeg command: stdin (H.264) -> RTSP (no transcoding)
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                # Input: raw H.264 from stdin
                "-f", "h264",
                "-i", "pipe:0",
                # Output: copy codec (no transcoding!), RTSP
                "-c:v", "copy",
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                rtsp_url
            ]
            
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
            
            # Start writer task
            self._tasks[stream_key] = asyncio.create_task(
                self._write_loop(stream_key, process)
            )
            
            _LOGGER.info("Started RTSP stream: %s -> %s", stream_key, rtsp_url)
            return True
            
        except Exception as e:
            _LOGGER.error("Failed to start RTSP stream %s: %s", stream_key, e)
            return False

    async def stop_stream(self, did: str, channel: int = 0):
        """Stop RTSP stream for a camera."""
        stream_key = f"{did}_{channel}"
        
        if stream_key not in self._streamers:
            return
        
        # Cancel writer task
        if stream_key in self._tasks:
            self._tasks[stream_key].cancel()
            try:
                await self._tasks[stream_key]
            except asyncio.CancelledError:
                pass
            del self._tasks[stream_key]
        
        # Stop ffmpeg
        process = self._streamers[stream_key]
        try:
            process.stdin.close()
            process.terminate()
            process.wait(timeout=5)
        except Exception as e:
            _LOGGER.warning("Error stopping stream %s: %s", stream_key, e)
            process.kill()
        
        del self._streamers[stream_key]
        if stream_key in self._stream_queues:
            del self._stream_queues[stream_key]
        
        _LOGGER.info("Stopped RTSP stream: %s", stream_key)

    async def push_frame(self, did: str, frame_data: bytes, channel: int = 0):
        """Push H.264 frame to stream.
        
        Args:
            did: Device ID
            frame_data: Raw H.264 NAL unit
            channel: Camera channel
        """
        stream_key = f"{did}_{channel}"
        
        if stream_key not in self._stream_queues:
            return
        
        try:
            # Non-blocking put (drop frame if queue full)
            self._stream_queues[stream_key].put_nowait(frame_data)
        except asyncio.QueueFull:
            _LOGGER.debug("Stream queue full, dropping frame: %s", stream_key)

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
