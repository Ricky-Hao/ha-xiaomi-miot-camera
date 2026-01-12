# -*- coding: utf-8 -*-
# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""RTSP streamer - pushes H.264/H.265 to mediamtx."""
import asyncio
import logging
import subprocess
from typing import Dict, Optional

_LOGGER = logging.getLogger(__name__)


def detect_codec_from_nalu(data: bytes) -> int:
    """Detect codec from NAL unit header.
    
    H.264 NAL unit: [start_code] [nal_unit_type(5 bits)]
    H.265 NAL unit: [start_code] [nal_unit_type(6 bits) in byte 0, high 6 bits]
    
    Returns:
        4 for H.264, 5 for H.265/HEVC, 0 if unknown
    """
    if len(data) < 5:
        return 0
    
    # Find start code position (0x00 0x00 0x01 or 0x00 0x00 0x00 0x01)
    start_pos = 0
    if data[0:3] == b'\x00\x00\x01':
        start_pos = 3
    elif data[0:4] == b'\x00\x00\x00\x01':
        start_pos = 4
    else:
        # No start code found, might be raw NAL
        start_pos = 0
    
    if start_pos >= len(data):
        return 0
    
    nal_byte = data[start_pos]
    
    # H.264: forbidden_zero_bit(1) + nal_ref_idc(2) + nal_unit_type(5)
    # NAL types 1-23 are valid for H.264
    h264_type = nal_byte & 0x1F
    
    # H.265: forbidden_zero_bit(1) + nal_unit_type(6) + nuh_layer_id(6, in next byte)
    # NAL types are in bits 1-6 (shift right 1, mask 0x3F)
    h265_type = (nal_byte >> 1) & 0x3F
    
    # Heuristic: check if it looks more like H.264 or H.265
    # H.264 common types: 1 (P), 5 (IDR), 6 (SEI), 7 (SPS), 8 (PPS)
    # H.265 common types: 1 (P), 19-20 (IDR), 32 (VPS), 33 (SPS), 34 (PPS), 39-40 (SEI)
    
    # Check for H.265 VPS (32), SPS (33), PPS (34) - unique to H.265
    if h265_type in (32, 33, 34):
        return 5  # H.265
    
    # Check for H.265 IDR types (19, 20)
    if h265_type in (19, 20) and h264_type not in (5, 7, 8):
        return 5  # H.265
    
    # Check for H.264 SPS (7) or PPS (8) - these values would be unusual in H.265
    if h264_type in (7, 8) and nal_byte & 0x60 != 0:  # nal_ref_idc != 0
        return 4  # H.264
    
    # If first byte has high bits set (nal_ref_idc), likely H.264
    if nal_byte & 0x60:  # bits 5-6 set
        return 4  # H.264
    
    # Default to H.265 for modern cameras
    return 5


class RTSPStreamer:
    """Push H.264/H.265 streams to mediamtx RTSP server.
    
    Each camera gets its own ffmpeg process that:
    1. Receives raw H.264/H.265 NAL units via stdin
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
        self._detected_codecs: Dict[str, int] = {}  # Detected codec per stream

    def _is_stream_running(self, stream_key: str) -> bool:
        """Check if FFmpeg process is still running."""
        if stream_key not in self._streamers:
            return False
        process = self._streamers[stream_key]
        return process.poll() is None

    async def start_stream(self, did: str, channel: int = 0, codec_id: int = 0) -> bool:
        """Prepare RTSP stream for a camera (actual FFmpeg start is deferred).
        
        Args:
            did: Device ID
            channel: Camera channel number
            codec_id: Video codec (4=H.264, 5=H.265/HEVC, 0=auto-detect)
            
        Returns:
            True if prepared successfully
        """
        stream_key = f"{did}_{channel}"
        
        # Store config - FFmpeg will start when first frame arrives
        self._stream_configs[stream_key] = {"codec_id": codec_id}
        self._stream_queues[stream_key] = asyncio.Queue(maxsize=100)
        self._frame_counts[stream_key] = 0
        
        _LOGGER.info("Prepared RTSP stream for %s (codec will be auto-detected)", stream_key)
        return True

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
            
            # FFmpeg command: stdin (H.264/H.265 Annex B) -> RTSP (no transcoding)
            # Key settings:
            # - probesize/analyzeduration: fast startup, don't wait for too many frames
            # - fflags +genpts: generate timestamps if missing
            # - rtpflags latm: low-latency RTP flags
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "info",  # Changed to info for debugging
                # Input settings
                "-probesize", "32",  # Minimum probe size for faster startup
                "-analyzeduration", "0",  # Don't analyze, just start
                "-fflags", "+genpts+discardcorrupt",  # Generate PTS, discard corrupt
                "-f", input_format,
                "-i", "pipe:0",
                # Output: copy codec, RTSP
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
        """Monitor FFmpeg stderr for errors and info."""
        try:
            loop = asyncio.get_event_loop()
            while process.poll() is None:
                # Read stderr in executor to not block
                line = await loop.run_in_executor(
                    None, process.stderr.readline
                )
                if line:
                    line_str = line.decode().strip()
                    # Log everything from FFmpeg for debugging
                    if "error" in line_str.lower():
                        _LOGGER.error("FFmpeg [%s]: %s", stream_key, line_str)
                    else:
                        _LOGGER.info("FFmpeg [%s]: %s", stream_key, line_str)
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
        
        # Cleanup
        if stream_key in self._stream_queues:
            del self._stream_queues[stream_key]
        if stream_key in self._frame_counts:
            del self._frame_counts[stream_key]
        if stream_key in self._stream_configs:
            del self._stream_configs[stream_key]
        if stream_key in self._detected_codecs:
            del self._detected_codecs[stream_key]
        
        _LOGGER.info("Stopped RTSP stream: %s", stream_key)

    async def push_frame(self, did: str, frame_data: bytes, channel: int = 0):
        """Push H.264/H.265 frame to stream.
        
        Args:
            did: Device ID
            frame_data: Raw H.264/H.265 NAL unit (Annex B format with start codes)
            channel: Camera channel
        """
        stream_key = f"{did}_{channel}"
        
        if stream_key not in self._stream_queues:
            _LOGGER.warning("No stream queue for %s, frame dropped", stream_key)
            return
        
        # Auto-detect codec on first frame
        if stream_key not in self._detected_codecs:
            detected = detect_codec_from_nalu(frame_data)
            if detected == 0:
                detected = 5  # Default to H.265 for modern cameras
            self._detected_codecs[stream_key] = detected
            codec_name = "H.265/HEVC" if detected == 5 else "H.264"
            
            # Debug: log first frame header bytes
            header_hex = frame_data[:20].hex() if len(frame_data) >= 20 else frame_data.hex()
            _LOGGER.info(
                "First frame for %s: codec=%s, size=%d, header=%s", 
                stream_key, codec_name, len(frame_data), header_hex
            )
        
        # Start FFmpeg if not running (deferred start)
        if not self._is_stream_running(stream_key):
            codec_id = self._detected_codecs.get(stream_key, 5)
            _LOGGER.info("Starting FFmpeg for %s with codec_id=%d", stream_key, codec_id)
            await self._start_ffmpeg(stream_key, codec_id)
            # Give FFmpeg a moment to start and connect to MediaMTX
            await asyncio.sleep(0.5)
        
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
