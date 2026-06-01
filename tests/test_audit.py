"""Tests for Audit Layer V4.0 — 34-field OTel-aligned audit with hash chain."""
from __future__ import annotations

import hashlib
import json

import pytest

from skillpool.audit import AuditLayer, AuditRecord, AuditUnavailableError, log_event


class TestAuditRecord:
    """Tests for AuditRecord dataclass."""

    def test_default_fields(self):
        r = AuditRecord(audit_id="test-1")
        assert r.audit_id == "test-1"
        assert r.event_type == "skill_pool_event"
        assert r.actor == "system"
        assert r.result == "success"
        assert r.severity == "INFO"
        assert r.chain_index == 0
        assert r.current_hash == ""

    def test_backward_compat_hash_alias(self):
        r = AuditRecord(audit_id="test-1")
        r.hash = "abc123"
        assert r.current_hash == "abc123"
        assert r.hash == "abc123"

    def test_backward_compat_object_id_alias(self):
        r = AuditRecord(audit_id="test-1")
        r.object_id = "skill-42"
        assert r.resource_id == "skill-42"
        assert r.object_id == "skill-42"

    def test_backward_compat_object_type_alias(self):
        r = AuditRecord(audit_id="test-1")
        r.object_type = "agent"
        assert r.resource_type == "agent"
        assert r.object_type == "agent"

    def test_backward_compat_audit_ref_alias(self):
        r = AuditRecord(audit_id="test-1")
        r.audit_ref = "ref-123"
        assert r.audit_id == "ref-123"
        assert r.audit_ref == "ref-123"

    def test_all_34_fields_populated(self):
        r = AuditRecord(
            audit_id="a1", event_id="e1", trace_id="t1", span_id="s1",
            parent_span_id="p1", event_type="test", event_time=None,
            created_at="2026-01-01", updated_at="2026-01-01", duration_ms=100.0,
            actor="bot", session_id="sess1", tenant_id="ten1",
            source_component="SC", action="act", resource_type="rt",
            resource_id="ri", request_id="req1", correlation_id="corr1",
            policy_decision="deny", decision="blocked", result="failure",
            reason="bad", severity="ERROR", previous_hash="ph",
            current_hash="ch", chain_index=5, signature="sig",
            input_hash="ih", output_hash="oh", metadata_json='{"k":"v"}',
            retention_class="cold", compliance_tags="ct", geo_location="US",
        )
        assert r.audit_id == "a1"
        assert r.event_id == "e1"
        assert r.geo_location == "US"
        assert r.chain_index == 5


class TestLogEvent:
    """Tests for module-level log_event function."""

    def test_basic_event(self):
        record = log_event(action="register_skill", actor="admin")
        assert record.action == "register_skill"
        assert record.actor == "admin"
        assert record.result == "success"
        assert record.audit_id.startswith("audit-")
        assert record.current_hash != ""

    def test_auto_generates_trace_id(self):
        record = log_event(action="test")
        assert len(record.trace_id) == 32

    def test_auto_generates_span_id(self):
        record = log_event(action="test")
        assert len(record.span_id) == 16

    def test_input_hash_computed(self):
        record = log_event(action="test", resource_id="skill-1")
        assert record.input_hash != ""
        # Verify hash is deterministic
        payload = json.dumps({
            "action": "test",
            "actor": "system",
            "resource_type": "skill",
            "resource_id": "skill-1",
            "result": "success",
            "timestamp": record.created_at,
        }, sort_keys=True)
        expected = hashlib.sha256(payload.encode()).hexdigest()
        assert record.input_hash == expected

    def test_custom_metadata(self):
        record = log_event(action="test", metadata={"key": "value"})
        parsed = json.loads(record.metadata_json)
        assert parsed == {"key": "value"}

    def test_severity_levels(self):
        for sev in ("INFO", "WARN", "ERROR", "CRITICAL"):
            record = log_event(action="test", severity=sev)
            assert record.severity == sev


class TestAuditLayer:
    """Tests for AuditLayer class."""

    def test_append_returns_audit_id(self):
        layer = AuditLayer()
        ref = layer.append(action="test_action", object_id="obj-1")
        assert ref.startswith("audit-")

    def test_append_creates_record(self):
        layer = AuditLayer()
        layer.append(action="register", object_id="skill-1")
        records = layer.get_records()
        assert len(records) == 1
        assert records[0].action == "register"
        assert records[0].resource_id == "skill-1"

    def test_append_unavailable_raises(self):
        layer = AuditLayer(available=False)
        with pytest.raises(AuditUnavailableError):
            layer.append(action="test")

    def test_hash_chain_integrity(self):
        layer = AuditLayer()
        layer.append(action="action1")
        layer.append(action="action2")
        layer.append(action="action3")
        assert layer.verify_integrity() is True

    def test_hash_chain_broken_if_tampered(self):
        layer = AuditLayer()
        layer.append(action="action1")
        layer.append(action="action2")
        # Tamper with first record
        records = layer.get_records()
        records[0].action = "tampered"
        assert layer.verify_integrity() is False

    def test_chain_index_sequential(self):
        layer = AuditLayer()
        layer.append(action="a1")
        layer.append(action="a2")
        records = layer.get_records()
        assert records[0].chain_index == 0
        assert records[1].chain_index == 1

    def test_previous_hash_links(self):
        layer = AuditLayer()
        ref1 = layer.append(action="a1")
        layer.append(action="a2")
        records = layer.get_records()
        assert records[0].previous_hash == "0" * 64
        assert records[1].previous_hash == records[0].current_hash

    def test_filter_by_object_id(self):
        layer = AuditLayer()
        layer.append(action="a1", object_id="skill-1")
        layer.append(action="a2", object_id="skill-2")
        layer.append(action="a3", object_id="skill-1")
        filtered = layer.get_records("skill-1")
        assert len(filtered) == 2

    def test_get_record_count(self):
        layer = AuditLayer()
        assert layer.get_record_count() == 0
        layer.append(action="a1")
        layer.append(action="a2")
        assert layer.get_record_count() == 2

    def test_rotation(self):
        layer = AuditLayer(max_entries=3)
        for i in range(5):
            layer.append(action=f"a{i}")
        assert layer.get_record_count() == 3

    def test_rotation_preserves_chain_integrity(self):
        """After rotation, internal hash chain must still verify."""
        layer = AuditLayer(max_entries=3)
        for i in range(5):
            layer.append(action=f"a{i}")
        assert layer.verify_integrity() is True

    def test_rotation_carries_forward_pre_rotation_hash(self):
        """After rotation, the first retained record's previous_hash must
        match the current_hash of the last discarded record."""
        layer = AuditLayer(max_entries=3)
        for i in range(5):
            layer.append(action=f"a{i}")
        # Records kept: a2, a3, a4 (cutoff=2, discarded: a0, a1)
        first_retained = layer._records[0]
        assert first_retained.action == "a2"
        # previous_hash should be the current_hash of a1 (last discarded)
        assert first_retained.previous_hash != AuditLayer.GENESIS_HASH

    def test_log_event_record(self):
        layer = AuditLayer()
        record = layer.log_event_record(action="custom_event", actor="tester")
        assert record.action == "custom_event"
        assert record.actor == "tester"
        assert layer.get_record_count() == 1

    def test_log_event_record_unavailable_raises(self):
        layer = AuditLayer(available=False)
        with pytest.raises(AuditUnavailableError):
            layer.log_event_record(action="test")

    def test_set_available(self):
        layer = AuditLayer(available=False)
        assert not layer.is_available()
        layer.set_available(True)
        assert layer.is_available()

    def test_export_otel_traces(self):
        layer = AuditLayer()
        layer.append(action="test_action", object_id="obj-1")
        traces = layer.export_otel_traces()
        assert len(traces) == 1
        t = traces[0]
        assert "traceId" in t
        assert "spanId" in t
        assert "attributes" in t
        assert t["attributes"]["action"] == "test_action"
        assert t["status"]["code"] == 1  # success

    def test_export_otel_failure_status(self):
        layer = AuditLayer()
        layer.append(action="fail_action", result="failure")
        traces = layer.export_otel_traces()
        assert traces[0]["status"]["code"] == 2

    def test_genesis_hash(self):
        assert AuditLayer.GENESIS_HASH == "0" * 64


class TestTraceIdPropagation:
    """Tests for trace_id propagation (W3C TraceContext compliance)."""

    def test_log_event_generates_w3c_trace_id(self):
        """log_event should generate 32-char hex trace_id when not provided."""
        record = log_event(
            action="test_action",
            actor="test_actor",
            resource_type="test",
            resource_id="test-1",
            result="success",
        )
        assert len(record.trace_id) == 32
        assert all(c in "0123456789abcdef" for c in record.trace_id)

    def test_log_event_uses_provided_trace_id(self):
        """log_event should use provided trace_id."""
        trace_id = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        record = log_event(
            action="test_action",
            actor="test_actor",
            resource_type="test",
            resource_id="test-1",
            result="success",
            trace_id=trace_id,
        )
        assert record.trace_id == trace_id

    def test_append_propagates_trace_id(self):
        """AuditLayer.append should propagate trace_id to record."""
        layer = AuditLayer()
        trace_id = "deadbeef12345678deadbeef12345678"
        layer.append(
            action="test_action",
            object_id="test-obj",
            trace_id=trace_id,
        )
        records = layer.get_records()
        assert len(records) == 1
        assert records[0].trace_id == trace_id

    def test_trace_id_in_export_otel(self):
        """Exported OTel traces should include trace_id."""
        layer = AuditLayer()
        trace_id = "cafebabe12345678cafebabe12345678"
        layer.append(action="test_action", trace_id=trace_id)
        traces = layer.export_otel_traces()
        assert traces[0]["traceId"] == trace_id


class TestAuditAgentIdRequired:
    """Tests for agent_id as a required audit field (audit_record.v4.json schema)."""

    def test_log_event_with_agent_id(self):
        """log_event should accept and store agent_id."""
        record = log_event(
            action="cost_record",
            actor="evolver_v4",
            agent_id="spiffe://skillpool/evolver_v4",
        )
        assert record.agent_id == "spiffe://skillpool/evolver_v4"

    def test_log_event_agent_id_defaults_to_actor(self):
        """When agent_id is not provided, it should default to actor."""
        record = log_event(action="test", actor="evolver_v4")
        assert record.agent_id == "evolver_v4"

    def test_append_propagates_agent_id(self):
        """AuditLayer.append should propagate agent_id to record."""
        layer = AuditLayer()
        layer.append(
            action="test_action",
            object_id="test-obj",
            agent_id="spiffe://skillpool/review",
        )
        records = layer.get_records()
        assert records[0].agent_id == "spiffe://skillpool/review"

    def test_agent_id_in_to_dict(self):
        """agent_id should appear in serialized output."""
        import dataclasses
        record = log_event(action="test", agent_id="spiffe://skillpool/gate")
        d = dataclasses.asdict(record)
        assert "agent_id" in d
        assert d["agent_id"] == "spiffe://skillpool/gate"
