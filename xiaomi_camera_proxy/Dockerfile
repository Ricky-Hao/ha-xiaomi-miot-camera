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
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install Python dependencies
WORKDIR /app
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy rootfs (run script)
COPY rootfs/ /

# Copy application source
COPY src/ /app/

# Copy native library
COPY libs/linux/ /app/libs/linux/

# Set permissions
RUN chmod +x /run.sh

# Expose WebSocket port
EXPOSE 8765

CMD ["/run.sh"]
