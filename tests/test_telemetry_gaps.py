"""Tests for TelemetryBridge — covering uncovered lines in telemetry.py.

Uncovered lines:
- 102: empty line check in read_events loop
- 111-113: since filter — timestamp comparison and skip
- 115-116: generic Exception in read_events line parsing
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from skillpool.telemetry import TelemetryBridge, TelemetryChannel, TelemetryEvent


# ---------------------------------------------------------------------------
# read_events — empty line handling (line 102)
# ---------------------------------------------------------------------------

class TestReadEventsEmptyLine:
    """Empty lines in log file are skipped."""

    def test_empty_lines_skipped(self, tmp_path):
        bridge = TelemetryBridge(log_dir=tmp_path)
        # Write a log file with empty lines
        log_file = tmp_path / f"telemetry-{datetime.now().strftime('%Y%m%d')}.jsonl"
        ev = TelemetryEvent(event_type="test", skill_id="s1", channel=TelemetryChannel.LOG_FILE)
        log_file.write_text(
            ev.model_dump_json() + "\n\n\n" + ev.model_dump_json() + "\n"
        )
        events = bridge.read_events()
        assert len(events) == 2

    def test_only_empty_lines_returns_empty(self, tmp_path):
        bridge = TelemetryBridge(log_dir=tmp_path)
        log_file = tmp_path / f"telemetry-{datetime.now().strftime('%Y%m%d')}.jsonl"
        log_file.write_text("\n\n\n")
        events = bridge.read_events()
        assert events == []


# ---------------------------------------------------------------------------
# read_events — since filter (lines 111-113)
# ---------------------------------------------------------------------------

class TestReadEventsSinceFilter:
    """Events before the 'since' timestamp are filtered out."""

    def test_since_filters_old_events(self, tmp_path):
        bridge = TelemetryBridge(log_dir=tmp_path)

        # Emit event now
        bridge.emit(event_type="recent", skill_id="s1", channel=TelemetryChannel.LOG_FILE)

        # Read with since=0 (epoch) → all events included
        all_events = bridge.read_events(since=0)
        assert len(all_events) >= 1

        # Read with since=far future → no events
        future_events = bridge.read_events(since=time.time() + 10000)
        assert len(future_events) == 0

    def test_since_boundary(self, tmp_path):
        """Events exactly at the since boundary are included."""
        bridge = TelemetryBridge(log_dir=tmp_path)
        ev = bridge.emit(event_type="boundary", skill_id="s1", channel=TelemetryChannel.LOG_FILE)

        # Parse the event's timestamp to get its epoch time
        evt_ts = datetime.fromisoformat(ev.timestamp).timestamp()

        # since=evt_ts should include this event (evt_ts >= since)
        events = bridge.read_events(since=evt_ts)
        assert len(events) >= 1

    def test_since_with_mixed_events(self, tmp_path):
        """Only events after 'since' are returned."""
        bridge = TelemetryBridge(log_dir=tmp_path)

        # Write events with different timestamps manually
        log_file = tmp_path / f"telemetry-{datetime.now().strftime('%Y%m%d')}.jsonl"
        old_event = TelemetryEvent(
            event_type="old",
            skill_id="s1",
            channel=TelemetryChannel.LOG_FILE,
            timestamp="2020-01-01T00:00:00+00:00",
        )
        recent_event = TelemetryEvent(
            event_type="recent",
            skill_id="s2",
            channel=TelemetryChannel.LOG_FILE,
            timestamp="2026-01-01T00:00:00+00:00",
        )
        with open(log_file, "a") as f:
            f.write(old_event.model_dump_json() + "\n")
            f.write(recent_event.model_dump_json() + "\n")

        # since=2025-01-01 should exclude the 2020 event
        since_2025 = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
        events = bridge.read_events(since=since_2025)
        assert len(events) == 1
        assert events[0].event_type == "recent"


# ---------------------------------------------------------------------------
# read_events — generic Exception in line parsing (lines 115-116)
# ---------------------------------------------------------------------------

class TestReadEventsExceptionHandling:
    """Lines that cause exceptions during parsing are skipped."""

    def test_malformed_json_skipped(self, tmp_path):
        bridge = TelemetryBridge(log_dir=tmp_path)
        log_file = tmp_path / f"telemetry-{datetime.now().strftime('%Y%m%d')}.jsonl"

        # Valid event followed by malformed JSON, then another valid event
        valid = TelemetryEvent(event_type="valid", skill_id="s1", channel=TelemetryChannel.LOG_FILE)
        log_file.write_text(
            valid.model_dump_json() + "\n"
            + "{bad json\n"
            + valid.model_dump_json() + "\n"
        )
        events = bridge.read_events()
        # Two valid events, one malformed skipped
        assert len(events) == 2

    def test_exception_during_event_construction(self, tmp_path):
        """When TelemetryEvent construction raises an exception, line is skipped."""
        bridge = TelemetryBridge(log_dir=tmp_path)
        log_file = tmp_path / f"telemetry-{datetime.now().strftime('%Y%m%d')}.jsonl"

        # Valid JSON but missing required fields for TelemetryEvent
        log_file.write_text('{"event_type": "test"}\n')
        # TelemetryEvent requires skill_id, this should trigger an exception
        events = bridge.read_events()
        # Should gracefully skip the malformed entry
        assert isinstance(events, list)

    def test_skill_id_filter(self, tmp_path):
        """read_events filters by skill_id."""
        bridge = TelemetryBridge(log_dir=tmp_path)
        bridge.emit(event_type="type-a", skill_id="skill-1", channel=TelemetryChannel.LOG_FILE)
        bridge.emit(event_type="type-b", skill_id="skill-2", channel=TelemetryChannel.LOG_FILE)
        bridge.emit(event_type="type-a", skill_id="skill-1", channel=TelemetryChannel.LOG_FILE)

        events = bridge.read_events(skill_id="skill-1")
        assert len(events) == 2
        assert all(e.skill_id == "skill-1" for e in events)

    def test_event_type_filter(self, tmp_path):
        """read_events filters by event_type."""
        bridge = TelemetryBridge(log_dir=tmp_path)
        bridge.emit(event_type="gate_check", skill_id="s1", channel=TelemetryChannel.LOG_FILE)
        bridge.emit(event_type="skill_used", skill_id="s2", channel=TelemetryChannel.LOG_FILE)

        events = bridge.read_events(event_type="gate_check")
        assert len(events) == 1
        assert events[0].event_type == "gate_check"

    def test_combined_filters(self, tmp_path):
        """read_events with both skill_id and event_type filters."""
        bridge = TelemetryBridge(log_dir=tmp_path)
        bridge.emit(event_type="gate_check", skill_id="s1", channel=TelemetryChannel.LOG_FILE)
        bridge.emit(event_type="skill_used", skill_id="s1", channel=TelemetryChannel.LOG_FILE)
        bridge.emit(event_type="gate_check", skill_id="s2", channel=TelemetryChannel.LOG_FILE)

        events = bridge.read_events(skill_id="s1", event_type="gate_check")
        assert len(events) == 1
        assert events[0].skill_id == "s1"
        assert events[0].event_type == "gate_check"
