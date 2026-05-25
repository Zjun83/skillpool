"""Unit tests for SkillPool telemetry module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillpool.telemetry import EventType, TelemetryEvent, TelemetryLogger


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    """Return a temporary log directory."""
    d = tmp_path / "telemetry_logs"
    d.mkdir()
    return d


@pytest.fixture
def logger(log_dir: Path) -> TelemetryLogger:
    """Return a TelemetryLogger instance."""
    return TelemetryLogger(log_dir, session_id="test-session")


class TestTelemetryEvent:
    """Tests for TelemetryEvent model."""

    def test_event_creation(self) -> None:
        event = TelemetryEvent(
            event_type=EventType.SKILL_REGISTERED,
            skill_name="my-skill",
        )
        assert event.event_type == EventType.SKILL_REGISTERED
        assert event.skill_name == "my-skill"
        assert event.timestamp  # auto-generated
        assert event.payload == {}

    def test_event_with_payload(self) -> None:
        event = TelemetryEvent(
            event_type=EventType.GATE_CHECKED,
            skill_name="my-skill",
            payload={"status": "pass", "score": 0.95},
        )
        assert event.payload["status"] == "pass"
        assert event.payload["score"] == 0.95

    def test_event_serialization(self) -> None:
        event = TelemetryEvent(
            event_type=EventType.SKILL_DELETED,
            skill_name="old-skill",
            session_id="sess-1",
        )
        data = json.loads(event.model_dump_json())
        assert data["event_type"] == "skill.deleted"
        assert data["skill_name"] == "old-skill"


class TestTelemetryLogger:
    """Tests for TelemetryLogger."""

    def test_log_registered(self, logger: TelemetryLogger, log_dir: Path) -> None:
        logger.log_registered("my-skill", quality_score=0.9)
        events = logger.read_events()
        assert len(events) == 1
        assert events[0].event_type == EventType.SKILL_REGISTERED
        assert events[0].skill_name == "my-skill"
        assert events[0].payload["quality_score"] == 0.9

    def test_log_updated(self, logger: TelemetryLogger) -> None:
        logger.log_updated("my-skill", changes={"version": "2.0"})
        events = logger.read_events()
        assert len(events) == 1
        assert events[0].event_type == EventType.SKILL_UPDATED
        assert events[0].payload["changes"]["version"] == "2.0"

    def test_log_deleted(self, logger: TelemetryLogger) -> None:
        logger.log_deleted("old-skill")
        events = logger.read_events()
        assert len(events) == 1
        assert events[0].event_type == EventType.SKILL_DELETED

    def test_log_gate_check_pass(self, logger: TelemetryLogger) -> None:
        logger.log_gate_check("my-skill", status="pass", score=0.95)
        events = logger.read_events()
        assert events[0].event_type == EventType.GATE_CHECKED
        assert events[0].payload["status"] == "pass"

    def test_log_gate_check_override(self, logger: TelemetryLogger) -> None:
        logger.log_gate_check("my-skill", status="override", score=0.5)
        events = logger.read_events()
        assert events[0].event_type == EventType.GATE_OVERRIDE

    def test_log_materialize_started(self, logger: TelemetryLogger) -> None:
        logger.log_materialize("my-skill", status="started")
        events = logger.read_events()
        assert events[0].event_type == EventType.MATERIALIZE_STARTED

    def test_log_materialize_completed(self, logger: TelemetryLogger) -> None:
        logger.log_materialize("my-skill", status="completed")
        events = logger.read_events()
        assert events[0].event_type == EventType.MATERIALIZE_COMPLETED

    def test_log_materialize_failed(self, logger: TelemetryLogger) -> None:
        logger.log_materialize("my-skill", status="failed")
        events = logger.read_events()
        assert events[0].event_type == EventType.MATERIALIZE_FAILED

    def test_log_error(self, logger: TelemetryLogger) -> None:
        logger.log_error("Something went wrong")
        events = logger.read_events()
        assert events[0].event_type == EventType.ERROR
        assert events[0].payload["message"] == "Something went wrong"

    def test_read_events_filter_by_type(self, logger: TelemetryLogger) -> None:
        logger.log_registered("skill-a")
        logger.log_registered("skill-b")
        logger.log_deleted("skill-c")
        events = logger.read_events(event_type=EventType.SKILL_REGISTERED)
        assert len(events) == 2

    def test_read_events_filter_by_skill(self, logger: TelemetryLogger) -> None:
        logger.log_registered("skill-a")
        logger.log_registered("skill-b")
        events = logger.read_events(skill_name="skill-a")
        assert len(events) == 1
        assert events[0].skill_name == "skill-a"

    def test_read_events_empty(self, logger: TelemetryLogger) -> None:
        events = logger.read_events()
        assert events == []

    def test_session_id_propagation(self, logger: TelemetryLogger) -> None:
        logger.log_registered("my-skill")
        events = logger.read_events()
        assert events[0].session_id == "test-session"

    def test_log_path_property(self, log_dir: Path) -> None:
        logger = TelemetryLogger(log_dir, session_id="s1")
        assert "telemetry-" in str(logger.log_path)
        assert logger.log_path.suffix == ".jsonl"
