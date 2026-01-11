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
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy application
WORKDIR /app
COPY rootfs/ /
COPY src/ /app/

# Copy native library
COPY libs/ /app/libs/

# Set permissions
RUN chmod +x /run.sh

# Expose WebSocket port
EXPOSE 8765

CMD ["/run.sh"]
