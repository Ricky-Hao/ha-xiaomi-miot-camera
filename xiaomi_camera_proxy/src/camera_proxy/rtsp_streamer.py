# -*- coding: utf-8 -*-
# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""RTSP streamer - pushes H.264/H.265 to MediaMTX RTSP server.

Key design principles (learned from miloco):
1. Non-blocking writes to FFmpeg stdin using thread pool
2. Small queue to prevent frame buildup
3. Minimal probesize to reduce latency
4. Separate thread for FFmpeg communication
"""
import asyncio
import logging
import subprocess
import threading
from collections import deque
from typing import Dict, Optional

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


class FFmpegWriter(threading.Thread):
    """Dedicated thread for writing to FFmpeg stdin.
    
    This prevents blocking the asyncio event loop when FFmpeg's
    pipe buffer is full.
    """
    
    def __init__(self, stream_key: str, process: subprocess.Popen, max_queue_size: int = 30):
        super().__init__(daemon=True)
        self._stream_key = stream_key
        self._process = process
        self._queue: deque = deque(maxlen=max_queue_size)
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._running = True
        self._frame_count = 0
        self._drop_count = 0
    
    def push_frame(self, data: bytes) -> bool:
        """Push frame to queue (non-blocking)."""
        with self._lock:
            if len(self._queue) >= self._queue.maxlen:
                # Queue full, drop oldest frame
                self._queue.popleft()
                self._drop_count += 1
            self._queue.append(data)
        self._event.set()
        return True
    
    def run(self):
        """Writer thread main loop."""
        while self._running and self._process.poll() is None:
            # Wait for frames
            self._event.wait(timeout=1.0)
            self._event.clear()
            
            # Write all queued frames
            while True:
                with self._lock:
                    if not self._queue:
                        break
                    frame = self._queue.popleft()
                
                try:
                    if self._process.stdin:
                        self._process.stdin.write(frame)
                        self._process.stdin.flush()
                        self._frame_count += 1
                except (BrokenPipeError, OSError) as e:
                    _LOGGER.error("FFmpeg write error [%s]: %s", self._stream_key, e)
                    self._running = False
                    break
        
        _LOGGER.info("FFmpegWriter stopped [%s]: wrote %d frames, dropped %d",
                    self._stream_key, self._frame_count, self._drop_count)
    
    def stop(self):
        """Stop the writer thread."""
        self._running = False
        self._event.set()


class RTSPStreamer:
    """Push H.264/H.265 streams to MediaMTX RTSP server."""

    def __init__(self, transcode_h264: bool = True):
        """Initialize RTSP streamer.
        
        Args:
            transcode_h264: If True, transcode H.265 to H.264 for better browser compatibility.
                           This enables WebRTC in all browsers but uses more CPU.
        """
        self._streamers: Dict[str, subprocess.Popen] = {}
        self._writers: Dict[str, FFmpegWriter] = {}
        self._detected_codecs: Dict[str, int] = {}
        self._frame_counts: Dict[str, int] = {}
        self._prepared_streams: set = set()
        self._transcode_h264 = transcode_h264
        
        if transcode_h264:
            _LOGGER.info("H.265→H.264 transcoding enabled for better WebRTC compatibility")

    def _is_stream_running(self, stream_key: str) -> bool:
        """Check if FFmpeg process is still running."""
        if stream_key not in self._streamers:
            return False
        return self._streamers[stream_key].poll() is None

    async def start_stream(self, did: str, channel: int = 0, codec_id: int = 0) -> bool:
        """Prepare RTSP stream for a camera."""
        stream_key = f"{did}_{channel}"
        self._prepared_streams.add(stream_key)
        self._frame_counts[stream_key] = 0
        _LOGGER.info("Prepared RTSP stream for %s", stream_key)
        return True

    def _start_ffmpeg_sync(self, stream_key: str, codec_id: int, first_frame: bytes) -> bool:
        """Start FFmpeg process (sync, called from push_frame)."""
        try:
            did, channel = stream_key.rsplit("_", 1)
            rtsp_url = f"rtsp://localhost:8554/camera/{did}/{channel}"
            input_format = "hevc" if codec_id == 5 else "h264"
            
            # Determine if we need to transcode
            need_transcode = self._transcode_h264 and codec_id == 5  # H.265
            
            # Key FFmpeg settings for low latency:
            # - probesize 32K: just enough for VPS/SPS/PPS in first IDR frame
            # - analyzeduration 0: don't wait to analyze
            # - fflags nobuffer: disable input buffering
            # - flags low_delay: minimize latency
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                # Input: minimal buffering
                "-probesize", "32768",  # 32KB
                "-analyzeduration", "0",
                "-fflags", "+genpts+nobuffer+discardcorrupt",
                "-flags", "low_delay",
                "-f", input_format,
                "-i", "pipe:0",
            ]
            
            if need_transcode:
                # Transcode H.265 to H.264 for browser WebRTC compatibility
                # Use fast preset and tune for low latency
                cmd.extend([
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-tune", "zerolatency",
                    "-profile:v", "baseline",  # Most compatible
                    "-level", "3.1",
                    "-b:v", "2M",  # 2 Mbps bitrate
                    "-maxrate", "2M",
                    "-bufsize", "1M",
                    "-g", "30",  # Keyframe every 30 frames
                    "-keyint_min", "30",
                ])
                output_codec = "H.264 (transcoded)"
            else:
                # Copy codec (H.264 or H.265 passthrough)
                cmd.extend(["-c:v", "copy"])
                output_codec = "H.265" if codec_id == 5 else "H.264"
            
            # Output settings
            cmd.extend([
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                rtsp_url
            ])
            
            _LOGGER.info("Starting FFmpeg [%s]: %s -> %s (%s)", 
                        stream_key, input_format, rtsp_url, output_codec)
            
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
            
            self._streamers[stream_key] = process
            
            # Write first frame immediately
            if process.stdin and first_frame:
                process.stdin.write(first_frame)
                process.stdin.flush()
            
            # Start dedicated writer thread
            writer = FFmpegWriter(stream_key, process)
            writer.start()
            self._writers[stream_key] = writer
            
            # Start error monitor in background
            asyncio.get_event_loop().create_task(
                self._error_monitor(stream_key, process)
            )
            
            return True
            
        except Exception as e:
            _LOGGER.error("Failed to start FFmpeg [%s]: %s", stream_key, e)
            return False

    async def _error_monitor(self, stream_key: str, process: subprocess.Popen):
        """Monitor FFmpeg stderr."""
        try:
            loop = asyncio.get_event_loop()
            while process.poll() is None:
                line = await loop.run_in_executor(None, process.stderr.readline)
                if line:
                    line_str = line.decode().strip()
                    if line_str and not line_str.startswith("frame="):
                        if "error" in line_str.lower():
                            _LOGGER.error("FFmpeg [%s]: %s", stream_key, line_str)
                        elif not line_str.startswith("["):  # Skip codec info
                            _LOGGER.debug("FFmpeg [%s]: %s", stream_key, line_str)
        except Exception:
            pass
        
        # FFmpeg exited
        exit_code = process.poll()
        if exit_code and exit_code != 0:
            _LOGGER.warning("FFmpeg [%s] exited with code %d", stream_key, exit_code)

    async def stop_stream(self, did: str, channel: int = 0):
        """Stop RTSP stream for a camera."""
        stream_key = f"{did}_{channel}"
        
        # Stop writer thread
        if stream_key in self._writers:
            self._writers[stream_key].stop()
            self._writers[stream_key].join(timeout=2)
            del self._writers[stream_key]
        
        # Kill FFmpeg
        if stream_key in self._streamers:
            process = self._streamers[stream_key]
            if process.stdin:
                try:
                    process.stdin.close()
                except Exception:
                    pass
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            del self._streamers[stream_key]
        
        self._prepared_streams.discard(stream_key)
        self._detected_codecs.pop(stream_key, None)
        self._frame_counts.pop(stream_key, None)
        
        _LOGGER.info("Stopped RTSP stream: %s", stream_key)

    async def push_frame(self, did: str, frame_data: bytes, channel: int = 0):
        """Push H.264/H.265 frame to stream."""
        stream_key = f"{did}_{channel}"
        
        if stream_key not in self._prepared_streams:
            return
        
        # First frame: detect codec and start FFmpeg
        if stream_key not in self._detected_codecs:
            detected = detect_codec_from_nalu(frame_data)
            if detected == 0:
                detected = 5
            self._detected_codecs[stream_key] = detected
            
            codec_name = "H.265" if detected == 5 else "H.264"
            _LOGGER.info("Detected %s for %s (frame size=%d)", codec_name, stream_key, len(frame_data))
            
            # Start FFmpeg synchronously with first frame
            self._start_ffmpeg_sync(stream_key, detected, frame_data)
            self._frame_counts[stream_key] = 1
            return
        
        # FFmpeg crashed? Restart with this frame
        if not self._is_stream_running(stream_key):
            codec_id = self._detected_codecs.get(stream_key, 5)
            _LOGGER.warning("FFmpeg [%s] not running, restarting", stream_key)
            # Clean up old writer
            if stream_key in self._writers:
                self._writers[stream_key].stop()
                del self._writers[stream_key]
            self._start_ffmpeg_sync(stream_key, codec_id, frame_data)
            return
        
        # Normal frame: push to writer thread
        writer = self._writers.get(stream_key)
        if writer:
            writer.push_frame(frame_data)
            self._frame_counts[stream_key] = self._frame_counts.get(stream_key, 0) + 1

    async def stop_all(self):
        """Stop all streams."""
        for stream_key in list(self._streamers.keys()):
            did, channel = stream_key.rsplit("_", 1)
            await self.stop_stream(did, int(channel))

    def get_rtsp_url(self, did: str, channel: int = 0) -> str:
        """Get RTSP URL for a camera stream."""
        return f"rtsp://127.0.0.1:8554/camera/{did}/{channel}"
