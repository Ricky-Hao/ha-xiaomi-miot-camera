# syntax=docker/dockerfile:1
ARG BUILD_FROM=debian:bookworm-slim
FROM ${BUILD_FROM}

# Set environment
ENV LANG=C.UTF-8
ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    libgomp1 \
    jq \
    curl \
    ffmpeg \
    git \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Install mediamtx (lightweight RTSP server)
# Only used for RTSP relay, WebRTC is handled by HA go2rtc
ARG TARGETARCH
RUN MEDIAMTX_VERSION="1.9.3" && \
    if [ "$TARGETARCH" = "amd64" ]; then ARCH="linux_amd64"; \
    elif [ "$TARGETARCH" = "arm64" ]; then ARCH="linux_arm64v8"; \
    else echo "Unsupported architecture: $TARGETARCH" && exit 1; fi && \
    curl -fsSL "https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/mediamtx_v${MEDIAMTX_VERSION}_${ARCH}.tar.gz" | \
    tar -xzf - -C /usr/local/bin mediamtx && \
    chmod +x /usr/local/bin/mediamtx

# Create virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install Python dependencies (including miot_kit from git)
WORKDIR /app
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy rootfs (run script)
COPY rootfs/ /

# Copy application source
COPY src/ /app/

# Note: Native library is now included in miot_kit package
# No need to copy libs/ separately

# Set permissions
RUN chmod +x /run.sh

# Expose ports
# 8765: HTTP API
# 8554: RTSP streaming (internal, FFmpeg -> MediaMTX)
# 8889: WebRTC (WHEP endpoint)
EXPOSE 8765 8554 8889

CMD ["/run.sh"]
