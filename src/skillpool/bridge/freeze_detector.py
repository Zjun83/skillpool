"""SkillPool Freeze Detector — Detect and recover from frozen/stalled operations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, model_validator


class FreezeStatus(str, Enum):
    """Status of a freeze check."""

    HEALTHY = "healthy"
    FROZEN = "frozen"
    STALE = "stale"
    RECOVERING = "recovering"


class FreezeReport(BaseModel):
    """Report from a freeze detection check."""

    status: FreezeStatus
    frozen_operations: list[str] = []
    stale_threshold_seconds: int = 300
    last_heartbeat: str = ""
    timestamp: str = ""

    @model_validator(mode="after")
    def _set_timestamp(self) -> FreezeReport:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        return self


class FreezeDetector:
    """Detect and recover from frozen/stalled operations.

    Monitors heartbeat files to detect operations that have stalled
    beyond a configurable threshold. Provides recovery actions.
    """

    def __init__(self, state_dir: Path, stale_threshold: int = 300) -> None:
        self._state_dir = state_dir / "freeze_state"
        self._heartbeats_dir = self._state_dir / "heartbeats"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._heartbeats_dir.mkdir(parents=True, exist_ok=True)
        self._stale_threshold = stale_threshold

    def heartbeat(self, operation_id: str) -> None:
        """Record a heartbeat for an ongoing operation."""
        hb_file = self._heartbeats_dir / f"{operation_id}.json"
        data = {
            "operation_id": operation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        hb_file.write_text(json.dumps(data), encoding="utf-8")

    def complete_operation(self, operation_id: str) -> None:
        """Mark an operation as completed (remove heartbeat)."""
        hb_file = self._heartbeats_dir / f"{operation_id}.json"
        if hb_file.exists():
            hb_file.unlink()

    def check(self) -> FreezeReport:
        """Check for frozen/stalled operations."""
        frozen_ops: list[str] = []
        now = datetime.now(timezone.utc)
        last_hb = ""

        for hb_file in self._heartbeats_dir.iterdir():
            if not hb_file.suffix == ".json":
                continue
            try:
                data = json.loads(hb_file.read_text(encoding="utf-8"))
                ts_str = data.get("timestamp", "")
                if ts_str:
                    last_hb = ts_str
                    ts = datetime.fromisoformat(ts_str)
                    age = (now - ts).total_seconds()
                    if age > self._stale_threshold:
                        frozen_ops.append(data.get("operation_id", hb_file.stem))
            except (json.JSONDecodeError, Exception):
                frozen_ops.append(hb_file.stem)

        if frozen_ops:
            return FreezeReport(
                status=FreezeStatus.FROZEN,
                frozen_operations=frozen_ops,
                stale_threshold_seconds=self._stale_threshold,
                last_heartbeat=last_hb,
            )

        return FreezeReport(
            status=FreezeStatus.HEALTHY,
            stale_threshold_seconds=self._stale_threshold,
            last_heartbeat=last_hb,
        )

    def recover(self, operation_id: str) -> bool:
        """Attempt to recover a frozen operation.

        Removes the heartbeat file and returns True if recovery was possible.
        """
        hb_file = self._heartbeats_dir / f"{operation_id}.json"
        if hb_file.exists():
            hb_file.unlink()
            return True
        return False

    def recover_all(self) -> list[str]:
        """Recover all frozen operations."""
        recovered: list[str] = []
        for hb_file in list(self._heartbeats_dir.iterdir()):
            if hb_file.suffix == ".json":
                recovered.append(hb_file.stem)
                hb_file.unlink()
        return recovered

    def list_active_operations(self) -> list[dict[str, Any]]:
        """List all active (heartbeat-present) operations."""
        ops: list[dict[str, Any]] = []
        for hb_file in self._heartbeats_dir.iterdir():
            if hb_file.suffix != ".json":
                continue
            try:
                data = json.loads(hb_file.read_text(encoding="utf-8"))
                ops.append(data)
            except (json.JSONDecodeError, Exception):
                ops.append({"operation_id": hb_file.stem, "timestamp": "unknown"})
        return ops
