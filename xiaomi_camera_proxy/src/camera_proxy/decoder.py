# -*- coding: utf-8 -*-
"""Media decoder for camera frames."""
import io
import logging
from typing import Optional

_LOGGER = logging.getLogger(__name__)


class MIoTMediaDecoder:
    """Decoder for video/audio frames."""

    def __init__(self, enable_hw_accel: bool = False):
        """Initialize decoder."""
        self._enable_hw_accel = enable_hw_accel
        self._codec_context = None

    def decode_to_jpg(self, frame_data: bytes, codec_id: int) -> Optional[bytes]:
        """Decode video frame to JPG."""
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

            # Create codec context
            codec = av.CodecContext.create(codec_name, "r")

            # Decode frame
            packets = codec.parse(frame_data)
            for packet in packets:
                frames = codec.decode(packet)
                for frame in frames:
                    # Convert to PIL Image
                    img = frame.to_image()

                    # Convert to JPG
                    buffer = io.BytesIO()
                    img.save(buffer, format="JPEG", quality=85)
                    return buffer.getvalue()

        except Exception as e:
            _LOGGER.warning("Failed to decode frame: %s", e)

        return None

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
