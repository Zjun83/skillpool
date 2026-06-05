"""E2E test for SkillPool MCP HTTP transport.

Tests the streamable-http transport by starting skillpool-mcp on a test port
and sending MCP protocol requests via httpx. Requires session ID handling
per MCP Streamable HTTP spec.
"""

from __future__ import annotations

import subprocess
import sys
import time
import signal
from pathlib import Path

import httpx
import pytest

MCP_PORT = 18101
MCP_URL = f"http://127.0.0.1:{MCP_PORT}/mcp"
MCP_BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

PYTHON = str(Path(sys.executable))


@pytest.fixture(scope="module")
def mcp_server():
    """Start skillpool-mcp in HTTP mode for testing."""
    proc = subprocess.Popen(
        [
            PYTHON,
            "-m",
            "skillpool.mcp_server",
            "--transport",
            "streamable-http",
            "--port",
            str(MCP_PORT),
            "--host",
            "127.0.0.1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(4)
    yield proc
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _init_session(client: httpx.Client, port: int = MCP_PORT) -> dict:
    """Initialize MCP session and return headers with session ID."""
    url = f"http://127.0.0.1:{port}/mcp"
    resp = client.post(
        url,
        json={
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
        headers=MCP_BASE_HEADERS,
    )
    assert resp.status_code == 200, f"Initialize failed: {resp.status_code}"
    session_id = resp.headers.get("mcp-session-id", "")
    headers = {**MCP_BASE_HEADERS, "Mcp-Session-Id": session_id}
    # Send initialized notification
    client.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
    return {"url": url, "headers": headers}


class TestHTTPTransport:
    """Basic HTTP transport tests."""

    def test_initialize(self, mcp_server):
        with httpx.Client(timeout=10) as client:
            session = _init_session(client)
            assert session["headers"]["Mcp-Session-Id"]

    def test_tools_list(self, mcp_server):
        with httpx.Client(timeout=10) as client:
            session = _init_session(client)
            resp = client.post(
                session["url"], json={"jsonrpc": "2.0", "method": "tools/list", "id": 2}, headers=session["headers"]
            )
            assert resp.status_code == 200

    def test_resources_list(self, mcp_server):
        with httpx.Client(timeout=10) as client:
            session = _init_session(client)
            resp = client.post(
                session["url"], json={"jsonrpc": "2.0", "method": "resources/list", "id": 3}, headers=session["headers"]
            )
            assert resp.status_code == 200


class TestConcurrency:
    """Sequential rapid-fire request tests."""

    def test_10_concurrent_requests(self, mcp_server):
        with httpx.Client(timeout=15) as client:
            session = _init_session(client)
            results = []
            for i in range(10):
                try:
                    resp = client.post(
                        session["url"],
                        json={"jsonrpc": "2.0", "method": "tools/list", "id": 100 + i},
                        headers=session["headers"],
                    )
                    results.append(("ok", i) if resp.status_code == 200 else ("fail", i, resp.status_code))
                except Exception as e:
                    results.append(("error", i, str(e)))

            ok_count = sum(1 for r in results if r[0] == "ok")
            assert ok_count >= 8, f"Only {ok_count}/10 requests succeeded: {results}"


class TestGracefulShutdown:
    """Test that SIGTERM causes exit."""

    def test_sigterm_exit(self):
        proc = subprocess.Popen(
            [
                PYTHON,
                "-m",
                "skillpool.mcp_server",
                "--transport",
                "streamable-http",
                "--port",
                "18102",
                "--host",
                "127.0.0.1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(4)
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
            # -15 (SIGTERM) is acceptable — Python processes exit with -signal on SIGTERM
            assert proc.returncode in (0, -15), f"Exit code was {proc.returncode}"
        except subprocess.TimeoutExpired:
            proc.kill()
            pytest.fail("Server did not exit within 10s of SIGTERM")
