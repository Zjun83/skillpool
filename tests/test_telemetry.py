"""Tests for skillpool.telemetry — TelemetryChannel, TelemetryEvent, TelemetryBridge."""

import json
import time
from pathlib import Path

import pytest

from skillpool.telemetry import TelemetryBridge, TelemetryChannel, TelemetryEvent


# ── TelemetryChannel ──────────────────────────────────────────────

class TestTelemetryChannel:
    """TelemetryChannel enum correctness."""

    def test_members(self):
        assert set(TelemetryChannel) == {
            TelemetryChannel.HOOK,
            TelemetryChannel.MCP,
            TelemetryChannel.LOG_FILE,
        }

    def test_values(self):
        assert TelemetryChannel.HOOK.value == "hook"
        assert TelemetryChannel.MCP.value == "mcp"
        assert TelemetryChannel.LOG_FILE.value == "log_file"

    def test_from_value(self):
        assert TelemetryChannel("hook") is TelemetryChannel.HOOK

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            TelemetryChannel("invalid")


# ── TelemetryEvent ────────────────────────────────────────────────

class TestTelemetryEvent:
    """TelemetryEvent Pydantic model validation."""

    def test_minimal_fields(self):
        ev = TelemetryEvent(
            event_type="gate_check",
            skill_id="skill-1",
            channel=TelemetryChannel.HOOK,
            payload={},
        )
        assert ev.event_type == "gate_check"
        assert ev.skill_id == "skill-1"
        assert ev.channel is TelemetryChannel.HOOK
        assert ev.payload == {}
        assert ev.trace_id == ""
        # timestamp auto-generated
        assert ev.timestamp is not None

    def test_all_fields(self):
        ev = TelemetryEvent(
            event_type="execution",
            skill_id="skill-2",
            channel=TelemetryChannel.MCP,
            payload={"key": "value"},
            timestamp="2025-01-01T00:00:00Z",
            trace_id="trace-abc",
        )
        assert ev.timestamp == "2025-01-01T00:00:00Z"
        assert ev.trace_id == "trace-abc"

    def test_payload_accepts_dict(self):
        ev = TelemetryEvent(
            event_type="t",
            skill_id="s",
            channel=TelemetryChannel.LOG_FILE,
            payload={"nested": {"deep": True}},
        )
        assert ev.payload["nested"]["deep"] is True

    # TelemetryEvent allows missing optional fields with defaults
    ev = TelemetryEvent(event_type="test", skill_id="S01")
    assert ev.channel == TelemetryChannel.LOG_FILE

    def test_model_dump(self):
        ev = TelemetryEvent(
            event_type="gate_check",
            skill_id="s1",
            channel=TelemetryChannel.HOOK,
            payload={"x": 1},
        )
        d = ev.model_dump()
        assert d["event_type"] == "gate_check"
        assert d["channel"] == TelemetryChannel.HOOK


# ── TelemetryBridge ───────────────────────────────────────────────

class TestTelemetryBridge:
    """TelemetryBridge emit / register_hook / read_events."""

    def test_init_creates_log_dir(self, tmp_path):
        log_dir = tmp_path / "telem"
        bridge = TelemetryBridge(log_dir=log_dir)
        assert log_dir.is_dir()

    def test_emit_returns_event(self, tmp_path):
        bridge = TelemetryBridge(log_dir=tmp_path)
        ev = bridge.emit(
            event_type="test_event",
            skill_id="skill-x",
            channel=TelemetryChannel.HOOK,
            payload={"foo": "bar"},
        )
        assert isinstance(ev, TelemetryEvent)
        assert ev.event_type == "test_event"
        assert ev.skill_id == "skill-x"

    def test_emit_writes_to_log_file(self, tmp_path):
        bridge = TelemetryBridge(log_dir=tmp_path)
        bridge.emit(
            event_type="log_test",
            skill_id="skill-y",
            channel=TelemetryChannel.LOG_FILE,
            payload={"n": 42},
        )
        log_files = list(tmp_path.glob("*.jsonl"))
        assert len(log_files) >= 1
        content = log_files[0].read_text().strip()
        lines = content.split("\n")
        assert len(lines) >= 1
        record = json.loads(lines[-1])
        assert record["event_type"] == "log_test"
        assert record["skill_id"] == "skill-y"

    def test_emit_multiple_events_append(self, tmp_path):
        bridge = TelemetryBridge(log_dir=tmp_path)
        for i in range(3):
            bridge.emit(
                event_type=f"event_{i}",
                skill_id=f"skill-{i}",
                channel=TelemetryChannel.MCP,
                payload={},
            )
        log_files = list(tmp_path.glob("*.jsonl"))
        lines = log_files[0].read_text().strip().split("\n")
        assert len(lines) == 3

    def test_register_hook_called_on_emit(self, tmp_path):
        bridge = TelemetryBridge(log_dir=tmp_path)
        received = []

        def hook(event: TelemetryEvent):
            received.append(event)

        bridge.register_hook(hook)
        bridge.emit(
            event_type="hooked",
            skill_id="skill-h",
            channel=TelemetryChannel.HOOK,
            payload={},
        )
        assert len(received) == 1
        assert received[0].event_type == "hooked"

    def test_register_multiple_hooks(self, tmp_path):
        bridge = TelemetryBridge(log_dir=tmp_path)
        calls_a, calls_b = [], []

        bridge.register_hook(lambda e: calls_a.append(e))
        bridge.register_hook(lambda e: calls_b.append(e))
        bridge.emit(
            event_type="multi_hook",
            skill_id="skill-mh",
            channel=TelemetryChannel.HOOK,
            payload={},
        )
        assert len(calls_a) == 1
        assert len(calls_b) == 1

    def test_read_events_returns_list(self, tmp_path):
        bridge = TelemetryBridge(log_dir=tmp_path)
        bridge.emit(
            event_type="read_test",
            skill_id="skill-r",
            channel=TelemetryChannel.LOG_FILE,
            payload={"val": 1},
        )
        events = bridge.read_events()
        assert isinstance(events, list)
        assert len(events) >= 1
        assert events[-1].event_type == "read_test"

    def test_read_events_empty_log(self, tmp_path):
        bridge = TelemetryBridge(log_dir=tmp_path)
        events = bridge.read_events()
        assert events == []

    def test_emit_with_trace_id(self, tmp_path):
        bridge = TelemetryBridge(log_dir=tmp_path)
        ev = bridge.emit(
            event_type="traced",
            skill_id="skill-t",
            channel=TelemetryChannel.MCP,
            payload={},
            trace_id="trace-123",
        )
        assert ev.trace_id == "trace-123"

    def test_emit_hook_exception_does_not_crash(self, tmp_path):
        """A failing hook must not prevent the event from being emitted."""
        bridge = TelemetryBridge(log_dir=tmp_path)

        def bad_hook(event):
            raise RuntimeError("hook failed")

        bridge.register_hook(bad_hook)
        # Should not raise
        ev = bridge.emit(
            event_type="resilient",
            skill_id="skill-res",
            channel=TelemetryChannel.HOOK,
            payload={},
        )
        assert ev.event_type == "resilient"
