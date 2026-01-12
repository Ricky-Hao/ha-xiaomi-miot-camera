# -*- coding: utf-8 -*-
# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""RTSP streamer - pushes H.264/H.265 to MediaMTX RTSP server.

Key design principles (learned from miloco):
1. Non-blocking writes to FFmpeg stdin using thread pool
2. Small queue to prevent frame buildup
3. Minimal probesize to reduce latency
4. Separate thread for FFmpeg communication
5. Cache I-frames (keyframes) to allow FFmpeg restart from valid point
"""
import asyncio
import logging
import subprocess
import threading
from collections import deque
from typing import Dict, Optional, List, Tuple

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


def is_keyframe(data: bytes, codec_id: int) -> bool:
    """Check if frame is a keyframe (I-frame/IDR).
    
    Args:
        data: NAL unit data with start code
        codec_id: 4 for H.264, 5 for H.265
    
    Returns: True if this is a keyframe
    """
    if len(data) < 5:
        return False
    
    # Find start code position
    start_pos = 0
    if data[0:3] == b'\x00\x00\x01':
        start_pos = 3
    elif data[0:4] == b'\x00\x00\x00\x01':
        start_pos = 4
    else:
        return False
    
    if start_pos >= len(data):
        return False
    
    nal_byte = data[start_pos]
    
    if codec_id == 5:  # H.265/HEVC
        nal_type = (nal_byte >> 1) & 0x3F
        # VPS(32), SPS(33), PPS(34), IDR_W_RADL(19), IDR_N_LP(20), CRA(21)
        return nal_type in (32, 33, 34, 19, 20, 21)
    else:  # H.264
        nal_type = nal_byte & 0x1F
        # SPS(7), PPS(8), IDR(5)
        return nal_type in (5, 7, 8)


class FrameBuffer:
    """Buffer that caches frames from the last keyframe.
    
    This allows FFmpeg to be restarted with a valid keyframe
    instead of starting from a P-frame which causes decode errors.
    """
    
    def __init__(self, max_frames: int = 60):
        """Initialize frame buffer.
        
        Args:
            max_frames: Maximum frames to keep after keyframe (about 2 seconds at 30fps)
        """
        self._max_frames = max_frames
        self._frames: List[bytes] = []
        self._has_keyframe = False
        self._lock = threading.Lock()
    
    def add_frame(self, data: bytes, is_key: bool) -> None:
        """Add a frame to buffer."""
        with self._lock:
            if is_key:
                # New keyframe: clear buffer and start fresh
                self._frames = [data]
                self._has_keyframe = True
            elif self._has_keyframe:
                # Add frame after keyframe
                self._frames.append(data)
                # Limit buffer size
                if len(self._frames) > self._max_frames:
                    # Keep keyframe and trim old P-frames
                    self._frames = self._frames[-self._max_frames:]
    
    def get_frames(self) -> List[bytes]:
        """Get all cached frames starting from keyframe."""
        with self._lock:
            return list(self._frames)
    
    def has_keyframe(self) -> bool:
        """Check if buffer has a keyframe."""
        with self._lock:
            return self._has_keyframe
    
    def clear(self) -> None:
        """Clear the buffer."""
        with self._lock:
            self._frames = []
            self._has_keyframe = False


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
        self._frame_buffers: Dict[str, FrameBuffer] = {}  # Cache keyframes
        
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
        self._frame_buffers[stream_key] = FrameBuffer(max_frames=90)  # ~3 seconds at 30fps
        _LOGGER.info("Prepared RTSP stream for %s", stream_key)
        return True

    def _start_ffmpeg_sync(self, stream_key: str, codec_id: int, initial_frames: List[bytes]) -> bool:
        """Start FFmpeg process (sync, called from push_frame).
        
        Args:
            stream_key: Stream identifier (did_channel)
            codec_id: 4 for H.264, 5 for H.265
            initial_frames: List of frames to send, should start with keyframe
        """
        try:
            did, channel = stream_key.rsplit("_", 1)
            rtsp_url = f"rtsp://localhost:8554/camera/{did}/{channel}"
            input_format = "hevc" if codec_id == 5 else "h264"
            
            # Determine if we need to transcode
            need_transcode = self._transcode_h264 and codec_id == 5  # H.265
            
            # FFmpeg settings depend on whether we're transcoding or passing through
            # For passthrough: minimal probe size for low latency
            # For transcoding: larger probe size to properly analyze HEVC stream
            if need_transcode:
                # Transcoding needs more analysis time for HEVC
                probesize = "5000000"    # 5MB - enough for complete IDR frame analysis
                analyzeduration = "5000000"  # 5 seconds
            else:
                # Passthrough: minimal latency
                probesize = "32768"      # 32KB
                analyzeduration = "0"
            
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                # Input settings
                "-probesize", probesize,
                "-analyzeduration", analyzeduration,
                "-fflags", "+genpts+discardcorrupt+igndts",
                "-flags", "low_delay",
                "-err_detect", "ignore_err",  # Ignore decode errors
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
                    "-maxrate", "2.5M",
                    "-bufsize", "2M",
                    "-g", "30",  # Keyframe every 30 frames
                    "-keyint_min", "15",
                    "-x264-params", "nal-hrd=cbr:force-cfr=1",
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
            
            # Write initial frames (keyframe + following frames)
            if process.stdin and initial_frames:
                _LOGGER.info("Sending %d initial frames to FFmpeg [%s]", len(initial_frames), stream_key)
                for frame in initial_frames:
                    process.stdin.write(frame)
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
        
        # Clear frame buffer
        if stream_key in self._frame_buffers:
            self._frame_buffers[stream_key].clear()
            del self._frame_buffers[stream_key]
        
        _LOGGER.info("Stopped RTSP stream: %s", stream_key)

    async def push_frame(self, did: str, frame_data: bytes, channel: int = 0):
        """Push H.264/H.265 frame to stream."""
        stream_key = f"{did}_{channel}"
        
        if stream_key not in self._prepared_streams:
            return
        
        # Get or create frame buffer
        if stream_key not in self._frame_buffers:
            self._frame_buffers[stream_key] = FrameBuffer(max_frames=90)
        frame_buffer = self._frame_buffers[stream_key]
        
        # First frame: detect codec
        if stream_key not in self._detected_codecs:
            detected = detect_codec_from_nalu(frame_data)
            if detected == 0:
                detected = 5
            self._detected_codecs[stream_key] = detected
            
            codec_name = "H.265" if detected == 5 else "H.264"
            _LOGGER.info("Detected %s for %s (frame size=%d)", codec_name, stream_key, len(frame_data))
        
        codec_id = self._detected_codecs.get(stream_key, 5)
        is_key = is_keyframe(frame_data, codec_id)
        
        # Always add to buffer (for FFmpeg restart)
        frame_buffer.add_frame(frame_data, is_key)
        
        # FFmpeg not started yet? Wait for keyframe
        if stream_key not in self._streamers:
            if not frame_buffer.has_keyframe():
                # Still waiting for first keyframe
                return
            
            # Have keyframe, start FFmpeg with buffered frames
            initial_frames = frame_buffer.get_frames()
            _LOGGER.info("Got keyframe for %s, starting FFmpeg with %d buffered frames", 
                        stream_key, len(initial_frames))
            self._start_ffmpeg_sync(stream_key, codec_id, initial_frames)
            self._frame_counts[stream_key] = len(initial_frames)
            return
        
        # FFmpeg crashed? Wait for next keyframe to restart
        if not self._is_stream_running(stream_key):
            if not is_key:
                # Wait for keyframe before restarting
                return
            
            _LOGGER.warning("FFmpeg [%s] not running, restarting with keyframe", stream_key)
            # Clean up old writer
            if stream_key in self._writers:
                self._writers[stream_key].stop()
                del self._writers[stream_key]
            
            # Restart with buffered frames starting from this keyframe
            initial_frames = frame_buffer.get_frames()
            self._start_ffmpeg_sync(stream_key, codec_id, initial_frames)
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
