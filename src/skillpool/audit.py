"""SkillPool Audit — Structured audit logging for skill operations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AuditEventType(str, Enum):
    """Types of auditable events."""

    REGISTER = "register"
    UPDATE = "update"
    DELETE = "delete"
    GATE_PASS = "gate_pass"
    GATE_FAIL = "gate_fail"
    GATE_OVERRIDE = "gate_override"
    MATERIALIZATION_START = "materialization_start"
    MATERIALIZATION_COMPLETE = "materialization_complete"
    MATERIALIZATION_ROLLBACK = "materialization_rollback"
    QUALITY_PROFILE = "quality_profile"
    ERROR = "error"


class AuditEntry(BaseModel):
    """A single audit log entry."""

    timestamp: str = ""
    event_type: AuditEventType
    skill_name: str
    actor: str = "system"
    details: dict[str, Any] = Field(default_factory=dict)
    session_id: str = ""
    correlation_id: str = ""

    @model_validator(mode="after")
    def _set_timestamp(self) -> AuditEntry:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        return self


class AuditLog:
    """Structured audit logger for skill operations."""

    def __init__(self, log_dir: Path, session_id: str = "") -> None:
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._session_id = session_id
        self._log_path = self._log_dir / "audit.jsonl"

    def _write_entry(self, entry: AuditEntry) -> None:
        with open(self._log_path, "a") as f:
            f.write(entry.model_dump_json() + "\n")

    def log(
        self,
        event_type: AuditEventType,
        skill_name: str,
        actor: str = "system",
        details: dict[str, Any] | None = None,
        correlation_id: str = "",
    ) -> AuditEntry:
        entry = AuditEntry(
            event_type=event_type,
            skill_name=skill_name,
            actor=actor,
            details=details or {},
            session_id=self._session_id,
            correlation_id=correlation_id,
        )
        self._write_entry(entry)
        return entry

    def query(
        self,
        skill_name: str | None = None,
        event_type: AuditEventType | None = None,
        actor: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        entries: list[AuditEntry] = []
        if not self._log_path.exists():
            return entries

        with open(self._log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = AuditEntry(**data)
                    if skill_name and entry.skill_name != skill_name:
                        continue
                    if event_type and entry.event_type != event_type:
                        continue
                    if actor and entry.actor != actor:
                        continue
                    entries.append(entry)
                except (json.JSONDecodeError, Exception):
                    continue

        entries.reverse()
        return entries[:limit]

    def count(self) -> int:
        if not self._log_path.exists():
            return 0
        count = 0
        with open(self._log_path) as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
