# -*- coding: utf-8 -*-
"""Media decoder for camera frames.

Based on xiaomi-miloco reference implementation.
Uses direct Packet decoding without parse() for H.264/H.265 streams.

MIoT Camera Codec IDs (from native library):
- VIDEO_H264 = 4
- VIDEO_HEVC/VIDEO_H265 = 5
- AUDIO_PCM = 1024
- AUDIO_G711U = 1026
- AUDIO_G711A = 1027
- AUDIO_OPUS = 1032
"""
import io
import logging
from typing import Optional, Dict
from enum import IntEnum

_LOGGER = logging.getLogger(__name__)


class MIoTCameraCodec(IntEnum):
    """MIoT Camera Codec IDs (matching native library)."""
    VIDEO_H264 = 4
    VIDEO_HEVC = 5
    VIDEO_H265 = 5
    
    AUDIO_PCM = 1024
    AUDIO_G711U = 1026
    AUDIO_G711A = 1027
    AUDIO_OPUS = 1032


class MIoTMediaDecoder:
    """Decoder for video/audio frames.
    
    Key insight from reference implementation:
    - Use Packet(data) directly, not codec.parse()
    - Maintain codec context per stream for SPS/PPS state
    - Let the codec handle NAL accumulation internally
    """

    def __init__(self, enable_hw_accel: bool = False):
        """Initialize decoder."""
        self._enable_hw_accel = enable_hw_accel
        # Keep codec contexts per stream to maintain SPS/PPS state
        self._video_codecs: Dict[str, any] = {}

    def decode_to_jpg(self, frame_data: bytes, codec_id: int, stream_id: str = "default") -> Optional[bytes]:
        """Decode video frame to JPG.
        
        Uses direct Packet decoding (matching xiaomi-miloco reference).
        The codec context maintains SPS/PPS state across calls.
        
        Args:
            frame_data: Raw video frame data (NAL units)
            codec_id: MIoT codec ID (4=H.264, 5=H.265)
            stream_id: Unique identifier for stream state
        """
        try:
            import av
            from av.packet import Packet
            from av.video.codeccontext import VideoCodecContext
            from PIL import Image

            # Determine codec name from MIoT codec ID
            if codec_id == MIoTCameraCodec.VIDEO_H264:
                codec_name = "h264"
            elif codec_id in (MIoTCameraCodec.VIDEO_HEVC, MIoTCameraCodec.VIDEO_H265):
                codec_name = "hevc"
            else:
                _LOGGER.warning("Unknown video codec: %d", codec_id)
                return None

            # Get or create codec context for this stream
            codec_key = f"{stream_id}_{codec_name}"
            if codec_key not in self._video_codecs:
                # Use VideoCodecContext.create() like reference implementation
                codec = VideoCodecContext.create(codec_name, "r")
                self._video_codecs[codec_key] = codec
                _LOGGER.info("Created VideoCodecContext for %s", codec_key)

            codec = self._video_codecs[codec_key]
            
            # Decode using Packet directly (reference implementation pattern)
            # Don't use parse() - let the codec handle NAL parsing
            pkt = Packet(frame_data)
            try:
                frames = codec.decode(pkt)
                for frame in frames:
                    # Convert to RGB then to PIL Image
                    rgb_frame = frame.to_rgb()
                    img = rgb_frame.to_image()

                    # Convert to JPG
                    jpg_buffer = io.BytesIO()
                    img.save(jpg_buffer, format="JPEG", quality=90)
                    jpg_data = jpg_buffer.getvalue()
                    _LOGGER.debug("Decoded frame to JPG: %d bytes", len(jpg_data))
                    return jpg_data
            except av.AVError as e:
                # This is normal - decoder needs SPS/PPS before it can decode
                _LOGGER.debug("Decode pending (waiting for keyframe): %s", e)

        except ImportError as e:
            _LOGGER.error("Missing dependency: %s", e)
        except Exception as e:
            _LOGGER.warning("Failed to decode frame: %s", e)

        return None

    def reset_codec(self, stream_id: str = "default"):
        """Reset codec context for a stream."""
        keys_to_remove = [k for k in self._video_codecs.keys() if k.startswith(stream_id)]
        for key in keys_to_remove:
            del self._video_codecs[key]
        _LOGGER.info("Reset codec for stream: %s", stream_id)

    def decode_to_pcm(self, frame_data: bytes, codec_id: int) -> Optional[bytes]:
        """Decode audio frame to PCM.
        
        Args:
            frame_data: Raw audio frame data
            codec_id: MIoT codec ID (1024=PCM, 1026=G711U, 1027=G711A, 1032=OPUS)
        """
        try:
            import av
            from av.packet import Packet
            from av.audio.codeccontext import AudioCodecContext
            from av.audio.resampler import AudioResampler

            # Determine codec from MIoT codec ID
            if codec_id == MIoTCameraCodec.AUDIO_PCM:
                return frame_data  # Already PCM
            elif codec_id == MIoTCameraCodec.AUDIO_OPUS:
                codec_name = "opus"
            elif codec_id == MIoTCameraCodec.AUDIO_G711A:
                codec_name = "pcm_alaw"
            elif codec_id == MIoTCameraCodec.AUDIO_G711U:
                codec_name = "pcm_mulaw"
            else:
                _LOGGER.warning("Unknown audio codec: %d", codec_id)
                return frame_data

            codec = AudioCodecContext.create(codec_name, "r")
            resampler = AudioResampler(format="s16", layout="mono", rate=16000)

            pkt = Packet(frame_data)
            frames = codec.decode(pkt)
            pcm_data = b""
            for frame in frames:
                rs_frames = resampler.resample(frame)
                for rs_frame in rs_frames:
                    pcm_data += rs_frame.to_ndarray().tobytes()

            return pcm_data if pcm_data else None

        except Exception as e:
            _LOGGER.warning("Failed to decode audio: %s", e)

        return None
