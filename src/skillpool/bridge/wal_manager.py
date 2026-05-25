"""SkillPool WAL Manager — Write-Ahead Log for atomic registry operations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, model_validator


class WALEntryType(str, Enum):
    """Types of WAL operations."""

    REGISTER = "register"
    UPDATE = "update"
    DELETE = "delete"
    CHECKPOINT = "checkpoint"


class WALEntry(BaseModel):
    """A single WAL entry."""

    entry_type: WALEntryType
    skill_name: str
    data: dict[str, Any] = {}
    timestamp: str = ""
    txn_id: str = ""

    @model_validator(mode="after")
    def _set_timestamp(self) -> WALEntry:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        return self


class WALManager:
    """Write-Ahead Log manager for atomic registry operations.

    Ensures crash-recovery by logging all mutations before applying them.
    On startup, replays any uncommitted entries to restore consistency.
    """

    def __init__(self, wal_dir: Path) -> None:
        self._wal_dir = wal_dir
        self._wal_file = wal_dir / "wal.jsonl"
        self._checkpoint_file = wal_dir / "checkpoint.json"
        self._wal_dir.mkdir(parents=True, exist_ok=True)
        self._txn_counter = 0

    def _next_txn_id(self) -> str:
        self._txn_counter += 1
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"txn-{ts}-{self._txn_counter:04d}"

    def append(
        self, entry_type: WALEntryType, skill_name: str, data: dict[str, Any] | None = None
    ) -> WALEntry:
        """Append a new WAL entry."""
        entry = WALEntry(
            entry_type=entry_type,
            skill_name=skill_name,
            data=data or {},
            txn_id=self._next_txn_id(),
        )
        with open(self._wal_file, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")
        return entry

    def read_uncommitted(self) -> list[WALEntry]:
        """Read WAL entries since last checkpoint."""
        checkpoint_ts = self._load_checkpoint_timestamp()
        entries: list[WALEntry] = []
        if not self._wal_file.exists():
            return entries
        with open(self._wal_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = WALEntry(**json.loads(line))
                    if checkpoint_ts and entry.timestamp <= checkpoint_ts:
                        continue
                    entries.append(entry)
                except (json.JSONDecodeError, Exception):
                    continue
        return entries

    def checkpoint(self) -> str:
        """Create a checkpoint marking all current WAL entries as committed."""
        ts = datetime.now(timezone.utc).isoformat()
        self._checkpoint_file.write_text(
            json.dumps({"timestamp": ts, "entries": len(self.read_uncommitted())}),
            encoding="utf-8",
        )
        self._wal_file.write_text("", encoding="utf-8")
        return ts

    def _load_checkpoint_timestamp(self) -> str | None:
        """Load the last checkpoint timestamp."""
        if not self._checkpoint_file.exists():
            return None
        try:
            data = json.loads(self._checkpoint_file.read_text(encoding="utf-8"))
            return data.get("timestamp")
        except (json.JSONDecodeError, Exception):
            return None

    def recover(self) -> list[WALEntry]:
        """Recover uncommitted entries after a crash."""
        return self.read_uncommitted()

    def get_stats(self) -> dict[str, Any]:
        """Get WAL statistics."""
        uncommitted = self.read_uncommitted()
        checkpoint_ts = self._load_checkpoint_timestamp()
        wal_size = self._wal_file.stat().st_size if self._wal_file.exists() else 0
        return {
            "uncommitted_count": len(uncommitted),
            "last_checkpoint": checkpoint_ts,
            "wal_file_size_bytes": wal_size,
            "wal_file_path": str(self._wal_file),
        }

    def compact(self) -> int:
        """Compact the WAL by removing committed entries."""
        uncommitted = self.read_uncommitted()
        if not self._wal_file.exists():
            return 0
        with open(self._wal_file, encoding="utf-8") as f:
            total = sum(1 for line in f if line.strip())
        with open(self._wal_file, "w", encoding="utf-8") as f:
            for entry in uncommitted:
                f.write(entry.model_dump_json() + "\n")
        return total - len(uncommitted)
