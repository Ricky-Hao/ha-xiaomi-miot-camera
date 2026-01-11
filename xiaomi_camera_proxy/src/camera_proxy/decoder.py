# -*- coding: utf-8 -*-
"""Media decoder for camera frames."""
import io
import logging
from typing import Optional, Dict

_LOGGER = logging.getLogger(__name__)


class MIoTMediaDecoder:
    """Decoder for video/audio frames."""

    def __init__(self, enable_hw_accel: bool = False):
        """Initialize decoder."""
        self._enable_hw_accel = enable_hw_accel
        # Keep codec contexts per stream to maintain SPS/PPS state
        self._video_codecs: Dict[str, any] = {}
        self._frame_buffers: Dict[str, bytes] = {}

    def decode_to_jpg(self, frame_data: bytes, codec_id: int, stream_id: str = "default") -> Optional[bytes]:
        """Decode video frame to JPG.
        
        H.264 streams need to accumulate SPS/PPS/IDR frames before decoding.
        """
        try:
            import av
            from PIL import Image

            # Determine codec
            if codec_id == 27:  # H264
                codec_name = "h264"
            elif codec_id == 173:  # H265/HEVC
                codec_name = "hevc"
            else:
                _LOGGER.warning("Unknown codec: %d", codec_id)
                return None

            # Get or create codec context for this stream
            codec_key = f"{stream_id}_{codec_name}"
            if codec_key not in self._video_codecs:
                codec = av.CodecContext.create(codec_name, "r")
                # Set some options that may help with parsing
                codec.thread_type = "AUTO"
                self._video_codecs[codec_key] = codec
                self._frame_buffers[codec_key] = b""
                _LOGGER.info("Created codec context for %s", codec_key)

            codec = self._video_codecs[codec_key]
            
            # Accumulate frame data
            self._frame_buffers[codec_key] += frame_data
            buffer = self._frame_buffers[codec_key]
            
            # Try to parse and decode
            try:
                packets = list(codec.parse(buffer))
                if packets:
                    # Successfully parsed, clear buffer
                    self._frame_buffers[codec_key] = b""
                    
                    for packet in packets:
                        try:
                            frames = codec.decode(packet)
                            for frame in frames:
                                # Convert to PIL Image
                                img = frame.to_image()

                                # Convert to JPG
                                jpg_buffer = io.BytesIO()
                                img.save(jpg_buffer, format="JPEG", quality=85)
                                jpg_data = jpg_buffer.getvalue()
                                _LOGGER.debug("Decoded frame to JPG: %d bytes", len(jpg_data))
                                return jpg_data
                        except av.AVError as e:
                            _LOGGER.debug("Decode error (need more data): %s", e)
                            continue
            except av.AVError as e:
                _LOGGER.debug("Parse error (need more data): %s", e)
            
            # Prevent buffer from growing too large (max 1MB)
            if len(self._frame_buffers[codec_key]) > 1024 * 1024:
                _LOGGER.warning("Frame buffer too large, clearing")
                self._frame_buffers[codec_key] = b""

        except Exception as e:
            _LOGGER.warning("Failed to decode frame: %s", e)

        return None

    def reset_codec(self, stream_id: str = "default"):
        """Reset codec context for a stream."""
        keys_to_remove = [k for k in self._video_codecs.keys() if k.startswith(stream_id)]
        for key in keys_to_remove:
            del self._video_codecs[key]
            if key in self._frame_buffers:
                del self._frame_buffers[key]

    def decode_to_pcm(self, frame_data: bytes, codec_id: int) -> Optional[bytes]:
        """Decode audio frame to PCM."""
        try:
            import av

            # Determine codec
            if codec_id == 86018:  # AAC
                codec_name = "aac"
            else:
                return frame_data  # Already PCM

            codec = av.CodecContext.create(codec_name, "r")

            packets = codec.parse(frame_data)
            pcm_data = b""
            for packet in packets:
                frames = codec.decode(packet)
                for frame in frames:
                    pcm_data += frame.to_ndarray().tobytes()

            return pcm_data if pcm_data else None

        except Exception as e:
            _LOGGER.warning("Failed to decode audio: %s", e)

        return None
