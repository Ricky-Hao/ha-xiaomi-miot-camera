# Changelog

## [0.6.16] - 2026-01-12 (Integration + Add-on)

### Fixed
- **Fix camera auto-reconnect after integration reconfigure**: Now properly handles placeholder tokens
  - When integration sends "managed_by_addon" placeholder, Add-on uses existing saved tokens and triggers auto-start
  - Previously, placeholder tokens were ignored, preventing auto-reconnect
- **Fix camera state showing "Idle" instead of "Recording"**: Added `is_recording` property to camera entity
  - When streaming, camera now shows "监控中" (Recording) instead of "空闲" (Idle)

## [0.6.15] - 2026-01-12 (Integration + Add-on)

### Fixed
- **Fix camera auto-reconnect after integration reconfigure**: Cameras now automatically restart when tokens are refreshed via `set_tokens_async`
- Previously, reconfiguring the integration would not reconnect cameras until Add-on restart

### Changed
- **Code cleanup**: Removed legacy WebSocket API code (not needed, project in active development)
- **Simplified server**: Removed unused imports and WebSocket handlers
- **Cleaner API**: Video quality is now Add-on config only, removed from HTTP API parameters

## [0.5.1] - 2026-01-12 (Add-on)

### Fixed
- **Fix first frame loss**: First frame containing VPS/SPS/PPS is now properly sent to FFmpeg
- Previously, first frame was used for codec detection but lost before FFmpeg started
- This caused "PPS id out of range" errors for some cameras

### Changed
- **Reduce log noise**: FFmpeg log level changed to warning, periodic frame logs reduced to every 500 frames
- **Simplified code**: Removed redundant logging and unused variables

## [0.5.0] - 2026-01-12 (Integration + Add-on)

### Changed - Architecture Refactoring
- **Switch to go2rtc-based WebRTC streaming**: Major architecture simplification
- **Add-on changes**:
  - MediaMTX now only serves RTSP (WebRTC disabled)
  - RTSP streams available at `rtsp://<host>:8554/camera/{did}/{channel}`
  - Removed port 8889 (WebRTC), kept only 8765 (API) and 8554 (RTSP)
- **Integration changes**:
  - `stream_source()` now returns RTSP URL instead of None
  - Removed all custom WHEP/WebRTC code
  - HA's native go2rtc handles WebRTC conversion automatically
- **Benefits**:
  - Simpler architecture with fewer moving parts
  - Leverages HA's battle-tested go2rtc for WebRTC
  - Better codec compatibility (go2rtc handles H.265/H.264 transcoding)
  - Improved reliability and maintainability

## [0.4.21] - 2026-01-12 (Add-on)

### Fixed
- **Fix HEVC parameter set detection**: Increased FFmpeg probesize to 5MB and analyzeduration to 5s
- Previous probesize (32 bytes) was too small to find VPS/SPS/PPS parameter sets
- This caused "PPS id out of range" and "dimensions not set" errors
- FFmpeg now waits for enough data to properly detect video parameters

## [0.4.20] - 2026-01-12 (Add-on)

### Changed
- **Enhanced FFmpeg debugging**: Added detailed logging for FFmpeg output
- **Improved FFmpeg startup**: Added probesize/analyzeduration settings for faster stream initialization
- **Better frame logging**: Log first frame header bytes to debug codec detection
- **Wait for FFmpeg**: Brief delay after starting FFmpeg before pushing frames

## [0.4.15] - 2026-01-12 (Integration)

### Fixed
- **Fix "stream doesn't contain any supported codec" error**: Auto-start camera stream before WebRTC negotiation
- **Add retry logic for WebRTC**: Retry WHEP request up to 3 times if stream is not ready
- Camera will now automatically start streaming when user opens the camera view

## [0.4.19] - 2026-01-12 (Add-on)

### Changed
- **Add STUN servers to MediaMTX**: Use Google's public STUN servers for better NAT traversal
- This should improve WebRTC connectivity in various network environments

## [0.4.14] - 2026-01-12 (Integration)

### Changed
- **Upgrade to new async WebRTC API**: Use `async_handle_async_webrtc_offer` instead of deprecated `async_handle_web_rtc_offer`
- **Add ICE candidate handling**: Implement `async_on_webrtc_candidate` method
- **Add session cleanup**: Implement `close_webrtc_session` to properly clean up WHEP sessions
- These changes should improve WebRTC streaming reliability and compatibility with newer Home Assistant versions

## [0.4.13] - 2026-01-12 (Integration)

### Fixed
- **Add explicit stream_source() method**: Returns None to indicate HLS/RTSP streaming is not supported
- This camera integration only supports WebRTC streaming
- The `play_stream` service (to cast to media players) is not supported - this is expected behavior

## [0.4.12] - 2026-01-12 (Integration)

### Fixed
- **Fix device cleanup on reconfigure**: Devices are now properly removed when cameras are deselected in options flow
- Previously only entities were removed, but devices remained in the registry
- Changed logic to pre-calculate which devices need removal instead of checking after entity deletion

## [0.4.18] - 2026-01-12

### Fixed
- **Fix connection leak**: Call `destroy_camera_async()` when stopping cameras to release native library connections
- Previously only called `stop_camera_async()` which stops streaming but keeps the connection
- This caused "too many connections" error when cameras were started/stopped multiple times

### Changed
- Each camera now has exactly one connection at a time
- Connection is properly released when camera is stopped or Add-on is shut down

## [0.4.17] - 2026-01-12

### Removed
- **Remove external RTSP API**: `/camera/{did}/rtsp_url` endpoint removed
- **Remove rtsp_url from responses**: Start camera now returns only status, no RTSP URL
- **Integration cleanup**: Remove `stream_source()`, `get_rtsp_url_async()` - WebRTC only

### Architecture
- WebRTC is now the only external streaming protocol
- Internal RTSP (FFmpeg → MediaMTX) remains for WebRTC source
- Simpler codebase with single streaming path

## [0.4.16] - 2026-01-12

### Changed
- **RTSP internal only**: Remove external RTSP port (8554) - used internally by FFmpeg→MediaMTX
- **Simplified ports**: Only expose API (8765) and WebRTC (8889)

### Architecture
```
Camera → miot_kit → FFmpeg → RTSP (internal) → MediaMTX → WebRTC (external)
```

## [0.4.15] - 2026-01-12

### Changed
- **WebRTC only**: Disable HLS, use WebRTC exclusively for lowest latency
- **Removed port 8888**: No longer needed without HLS

### Simplified
- MediaMTX now provides: RTSP (8554), WebRTC (8889), API (9997)
- Less resource usage without HLS segment generation

## [0.4.14] - 2026-01-12

### Added
- **WebRTC support**: Enable MediaMTX WebRTC server on port 8889 for instant low-latency streaming
- **HLS always-on**: Enable MediaMTX HLS server on port 8888 with `hlsAlwaysRemux` for pre-generated HLS segments
- **Camera WebRTC integration**: Implement `async_handle_web_rtc_offer()` using MediaMTX WHEP protocol

### Changed
- **Instant camera playback**: WebRTC streams directly from MediaMTX without HA stream component transcoding
- **Fallback to HLS**: If WebRTC unavailable, uses HLS which is always ready from MediaMTX

### New Ports
- `8888/tcp`: HLS streaming (always-on, pre-generated segments)
- `8889/tcp`: WebRTC streaming (WHEP protocol, lowest latency)

### Technical
- MediaMTX now provides: RTSP (8554), HLS (8888), WebRTC (8889), API (9997)
- Camera entity uses `StreamType.WEB_RTC` as frontend stream type
- HLS configured with LL-HLS (Low Latency HLS) for ~1-2s latency

## [0.4.13] - 2026-01-12

### Fixed
- **Revert non-blocking start**: Always wait for RTSP stream to be ready before returning
- **Fix HLS playlist delay**: 0.4.12's non-blocking approach caused HA's stream component to wait at HLS level
- Removed `wait_ready` parameter - always ensure stream is ready

### Behavior
- If camera already streaming and ready → returns immediately (0 delay)
- If camera already active but stream not ready → waits for stream
- If camera not active → starts camera and waits for stream to be ready
- This ensures HLS playlist generation doesn't block waiting for RTSP data

## [0.4.12] - 2026-01-12

### Changed
- **Non-blocking camera start by default**: `start_camera` now returns immediately without waiting for RTSP stream
- **New `wait_ready` parameter**: Optional parameter to wait for stream ready (default: false)
- Integration can now start cameras without blocking, RTSP stream prepares in background

### Improved
- **Faster first-time camera startup**: Integration initialization no longer blocks waiting for stream
- Add-on auto-starts cameras on boot, so streams are ready before user opens HA
- Combined with 0.4.10/0.4.11 optimizations, camera opens nearly instantly

### API Changes
- `POST /camera/{did}/start` now accepts `wait_ready` boolean parameter (default: false)
- WebSocket `start_camera` also accepts `wait_ready` parameter

## [0.4.11] - 2026-01-12

### Changed
- **Always-on streaming optimization**: If camera is already streaming, `start_camera` returns immediately without re-initialization
- **Reduced camera open latency**: Skip wait time when RTSP stream is already ready
- **Refactored stream ready check**: Extracted `_check_stream_ready_async()` for non-blocking status check

### Improved
- Opening camera in HA frontend is now instant when stream is already active
- Better code organization for stream status checking

## [0.4.10] - 2026-01-12

### Added
- **Auto-start cameras on Add-on restart**: Previously active cameras are now saved and automatically restarted when Add-on boots
- **Wait for RTSP stream ready**: Camera start now waits for MediaMTX to confirm stream is publishing before returning

### Fixed
- **Issue 1**: Add-on restart no longer requires Integration re-initialization - cameras auto-start from saved state
- **Issue 2**: First camera view no longer shows frozen frame - ensures stream is ready before HA connects

## [0.4.2] - 2026-01-12

### Fixed
- **Fix OAuth redirect_uri error**: Use Xiaomi's official redirect_uri (`https://mico.api.mijia.tech/login_redirect`) instead of custom HA callback URL
- Users now manually copy code and state from Xiaomi's redirect page
- Remove unused auth_callback.py (no longer needed with official redirect_uri)
- Simplify config_flow.py

## [0.4.1] - 2026-01-12

### Changed
- Remove unused code from Integration (common.py, error.py, LICENSE)
- Simplify types.py (keep only camera-related types)
- Clean up unused imports and constants
- Fix server import in __main__.py

## [0.4.0] - 2026-01-12

### Major Refactoring
- **Use miot_kit package**: Replaced all custom MIoT code with miot_kit from xiaomi-miloco
- **Simplified architecture**: CameraService handles all camera operations using miot_kit
- **New HTTP API**: RESTful endpoints for OAuth, device discovery, camera control
- **pip install from git**: miot_kit installed via `pip install git+...#subdirectory=miot_kit`

### Added
- New `CameraService` class using miot_kit's `MIoTCamera`
- HTTP endpoints: `/oauth/*`, `/devices`, `/cameras`, `/camera/{did}/*`, `/snapshot/*`
- OAuth flow support directly in Add-on
- Token persistence in `/data/tokens.json`

### Changed
- Server rewritten as `server_v2.py` using `CameraService`
- Native library now comes bundled with miot_kit package
- Removed redundant `camera_manager.py`, `decoder.py` code
- WebSocket API kept for backward compatibility but deprecated

### Technical
- miot_kit provides: OAuth2, cloud API, camera library wrapper, video decoding
- Add-on no longer needs to copy `libs/` directory manually
- Reduced code duplication between Integration and Add-on

## [0.3.4] - 2026-01-12

### Fixed
- **Fix snapshot/thumbnail generation**: Detect H.265 keyframes by NAL type instead of unreliable frame_type
- Parse NAL header to find IDR frames (type 19/20 for H.265, type 5 for H.264)
- Also detect VPS/SPS/PPS frames as keyframe candidates
- Fixes camera_proxy thumbnail requests returning empty

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

## [0.5.2] - 2025-01-XX

### Changed
- Rewritten RTSP streamer for stability (borrowed from miloco design)
  - Added dedicated writer thread to prevent asyncio blocking
  - Reduced probesize from 5MB to 32KB for faster stream start
  - Added frame queue with automatic drop on overflow
  - Added automatic FFmpeg restart on crash

## [0.5.3] - 2025-01-12

### Changed
- Increased MediaMTX read/write timeout from 10s to 60s for unstable connections
- Enabled MediaMTX API on port 9997 for debugging
- Added detailed status change logging for camera disconnect/reconnect
- Added periodic frame count logging for debugging (every 100 frames)

## [0.5.4] - 2025-01-12

### Changed
- Improved frame logging: log first frame and every 30 frames (once per second)
- Added sourceOnDemand: no to MediaMTX config
- This will help identify if miot_kit stops sending frames

## [0.5.5] - 2025-01-12

### Added
- **H.265→H.264 transcoding** for browser WebRTC compatibility
  - Enabled by default (`transcode_h264: true` in Add-on config)
  - Solves HLS fallback issue - WebRTC should work in all browsers now
  - Uses FFmpeg libx264 with ultrafast preset for low latency
  - Disable via Add-on config if your browser supports H.265 WebRTC

## [0.6.0] - 2025-01-12

### Changed
- **Major architecture change: Direct WebRTC streaming**
  - Add-on now provides WebRTC directly via WHEP (port 8889)
  - No longer depends on HA go2rtc
  - Integration handles WebRTC signaling via `async_handle_web_rtc_offer()`
  - FFmpeg transcodes H.265→H.264 for browser compatibility
  - MediaMTX converts RTSP to WebRTC internally

### Removed
- RTSP port 8554 exposure (now internal only)
- Dependency on HA go2rtc for WebRTC conversion

## [0.6.1] - 2025-01-12

### Changed
- Simplified OAuth flow: now accepts a single Base64 string instead of separate code and state fields
- Updated UI strings in English and Chinese

## [0.6.2] - 2026-01-12

### Fixed
- Fix H.265→H.264 transcoding by waiting for keyframe before starting FFmpeg
- Add FrameBuffer class to cache frames from last keyframe
- FFmpeg now receives complete GOP (keyframe + following frames) on start/restart
- This prevents "Error parsing NAL unit" errors when FFmpeg starts from P-frame

## [0.6.3] - 2026-01-12

### Fixed
- Add explicit frame rate (-r 15) for FFmpeg input and output
- Increase FFmpeg log level to info for better debugging
- Add RTSP timeout parameter (30 seconds)
- Increase encoder buffer size to 4MB
- Improve FFmpeg error monitoring to show all output

## [0.6.4] - 2026-01-12

### Fixed
- Fix MediaMTX not starting - add proper startup check with nc (netcat)
- Wait up to 30 seconds for MediaMTX to be ready before starting Python
- Add netcat-openbsd to Dockerfile for port checking
- Add 8889 port to Dockerfile EXPOSE
- Improve startup script error messages

## [0.6.5] - 2026-01-12

### Fixed
- Fix MediaMTX ICE server configuration format (use `url:` instead of `urls:`)

## [0.6.6] - 2026-01-12

### Changed
- Use custom STUN server (gd.rickyhao.com:3478)

## [0.6.7] - 2026-01-12

### Changed
- Remove ICE server config - not needed for local network access

## [0.6.8] - 2026-01-12

### Fixed
- **Fix WebRTC not working**: Update to new HA WebRTC API
  - Use `async_handle_async_webrtc_offer(offer_sdp, session_id, send_message)` instead of old `async_handle_web_rtc_offer`
  - Use `WebRTCAnswer` and `WebRTCError` callback messages
  - This is required for HA 2024.x+ WebRTC support

## [0.6.9] - 2026-01-12

### Changed
- **Faster integration setup**: Don't start cameras during initialization
- Cameras now start on-demand when WebRTC stream is requested
- This makes config flow complete almost instantly
