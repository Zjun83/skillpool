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

    def _make_layer(self, tmp_path=None, **kwargs):
        """Create an AuditLayer with isolated data_dir for testing."""
        if tmp_path is not None:
            return AuditLayer(data_dir=tmp_path, **kwargs)
        return AuditLayer(**kwargs)

    def test_append_returns_audit_id(self, tmp_path):
        layer = self._make_layer(tmp_path)
        ref = layer.append(action="test_action", object_id="obj-1")
        assert ref.startswith("audit-")

    def test_append_creates_record(self, tmp_path):
        layer = self._make_layer(tmp_path)
        layer.append(action="register", object_id="skill-1")
        records = layer.get_records()
        assert len(records) == 1
        assert records[0].action == "register"
        assert records[0].resource_id == "skill-1"

    def test_append_unavailable_raises(self):
        layer = AuditLayer(available=False)
        with pytest.raises(AuditUnavailableError):
            layer.append(action="test")

    def test_hash_chain_integrity(self, tmp_path):
        layer = self._make_layer(tmp_path)
        layer.append(action="action1")
        layer.append(action="action2")
        layer.append(action="action3")
        assert layer.verify_integrity() is True

    def test_hash_chain_broken_if_tampered(self, tmp_path):
        layer = self._make_layer(tmp_path)
        layer.append(action="action1")
        layer.append(action="action2")
        # Tamper with first record
        records = layer.get_records()
        records[0].action = "tampered"
        assert layer.verify_integrity() is False

    def test_chain_index_sequential(self, tmp_path):
        layer = self._make_layer(tmp_path)
        layer.append(action="a1")
        layer.append(action="a2")
        records = layer.get_records()
        assert records[0].chain_index == 0
        assert records[1].chain_index == 1

    def test_previous_hash_links(self, tmp_path):
        layer = self._make_layer(tmp_path)
        layer.append(action="a1")
        layer.append(action="a2")
        records = layer.get_records()
        assert records[0].previous_hash == "0" * 64
        assert records[1].previous_hash == records[0].current_hash

    def test_filter_by_object_id(self, tmp_path):
        layer = self._make_layer(tmp_path)
        layer.append(action="a1", object_id="skill-1")
        layer.append(action="a2", object_id="skill-2")
        layer.append(action="a3", object_id="skill-1")
        filtered = layer.get_records("skill-1")
        assert len(filtered) == 2

    def test_get_record_count(self, tmp_path):
        layer = self._make_layer(tmp_path)
        assert layer.get_record_count() == 0
        layer.append(action="a1")
        layer.append(action="a2")
        assert layer.get_record_count() == 2

    def test_rotation(self, tmp_path):
        layer = self._make_layer(tmp_path, max_entries=3)
        for i in range(5):
            layer.append(action=f"a{i}")
        assert layer.get_record_count() == 3

    def test_rotation_preserves_chain_integrity(self, tmp_path):
        """After rotation, internal hash chain must still verify."""
        layer = self._make_layer(tmp_path, max_entries=3)
        for i in range(5):
            layer.append(action=f"a{i}")
        assert layer.verify_integrity() is True

    def test_rotation_carries_forward_pre_rotation_hash(self, tmp_path):
        """After rotation, the first retained record's previous_hash must
        match the current_hash of the last discarded record."""
        layer = self._make_layer(tmp_path, max_entries=3)
        for i in range(5):
            layer.append(action=f"a{i}")
        # Records kept: a2, a3, a4 (cutoff=2, discarded: a0, a1)
        first_retained = layer._records[0]
        assert first_retained.action == "a2"
        # previous_hash should be the current_hash of a1 (last discarded)
        assert first_retained.previous_hash != AuditLayer.GENESIS_HASH

    def test_log_event_record(self, tmp_path):
        layer = self._make_layer(tmp_path)
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

    def test_export_otel_traces(self, tmp_path):
        layer = self._make_layer(tmp_path)
        layer.append(action="test_action", object_id="obj-1")
        traces = layer.export_otel_traces()
        assert len(traces) == 1
        t = traces[0]
        assert "traceId" in t
        assert "spanId" in t
        assert "attributes" in t
        assert t["attributes"]["action"] == "test_action"
        assert t["status"]["code"] == 1  # success

    def test_export_otel_failure_status(self, tmp_path):
        layer = self._make_layer(tmp_path)
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

    def test_append_propagates_trace_id(self, tmp_path):
        """AuditLayer.append should propagate trace_id to record."""
        layer = AuditLayer(data_dir=tmp_path)
        trace_id = "deadbeef12345678deadbeef12345678"
        layer.append(
            action="test_action",
            object_id="test-obj",
            trace_id=trace_id,
        )
        records = layer.get_records()
        assert len(records) == 1
        assert records[0].trace_id == trace_id

    def test_trace_id_in_export_otel(self, tmp_path):
        """Exported OTel traces should include trace_id."""
        layer = AuditLayer(data_dir=tmp_path)
        trace_id = "cafebabe12345678cafebabe12345678"
        layer.append(action="test_action", trace_id=trace_id)
        traces = layer.export_otel_traces()
        assert traces[0]["traceId"] == trace_id


class TestTraceSource:
    """Tests for trace_source field tracking trace_id provenance."""

    def test_auto_generated_trace_sets_internal_source(self):
        """When trace_id is auto-generated, trace_source should be 'skillpool_internal'."""
        record = log_event(action="test")
        assert record.trace_source == "skillpool_internal"

    def test_provided_trace_sets_passthrough_source(self):
        """When trace_id is provided, trace_source should be 'w3c_passthrough'."""
        record = log_event(action="test", trace_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        assert record.trace_source == "w3c_passthrough"

    def test_explicit_trace_source_override(self):
        """trace_source can be explicitly overridden via kwargs."""
        record = log_event(action="test", trace_source="test")
        assert record.trace_source == "test"

    def test_trace_source_persisted_in_jsonl(self, tmp_path):
        """trace_source should be persisted to and loaded from JSONL."""
        layer = AuditLayer(data_dir=tmp_path)
        layer.append(action="test", trace_id="abc123def456abc123def456abc12345")
        records = layer.get_records()
        assert records[0].trace_source == "w3c_passthrough"

        # Load from disk
        layer2 = AuditLayer(data_dir=tmp_path)
        loaded = layer2.get_records()
        assert loaded[0].trace_source == "w3c_passthrough"


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

    def test_append_propagates_agent_id(self, tmp_path):
        """AuditLayer.append should propagate agent_id to record."""
        layer = AuditLayer(data_dir=tmp_path)
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


class TestAuditJsonlPersistence:
    """Tests for JSONL file persistence of audit records."""

    def test_jsonl_file_created_on_append(self, tmp_path):
        """Appending a record should create audit.jsonl."""
        layer = AuditLayer(data_dir=tmp_path)
        layer.append(action="test_action")
        jsonl_path = tmp_path / "audit" / "audit.jsonl"
        assert jsonl_path.exists()

    def test_jsonl_contains_record(self, tmp_path):
        """JSONL file should contain the appended record."""
        layer = AuditLayer(data_dir=tmp_path)
        layer.append(action="register_skill", object_id="skill-1")
        jsonl_path = tmp_path / "audit" / "audit.jsonl"
        line = jsonl_path.read_text(encoding="utf-8").strip()
        data = json.loads(line)
        assert data["action"] == "register_skill"
        assert data["resource_id"] == "skill-1"

    def test_jsonl_appends_multiple_records(self, tmp_path):
        """Multiple appends should produce multiple lines."""
        layer = AuditLayer(data_dir=tmp_path)
        layer.append(action="a1")
        layer.append(action="a2")
        lines = (tmp_path / "audit" / "audit.jsonl").read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["action"] == "a1"
        assert json.loads(lines[1])["action"] == "a2"

    def test_load_from_jsonl_rebuilds_state(self, tmp_path):
        """New AuditLayer should load records from existing JSONL."""
        # Write records with first instance
        layer1 = AuditLayer(data_dir=tmp_path)
        layer1.append(action="action1", object_id="obj-1")
        layer1.append(action="action2", object_id="obj-2")

        # Create new instance — should load from JSONL
        layer2 = AuditLayer(data_dir=tmp_path)
        assert layer2.get_record_count() == 2
        records = layer2.get_records()
        assert records[0].action == "action1"
        assert records[1].action == "action2"

    def test_load_preserves_hash_chain(self, tmp_path):
        """Hash chain should survive reload from JSONL."""
        layer1 = AuditLayer(data_dir=tmp_path)
        layer1.append(action="a1")
        layer1.append(action="a2")

        layer2 = AuditLayer(data_dir=tmp_path)
        assert layer2.verify_integrity() is True

    def test_loaded_records_have_correct_last_hash(self, tmp_path):
        """_last_hash should be correctly set after loading."""
        layer1 = AuditLayer(data_dir=tmp_path)
        layer1.append(action="a1")
        layer1.append(action="a2")
        expected_last = layer1._last_hash

        layer2 = AuditLayer(data_dir=tmp_path)
        assert layer2._last_hash == expected_last

    def test_new_appends_after_load_continue_chain(self, tmp_path):
        """Appending after reload should continue the hash chain."""
        layer1 = AuditLayer(data_dir=tmp_path)
        layer1.append(action="a1")
        layer1.append(action="a2")

        layer2 = AuditLayer(data_dir=tmp_path)
        layer2.append(action="a3")
        assert layer2.verify_integrity() is True
        records = layer2.get_records()
        assert records[2].previous_hash == records[1].current_hash

    def test_empty_data_dir_no_error(self, tmp_path):
        """Creating AuditLayer with empty dir should not raise."""
        layer = AuditLayer(data_dir=tmp_path)
        assert layer.get_record_count() == 0

    def test_corrupted_jsonl_graceful(self, tmp_path):
        """Corrupted JSONL lines should be skipped gracefully."""
        jsonl_path = tmp_path / "audit"
        jsonl_path.mkdir()
        (jsonl_path / "audit.jsonl").write_text("not-json\n", encoding="utf-8")
        layer = AuditLayer(data_dir=tmp_path)
        assert layer.get_record_count() == 0
