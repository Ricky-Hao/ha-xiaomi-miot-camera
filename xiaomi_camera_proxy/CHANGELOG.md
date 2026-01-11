# Changelog

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
