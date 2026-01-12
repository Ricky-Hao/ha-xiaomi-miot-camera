# -*- coding: utf-8 -*-
# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""RTSP streamer - pushes H.264/H.265 to MediaMTX RTSP server."""
import asyncio
import logging
import subprocess
from typing import Dict

_LOGGER = logging.getLogger(__name__)


def detect_codec_from_nalu(data: bytes) -> int:
    """Detect codec from NAL unit header.
    
    Returns: 4 for H.264, 5 for H.265/HEVC, 0 if unknown
    """
    if len(data) < 5:
        return 0
    
    # Find start code position
    start_pos = 0
    if data[0:3] == b'\x00\x00\x01':
        start_pos = 3
    elif data[0:4] == b'\x00\x00\x00\x01':
        start_pos = 4
    
    if start_pos >= len(data):
        return 0
    
    nal_byte = data[start_pos]
    h265_type = (nal_byte >> 1) & 0x3F
    
    # H.265 VPS (32), SPS (33), PPS (34) - unique to H.265
    if h265_type in (32, 33, 34, 19, 20):
        return 5  # H.265
    
    # Check for H.264 characteristics
    if nal_byte & 0x60:  # nal_ref_idc != 0
        return 4  # H.264
    
    return 5  # Default to H.265


class RTSPStreamer:
    """Push H.264/H.265 streams to MediaMTX RTSP server."""

    def __init__(self):
        """Initialize RTSP streamer."""
        self._streamers: Dict[str, subprocess.Popen] = {}
        self._stream_queues: Dict[str, asyncio.Queue] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._frame_counts: Dict[str, int] = {}
        self._detected_codecs: Dict[str, int] = {}
        self._pending_first_frame: Dict[str, bytes] = {}  # Store first frame

    def _is_stream_running(self, stream_key: str) -> bool:
        """Check if FFmpeg process is still running."""
        if stream_key not in self._streamers:
            return False
        return self._streamers[stream_key].poll() is None

    async def start_stream(self, did: str, channel: int = 0, codec_id: int = 0) -> bool:
        """Prepare RTSP stream for a camera."""
        stream_key = f"{did}_{channel}"
        self._stream_queues[stream_key] = asyncio.Queue(maxsize=100)
        self._frame_counts[stream_key] = 0
        _LOGGER.info("Prepared RTSP stream for %s", stream_key)
        return True

    async def _start_ffmpeg(self, stream_key: str, codec_id: int, first_frame: bytes) -> bool:
        """Start FFmpeg process and send first frame."""
        try:
            did, channel = stream_key.rsplit("_", 1)
            rtsp_url = f"rtsp://localhost:8554/camera/{did}/{channel}"
            input_format = "hevc" if codec_id == 5 else "h264"
            
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",  # Reduce log noise
                "-probesize", "5000000",
                "-analyzeduration", "5000000",
                "-fflags", "+genpts+discardcorrupt",
                "-f", input_format,
                "-i", "pipe:0",
                "-c:v", "copy",
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                rtsp_url
            ]
            
            _LOGGER.info("Starting FFmpeg for %s: %s -> %s", stream_key, input_format, rtsp_url)
            
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
            
            self._streamers[stream_key] = process
            
            # Write first frame immediately (contains VPS/SPS/PPS)
            if process.stdin and first_frame:
                process.stdin.write(first_frame)
                process.stdin.flush()
            
            # Start writer task
            self._tasks[stream_key] = asyncio.create_task(
                self._write_loop(stream_key, process)
            )
            
            # Start error monitor (minimal logging)
            asyncio.create_task(self._error_monitor(stream_key, process))
            
            return True
            
        except Exception as e:
            _LOGGER.error("Failed to start FFmpeg for %s: %s", stream_key, e)
            return False

    async def _error_monitor(self, stream_key: str, process: subprocess.Popen):
        """Monitor FFmpeg stderr for errors only."""
        try:
            loop = asyncio.get_event_loop()
            while process.poll() is None:
                line = await loop.run_in_executor(None, process.stderr.readline)
                if line:
                    line_str = line.decode().strip()
                    # Only log warnings and errors
                    if line_str and not line_str.startswith("frame="):
                        if "error" in line_str.lower():
                            _LOGGER.error("FFmpeg [%s]: %s", stream_key, line_str)
                        elif "warning" in line_str.lower() or "discarding" in line_str.lower():
                            _LOGGER.warning("FFmpeg [%s]: %s", stream_key, line_str)
        except Exception:
            pass

    async def stop_stream(self, did: str, channel: int = 0):
        """Stop RTSP stream for a camera."""
        stream_key = f"{did}_{channel}"
        
        if stream_key in self._tasks:
            self._tasks[stream_key].cancel()
            try:
                await self._tasks[stream_key]
            except asyncio.CancelledError:
                pass
            del self._tasks[stream_key]
        
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
        
        self._stream_queues.pop(stream_key, None)
        self._frame_counts.pop(stream_key, None)
        self._detected_codecs.pop(stream_key, None)
        self._pending_first_frame.pop(stream_key, None)
        
        _LOGGER.info("Stopped RTSP stream: %s", stream_key)

    async def push_frame(self, did: str, frame_data: bytes, channel: int = 0):
        """Push H.264/H.265 frame to stream."""
        stream_key = f"{did}_{channel}"
        
        if stream_key not in self._stream_queues:
            return
        
        # Auto-detect codec and start FFmpeg on first frame
        if stream_key not in self._detected_codecs:
            detected = detect_codec_from_nalu(frame_data)
            if detected == 0:
                detected = 5
            self._detected_codecs[stream_key] = detected
            
            codec_name = "H.265" if detected == 5 else "H.264"
            _LOGGER.info("Detected %s for %s, size=%d", codec_name, stream_key, len(frame_data))
            
            # Start FFmpeg with the first frame (contains parameter sets)
            await self._start_ffmpeg(stream_key, detected, frame_data)
            self._frame_counts[stream_key] = 1
            return  # First frame already sent to FFmpeg
        
        # Restart FFmpeg if crashed
        if not self._is_stream_running(stream_key):
            codec_id = self._detected_codecs.get(stream_key, 5)
            _LOGGER.warning("FFmpeg crashed for %s, restarting", stream_key)
            await self._start_ffmpeg(stream_key, codec_id, frame_data)
            return
        
        # Count and log periodically
        self._frame_counts[stream_key] = self._frame_counts.get(stream_key, 0) + 1
        count = self._frame_counts[stream_key]
        if count % 500 == 0:  # Log every 500 frames
            _LOGGER.debug("Stream %s: %d frames", stream_key, count)
        
        # Queue frame for FFmpeg
        try:
            self._stream_queues[stream_key].put_nowait(frame_data)
        except asyncio.QueueFull:
            pass  # Drop frame silently if queue full

    async def _write_loop(self, stream_key: str, process: subprocess.Popen):
        """Write frames from queue to FFmpeg stdin."""
        queue = self._stream_queues.get(stream_key)
        if not queue:
            return
        
        try:
            while True:
                frame_data = await queue.get()
                if process.stdin:
                    process.stdin.write(frame_data)
                    process.stdin.flush()
        except asyncio.CancelledError:
            pass
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
