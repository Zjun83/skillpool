#!/usr/bin/env python3
"""Prometheus metrics server for SkillPool.

Runs a lightweight HTTP server on port 9101 serving /metrics endpoint
in Prometheus exposition format. Reads from the running SkillPool MCP
server's MonitorLayer instance.

Usage:
    python scripts/metrics_server.py [--port 9101]

Part of SkillPool — independent infrastructure, shared by all agents.
"""

from __future__ import annotations

import argparse
import http.server
import logging
import signal
import sys

logger = logging.getLogger("skillpool.metrics")


class MetricsHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler that serves Prometheus metrics."""

    def do_GET(self):
        if self.path == "/metrics":
            try:
                # Import the running MCP server's monitor instance
                from skillpool.mcp_server import _monitor

                content = _monitor.to_prometheus()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
            except Exception as e:
                logger.error("metrics_export_failed: %s", e)
                self.send_response(500)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(f"Error: {e}\n".encode("utf-8"))
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write("ok\n".encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        logger.debug("metrics_http: %s", format % args)


def main():
    parser = argparse.ArgumentParser(description="SkillPool Prometheus metrics server")
    parser.add_argument("--port", type=int, default=9101, help="Port to serve metrics on")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    server = http.server.HTTPServer(("0.0.0.0", args.port), MetricsHandler)
    logger.info("metrics_server_starting: port=%d", args.port)

    # Graceful shutdown
    def shutdown(sig, frame):
        logger.info("metrics_server_shutting_down")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    server.serve_forever()


if __name__ == "__main__":
    main()