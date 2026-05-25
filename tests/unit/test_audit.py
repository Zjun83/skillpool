"""Unit tests for SkillPool audit module."""

from __future__ import annotations

import json
from pathlib import Path

from skillpool.audit import AuditEntry, AuditEventType, AuditLog


class TestAuditEntry:
    """Tests for AuditEntry model."""

    def test_create_entry_with_defaults(self):
        entry = AuditEntry(
            event_type=AuditEventType.REGISTER,
            skill_name="test-skill",
        )
        assert entry.event_type == AuditEventType.REGISTER
        assert entry.skill_name == "test-skill"
        assert entry.actor == "system"
        assert entry.details == {}
        assert entry.timestamp  # auto-generated

    def test_create_entry_with_all_fields(self):
        entry = AuditEntry(
            event_type=AuditEventType.GATE_PASS,
            skill_name="my-skill",
            actor="user",
            details={"score": 0.85},
            session_id="sess-123",
            correlation_id="corr-456",
        )
        assert entry.event_type == AuditEventType.GATE_PASS
        assert entry.skill_name == "my-skill"
        assert entry.actor == "user"
        assert entry.details == {"score": 0.85}
        assert entry.session_id == "sess-123"
        assert entry.correlation_id == "corr-456"

    def test_entry_serialization(self):
        entry = AuditEntry(
            event_type=AuditEventType.REGISTER,
            skill_name="test-skill",
        )
        data = json.loads(entry.model_dump_json())
        assert data["event_type"] == "register"
        assert data["skill_name"] == "test-skill"


class TestAuditEventType:
    """Tests for AuditEventType enum."""

    def test_all_event_types(self):
        expected = {
            "register",
            "update",
            "delete",
            "gate_pass",
            "gate_fail",
            "gate_override",
            "materialization_start",
            "materialization_complete",
            "materialization_rollback",
            "quality_profile",
            "error",
        }
        actual = {e.value for e in AuditEventType}
        assert actual == expected


class TestAuditLog:
    """Tests for AuditLog class."""

    def test_log_creates_file(self, tmp_path: Path):
        log = AuditLog(tmp_path / "audit_test")
        log.log(AuditEventType.REGISTER, "test-skill")
        assert (tmp_path / "audit_test" / "audit.jsonl").exists()

    def test_log_writes_entry(self, tmp_path: Path):
        log = AuditLog(tmp_path / "audit_test")
        entry = log.log(AuditEventType.GATE_PASS, "my-skill", actor="user")
        assert entry.skill_name == "my-skill"
        assert entry.event_type == AuditEventType.GATE_PASS

    def test_log_with_details(self, tmp_path: Path):
        log = AuditLog(tmp_path / "audit_test")
        entry = log.log(
            AuditEventType.GATE_FAIL,
            "bad-skill",
            details={"score": 0.3, "threshold": 0.6},
        )
        assert entry.details["score"] == 0.3

    def test_query_by_skill_name(self, tmp_path: Path):
        log = AuditLog(tmp_path / "audit_test")
        log.log(AuditEventType.REGISTER, "skill-a")
        log.log(AuditEventType.REGISTER, "skill-b")
        log.log(AuditEventType.UPDATE, "skill-a")
        results = log.query(skill_name="skill-a")
        assert len(results) == 2

    def test_query_by_event_type(self, tmp_path: Path):
        log = AuditLog(tmp_path / "audit_test")
        log.log(AuditEventType.REGISTER, "skill-a")
        log.log(AuditEventType.GATE_PASS, "skill-a")
        results = log.query(event_type=AuditEventType.GATE_PASS)
        assert len(results) == 1
        assert results[0].event_type == AuditEventType.GATE_PASS

    def test_query_by_actor(self, tmp_path: Path):
        log = AuditLog(tmp_path / "audit_test")
        log.log(AuditEventType.REGISTER, "skill-a", actor="admin")
        log.log(AuditEventType.REGISTER, "skill-b", actor="user")
        results = log.query(actor="admin")
        assert len(results) == 1
        assert results[0].actor == "admin"

    def test_query_with_limit(self, tmp_path: Path):
        log = AuditLog(tmp_path / "audit_test")
        for i in range(10):
            log.log(AuditEventType.REGISTER, f"skill-{i}")
        results = log.query(limit=3)
        assert len(results) == 3

    def test_query_returns_most_recent_first(self, tmp_path: Path):
        log = AuditLog(tmp_path / "audit_test")
        log.log(AuditEventType.REGISTER, "oldest")
        log.log(AuditEventType.REGISTER, "newest")
        results = log.query()
        assert results[0].skill_name == "newest"

    def test_count(self, tmp_path: Path):
        log = AuditLog(tmp_path / "audit_test")
        assert log.count() == 0
        log.log(AuditEventType.REGISTER, "skill-a")
        log.log(AuditEventType.GATE_PASS, "skill-a")
        assert log.count() == 2

    def test_session_id_propagated(self, tmp_path: Path):
        log = AuditLog(tmp_path / "audit_test", session_id="sess-abc")
        entry = log.log(AuditEventType.REGISTER, "test-skill")
        assert entry.session_id == "sess-abc"

    def test_query_empty_log(self, tmp_path: Path):
        log = AuditLog(tmp_path / "audit_test")
        results = log.query()
        assert results == []
