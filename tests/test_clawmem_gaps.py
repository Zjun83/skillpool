"""Tests for ClawMem client coverage gaps — uncovered lines from clawmem_client.py.

Targeted gaps:
- L72: write_blindspot with dimension tag
- L84: write_upgrade with skill_id tag
- L134-140: _write_http success path
- L158-168: _write_cli error paths (FileNotFoundError, TimeoutExpired, generic Exception)
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from skillpool.clawmem_client import ClawMemClient, ClawMemStatus, ClawMemWriteResult


@pytest.fixture
def client():
    return ClawMemClient(use_http=False, timeout_seconds=2.0)


@pytest.fixture
def http_client():
    return ClawMemClient(use_http=True, timeout_seconds=2.0)


class TestWriteBlindspotWithDimension:
    def test_includes_dimension_tag(self, client):
        """Line 72: dimension tag appended."""
        with patch.object(client, "_write", return_value=ClawMemWriteResult(success=True, entry_id="e1")) as mock_write:
            client.write_blindspot("D3 issue", dimension="D3", severity="P1", skill_id="S09")
            call_args = mock_write.call_args
            tags = call_args[0][1]
            assert "D3" in tags
            assert "blindspot-report" in tags
            assert "p1" in tags
            assert "S09" in tags


class TestWriteUpgradeWithSkillId:
    def test_includes_skill_id_tag(self, client):
        """Line 84: skill_id tag appended."""
        with patch.object(client, "_write", return_value=ClawMemWriteResult(success=True, entry_id="e1")) as mock_write:
            client.write_upgrade("S09 upgrade", upgrade_type="MINOR", skill_id="S09")
            call_args = mock_write.call_args
            tags = call_args[0][1]
            assert "skill-upgrade" in tags
            assert "minor" in tags
            assert "S09" in tags


class TestWriteHttpSuccess:
    def test_http_success_returns_entry_id(self, http_client):
        """Lines 134-140: HTTP 200 returns success with entry_id."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({"entry_id": "abc123"}).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = http_client._write_http("test entry", ["tag1"])
            assert result.success is True
            assert result.entry_id == "abc123"

    def test_http_non_200_returns_error(self, http_client):
        """Lines 139-140: HTTP non-200 returns error."""
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.read.return_value = b"error"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = http_client._write_http("test entry", ["tag1"])
            assert result.success is False
            assert "500" in result.error

    def test_http_exception_returns_error(self, http_client):
        """Lines 141-142: HTTP exception returns error."""
        with patch("urllib.request.urlopen", side_effect=Exception("connection refused")):
            result = http_client._write_http("test entry", ["tag1"])
            assert result.success is False
            assert "connection refused" in result.error


class TestWriteCliErrors:
    def test_cli_filenotfound_sets_unavailable(self, client):
        """Lines 162-164: FileNotFoundError -> UNAVAILABLE."""
        with patch("subprocess.run", side_effect=FileNotFoundError("no clawmem")):
            result = client._write_cli("test", ["tag1"])
            assert result.success is False
            assert client.get_status() == ClawMemStatus.UNAVAILABLE

    def test_cli_timeout_returns_error(self, client):
        """Lines 165-166: TimeoutExpired -> error."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 2)):
            result = client._write_cli("test", ["tag1"])
            assert result.success is False
            assert "timeout" in result.error.lower()

    def test_cli_generic_exception_returns_error(self, client):
        """Lines 167-168: generic Exception -> error."""
        with patch("subprocess.run", side_effect=RuntimeError("unknown error")):
            result = client._write_cli("test", ["tag1"])
            assert result.success is False
            assert "unknown error" in result.error

    def test_cli_success_returns_entry_id(self, client):
        """Lines 156-157: successful CLI call."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "entry-abc123\n"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = client._write_cli("test entry", ["tag1"])
            assert result.success is True
            assert result.entry_id == "entry-abc123"

    def test_cli_nonzero_exit_returns_error(self, client):
        """Lines 158-161: non-zero exit code."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error: something went wrong"
        with patch("subprocess.run", return_value=mock_result):
            result = client._write_cli("test entry", ["tag1"])
            assert result.success is False
            assert "CLI exit 1" in result.error


class TestClawMemPendingWrites:
    def test_unavailable_status_queues_write(self, client):
        """Write when UNAVAILABLE adds to pending."""
        client._status = ClawMemStatus.UNAVAILABLE
        result = client.write_blindspot("test blind spot")
        assert result.success is False
        pending = client.get_pending_writes()
        assert len(pending) == 1

    def test_mark_available_restores_status(self, client):
        """mark_available resets status."""
        client._status = ClawMemStatus.UNAVAILABLE
        client.mark_available()
        assert client.get_status() == ClawMemStatus.AVAILABLE

    def test_failed_write_degrades_status(self, client):
        """Failed write when AVAILABLE degrades to DEGRADED."""
        with patch.object(client, "_write_cli", return_value=ClawMemWriteResult(success=False, error="fail")):
            client._write("test", ["tag1"])
            assert client.get_status() == ClawMemStatus.DEGRADED
