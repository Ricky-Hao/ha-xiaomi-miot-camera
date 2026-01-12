# -*- coding: utf-8 -*-
# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""Main entry point for camera proxy."""
import argparse
import asyncio
import logging
import sys

from . import __version__
from .server import CameraProxyServer


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Xiaomi MIoT Camera Proxy")
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="Port to bind (default: 8765)"
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Log level (default: info)",
    )
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )

    logger = logging.getLogger(__name__)
    logger.info("Starting Xiaomi MIoT Camera Proxy v%s (using miot_kit)", __version__)

    # Run server
    async def run():
        server = CameraProxyServer(host=args.host, port=args.port)
        await server.start_async()
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await server.stop_async()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
