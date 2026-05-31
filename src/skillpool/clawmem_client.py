"""ClawMem integration — dual-write for blind spots, upgrades, and audit events.

Provides ClawMemClient that wraps the ClawMem diary_write API (CLI or HTTP).
When ClawMem is unavailable, writes are silently skipped (graceful degradation).

Usage:
    client = ClawMemClient()
    client.write_blindspot("D3 score below 7.0", dimension="D3", severity="P1")
    client.write_upgrade("S09 MINOR upgrade", upgrade_type="MINOR")
    client.write_audit("cost_record accepted", trace_id="abc123")
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional

logger = logging.getLogger(__name__)


class ClawMemStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


@dataclass
class ClawMemWriteResult:
    """Result of a ClawMem write attempt."""
    success: bool
    entry_id: str = ""
    error: str = ""


class ClawMemClient:
    """Client for ClawMem diary_write integration.

    Supports two transport modes:
    - CLI: calls `clawmem diary write` subprocess
    - HTTP: calls ClawMem HTTP API on port 7438 (preferred when available)

    When ClawMem is unavailable, writes are silently skipped.
    """

    def __init__(
        self,
        http_url: str = "http://127.0.0.1:7438",
        use_http: bool = True,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._http_url = http_url
        self._use_http = use_http
        self._timeout = timeout_seconds
        self._status = ClawMemStatus.AVAILABLE
        self._pending_writes: list[dict] = []

    def write_blindspot(
        self,
        description: str,
        dimension: str = "",
        severity: str = "P2",
        skill_id: str = "",
    ) -> ClawMemWriteResult:
        """Write a blind spot to ClawMem with appropriate tags."""
        tags = ["blindspot-report", severity.lower()]
        if dimension:
            tags.append(dimension)
        if skill_id:
            tags.append(skill_id)
        return self._write(description, tags)

    def write_upgrade(
        self,
        description: str,
        upgrade_type: str = "PATCH",
        skill_id: str = "",
    ) -> ClawMemWriteResult:
        """Write an upgrade event to ClawMem."""
        tags = ["skill-upgrade", upgrade_type.lower()]
        if skill_id:
            tags.append(skill_id)
        return self._write(description, tags)

    def write_audit(
        self,
        description: str,
        trace_id: str = "",
    ) -> ClawMemWriteResult:
        """Write an audit event to ClawMem."""
        tags = ["audit-event"]
        if trace_id:
            tags.append(f"trace:{trace_id[:8]}")
        return self._write(description, tags)

    def get_status(self) -> ClawMemStatus:
        """Get current ClawMem availability status."""
        return self._status

    def get_pending_writes(self) -> list[dict]:
        """Get writes that failed and are pending retry."""
        return list(self._pending_writes)

    def _write(self, entry: str, tags: list[str]) -> ClawMemWriteResult:
        """Write an entry to ClawMem diary."""
        if self._status == ClawMemStatus.UNAVAILABLE:
            self._pending_writes.append({"entry": entry, "tags": tags})
            return ClawMemWriteResult(success=False, error="ClawMem unavailable")

        if self._use_http:
            result = self._write_http(entry, tags)
        else:
            result = self._write_cli(entry, tags)

        if not result.success:
            self._pending_writes.append({"entry": entry, "tags": tags})
            if self._status == ClawMemStatus.AVAILABLE:
                self._status = ClawMemStatus.DEGRADED

        return result

    def _write_http(self, entry: str, tags: list[str]) -> ClawMemWriteResult:
        """Write via ClawMem HTTP API."""
        try:
            import urllib.request
            url = f"{self._http_url}/diary/write"
            data = json.dumps({"entry": entry, "tags": tags}).encode()
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read())
                    return ClawMemWriteResult(
                        success=True,
                        entry_id=body.get("entry_id", ""),
                    )
                return ClawMemWriteResult(success=False, error=f"HTTP {resp.status}")
        except Exception as e:
            return ClawMemWriteResult(success=False, error=str(e))

    def _write_cli(self, entry: str, tags: list[str]) -> ClawMemWriteResult:
        """Write via ClawMem CLI subprocess."""
        try:
            cmd = ["clawmem", "diary", "write", entry]
            for tag in tags:
                cmd.extend(["-t", tag])
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            if result.returncode == 0:
                return ClawMemWriteResult(success=True, entry_id=result.stdout.strip())
            return ClawMemWriteResult(
                success=False,
                error=f"CLI exit {result.returncode}: {result.stderr.strip()}",
            )
        except FileNotFoundError:
            self._status = ClawMemStatus.UNAVAILABLE
            return ClawMemWriteResult(success=False, error="clawmem CLI not found")
        except subprocess.TimeoutExpired:
            return ClawMemWriteResult(success=False, error="CLI timeout")
        except Exception as e:
            return ClawMemWriteResult(success=False, error=str(e))

    def mark_available(self) -> None:
        """Mark ClawMem as available (e.g., after recovery)."""
        self._status = ClawMemStatus.AVAILABLE
