# Changelog

## [0.3.3] - 2026-01-12

### Fixed
- **Fix RTSP codec detection**: Start FFmpeg lazily on first video frame to detect actual codec
- Properly detect H.265 (codec=5) vs H.264 (codec=4) and pass correct `-f hevc` or `-f h264` to FFmpeg
- Fixes "data partitioning is not implemented" error when camera sends H.265 stream

## [0.3.2] - 2026-01-12

### Fixed
- Remove invalid `sourceOnDemand` from mediamtx config (not needed for publisher mode)
- Add FFmpeg error monitoring and logging
- Add frame count logging to track data flow

### Debug
- Log every 100 frames received from camera
- Log FFmpeg stderr output for troubleshooting

## [0.3.1] - 2026-01-12

### Fixed
- Fix mediamtx.yml config: move `readTimeout`/`writeTimeout` to global level

## [0.3.0] - 2026-01-12

### Added
- **RTSP streaming support** via mediamtx server
- **On-demand streaming** - camera only starts when someone is viewing
- Live H.264 stream pushed to RTSP (no transcoding, low CPU usage)
- FFmpeg integration for RTSP remuxing

### Changed
- Architecture: Add-on now provides RTSP streams instead of JPEG over WebSocket
- Integration: Camera entity now has `stream_source` property for native HA streaming
- JPEG decoding: Only decode I-frames for snapshots (saves CPU)
- Bandwidth: Reduced by 5-10x (H.264 vs JPEG)

### Technical
- Installed mediamtx v1.9.3 (RTSP server)
- Installed FFmpeg for H.264 remuxing
- RTSP port 8554 exposed alongside WebSocket 8765

## [0.2.8] - 2026-01-12

### Fixed
- Use correct MIoT Camera codec IDs (VIDEO_H264=4, VIDEO_H265=5) matching native library
- Use direct `Packet(data)` decoding instead of `parse()` (matching xiaomi-miloco reference)
- Simplified decoder - let codec handle NAL parsing internally
- Improved audio decoding with proper OPUS/G711 codec support

## [0.2.7] - 2026-01-12

### Fixed
- Rewrite decoder to maintain codec context state per stream
- Accumulate H.264 NAL frames (SPS/PPS/IDR) before decoding
- This fixes "Invalid data found when processing input" errors

## [0.2.6] - 2026-01-12

### Fixed
- Detect frame format by data header (00000001=H.264, FFD8=JPEG) instead of codec_id
- Handle H.264 streams reported as codec=5
- Decode all NAL frames (not just I-frames) to support various stream types

## [0.2.5] - 2026-01-12

### Added
- Validate JPEG header (FFD8) before sending frames
- More detailed logging for frame subscription and delivery

## [0.2.4] - 2026-01-12

### Fixed
- Add support for MJPEG codec (codec_id=5) - frames are already JPEG, no decoding needed
- This fixes cameras that output MJPEG instead of H264/H265

## [0.2.3] - 2026-01-12

### Added
- Debug logging for frame reception and decoding to diagnose streaming issues

## [0.2.2] - 2026-01-11

### Fixed
- Use correct API host (`mico.api.mijia.tech`) for camera library authentication

## [0.2.0] - 2026-01-11

### Changed
- Now the only method for camera streaming (native library removed from integration)
- Simplified WebSocket API (removed raw frame types, JPEG only)
- Updated documentation

### Fixed
- Improved stability and error handling

## [0.1.0] - 2026-01-11

### Added
- Initial release
- WebSocket API for camera control
- Support for H264/H265 video decoding to JPEG
- Support for AAC audio decoding to PCM
- Multi-camera support
- Multi-channel support
