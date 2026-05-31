"""Tests for ClawMemClient — ClawMem integration for dual-write."""
from __future__ import annotations

import pytest

from skillpool.clawmem_client import ClawMemClient, ClawMemStatus, ClawMemWriteResult


class TestClawMemClientBasic:
    def test_starts_available(self) -> None:
        client = ClawMemClient(use_http=False)
        assert client.get_status() == ClawMemStatus.AVAILABLE

    def test_write_blindspot_graceful_degradation(self) -> None:
        """When ClawMem CLI is not installed, write should gracefully fail."""
        client = ClawMemClient(use_http=False)
        result = client.write_blindspot(
            "D3 score below 7.0",
            dimension="D3",
            severity="P1",
        )
        # In test env, clawmem CLI likely not installed → should degrade
        assert isinstance(result, ClawMemWriteResult)
        # Either success (if clawmem is installed) or failure with pending
        if not result.success:
            assert len(client.get_pending_writes()) > 0

    def test_write_upgrade_graceful_degradation(self) -> None:
        client = ClawMemClient(use_http=False)
        result = client.write_upgrade("S09 MINOR upgrade", upgrade_type="MINOR")
        assert isinstance(result, ClawMemWriteResult)

    def test_write_audit_graceful_degradation(self) -> None:
        client = ClawMemClient(use_http=False)
        result = client.write_audit("cost_record accepted", trace_id="abc123")
        assert isinstance(result, ClawMemWriteResult)

    def test_unavailable_skips_writes(self) -> None:
        """After marking unavailable, writes should be skipped."""
        client = ClawMemClient(use_http=False)
        # Simulate unavailable state
        client._status = ClawMemStatus.UNAVAILABLE
        result = client.write_blindspot("test")
        assert not result.success
        assert result.error == "ClawMem unavailable"
        # Pending writes should accumulate
        assert len(client.get_pending_writes()) == 1

    def test_mark_available(self) -> None:
        client = ClawMemClient(use_http=False)
        client._status = ClawMemStatus.UNAVAILABLE
        client.mark_available()
        assert client.get_status() == ClawMemStatus.AVAILABLE

    def test_http_write_timeout(self) -> None:
        """HTTP write to non-existent server should fail gracefully."""
        client = ClawMemClient(http_url="http://127.0.0.1:19999", use_http=True, timeout_seconds=0.5)
        result = client.write_blindspot("test")
        assert not result.success
        assert "error" in result.error.lower() or "refused" in result.error.lower() or "timed" in result.error.lower() or "connect" in result.error.lower()

    def test_pending_writes_accumulate(self) -> None:
        client = ClawMemClient(use_http=False)
        client._status = ClawMemStatus.UNAVAILABLE
        client.write_blindspot("first")
        client.write_blindspot("second")
        assert len(client.get_pending_writes()) == 2

    def test_pending_writes_are_dicts(self) -> None:
        client = ClawMemClient(use_http=False)
        client._status = ClawMemStatus.UNAVAILABLE
        client.write_blindspot("test", dimension="D3", severity="P1")
        pending = client.get_pending_writes()
        assert pending[0]["entry"] == "test"
        assert "blindspot-report" in pending[0]["tags"]
        assert "p1" in pending[0]["tags"]
        assert "D3" in pending[0]["tags"]