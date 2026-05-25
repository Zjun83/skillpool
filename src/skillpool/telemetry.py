"""SkillPool Telemetry — Structured event logging for audit trails."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


class EventType(str, Enum):
    """Types of telemetry events."""

    SKILL_REGISTERED = "skill.registered"
    SKILL_UPDATED = "skill.updated"
    SKILL_DELETED = "skill.deleted"
    GATE_CHECKED = "gate.checked"
    GATE_OVERRIDE = "gate.override"
    MATERIALIZE_STARTED = "materialize.started"
    MATERIALIZE_COMPLETED = "materialize.completed"
    MATERIALIZE_FAILED = "materialize.failed"
    ERROR = "system.error"


class TelemetryEvent(BaseModel):
    """A single telemetry event."""

    event_type: EventType
    skill_name: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = ""
    session_id: str = ""

    @model_validator(mode="after")
    def _set_timestamp(self) -> TelemetryEvent:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        return self


class TelemetryLogger:
    """Structured telemetry logger that writes JSONL event logs.

    Each event is written as a single JSON line to the log file,
    providing a complete audit trail of all skillpool operations.
    """

    def __init__(self, log_dir: Path, session_id: str = "") -> None:
        self._log_dir = log_dir
        self._session_id = session_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self._log_dir.mkdir(parents=True, exist_ok=True)

    @property
    def log_path(self) -> Path:
        """Return the current log file path."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._log_dir / f"telemetry-{date_str}.jsonl"

    def _write_event(self, event: TelemetryEvent) -> None:
        """Append an event to the log file."""
        if not event.session_id:
            event.session_id = self._session_id
        with open(self.log_path, "a") as f:
            f.write(event.model_dump_json() + "\n")

    def log_registered(self, skill_name: str, quality_score: float = 0.0, **kwargs: Any) -> None:
        """Log a skill registration event."""
        self._write_event(
            TelemetryEvent(
                event_type=EventType.SKILL_REGISTERED,
                skill_name=skill_name,
                payload={"quality_score": quality_score, **kwargs},
            )
        )

    def log_updated(self, skill_name: str, changes: dict[str, Any], **kwargs: Any) -> None:
        """Log a skill update event."""
        self._write_event(
            TelemetryEvent(
                event_type=EventType.SKILL_UPDATED,
                skill_name=skill_name,
                payload={"changes": changes, **kwargs},
            )
        )

    def log_deleted(self, skill_name: str, **kwargs: Any) -> None:
        """Log a skill deletion event."""
        self._write_event(
            TelemetryEvent(
                event_type=EventType.SKILL_DELETED,
                skill_name=skill_name,
                payload={**kwargs},
            )
        )

    def log_gate_check(self, skill_name: str, status: str, score: float, **kwargs: Any) -> None:
        """Log a gate check event."""
        event_type = EventType.GATE_OVERRIDE if status == "override" else EventType.GATE_CHECKED
        self._write_event(
            TelemetryEvent(
                event_type=event_type,
                skill_name=skill_name,
                payload={"status": status, "score": score, **kwargs},
            )
        )

    def log_materialize(self, skill_name: str, status: str, **kwargs: Any) -> None:
        """Log a materialization event."""
        type_map = {
            "started": EventType.MATERIALIZE_STARTED,
            "completed": EventType.MATERIALIZE_COMPLETED,
            "failed": EventType.MATERIALIZE_FAILED,
        }
        event_type = type_map.get(status, EventType.MATERIALIZE_FAILED)
        self._write_event(
            TelemetryEvent(
                event_type=event_type,
                skill_name=skill_name,
                payload={"status": status, **kwargs},
            )
        )

    def log_error(self, message: str, **kwargs: Any) -> None:
        """Log an error event."""
        self._write_event(
            TelemetryEvent(
                event_type=EventType.ERROR,
                payload={"message": message, **kwargs},
            )
        )

    def read_events(
        self,
        event_type: EventType | None = None,
        skill_name: str | None = None,
        limit: int = 100,
    ) -> list[TelemetryEvent]:
        """Read events from the log with optional filtering."""
        events: list[TelemetryEvent] = []
        if not self.log_path.exists():
            return events
        with open(self.log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = TelemetryEvent(**json.loads(line))
                    if event_type and event.event_type != event_type:
                        continue
                    if skill_name and event.skill_name != skill_name:
                        continue
                    events.append(event)
                except (json.JSONDecodeError, Exception):
                    continue
        return events[-limit:]
