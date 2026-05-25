"""Integration tests for SkillPool end-to-end workflows."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillpool.audit import AuditEventType, AuditLog
from skillpool.csdf import CSDFDocument
from skillpool.gate import Gate, GateConfig, GateStatus
from skillpool.materializer import Materializer
from skillpool.quality import QualityProfiler
from skillpool.registry import Registry, SkillEntry
from skillpool.telemetry import EventType, TelemetryLogger


@pytest.fixture
def skillpool_dir(tmp_path: Path) -> Path:
    """Create a temporary .skillpool directory."""
    sp = tmp_path / ".skillpool"
    sp.mkdir()
    return sp


@pytest.fixture
def registry(skillpool_dir: Path) -> Registry:
    """Create a Registry instance."""
    return Registry(registry_path=skillpool_dir / "registry.jsonl")


@pytest.fixture
def audit_log(skillpool_dir: Path) -> AuditLog:
    """Create an AuditLog instance."""
    return AuditLog(skillpool_dir / "audit", session_id="test-session")


@pytest.fixture
def telemetry(skillpool_dir: Path) -> TelemetryLogger:
    """Create a TelemetryLogger instance."""
    return TelemetryLogger(skillpool_dir / "telemetry", session_id="test-session")


@pytest.fixture
def gate() -> Gate:
    """Create a Gate instance."""
    return Gate(config=GateConfig(min_quality_score=0.6))


@pytest.fixture
def quality_profiler() -> QualityProfiler:
    """Create a QualityProfiler instance."""
    return QualityProfiler()


@pytest.fixture
def materializer(skillpool_dir: Path) -> Materializer:
    """Create a Materializer instance."""
    return Materializer(skillpool_dir)


class TestRegisterAndGateWorkflow:
    """Test the register -> quality -> gate workflow."""

    def test_high_quality_skill_passes_gate(
        self,
        registry: Registry,
        quality_profiler: QualityProfiler,
        gate: Gate,
        audit_log: AuditLog,
        telemetry: TelemetryLogger,
    ) -> None:
        """A high-quality skill should pass the gate check."""
        doc = CSDFDocument(
            name="python-testing",
            version="1.0.0",
            description="Python testing best practices",
            triggers=["when writing tests", "when testing Python code"],
            dimensions={
                "completeness": 0.9,
                "accuracy": 0.85,
                "usability": 0.8,
                "maintainability": 0.75,
            },
            body="## Instructions\nWrite comprehensive tests.",
        )

        entry = SkillEntry(
            name=doc.name,
            version=doc.version,
            description=doc.description,
            tags=["testing", "python"],
        )
        registry.register(entry)

        profile = quality_profiler.profile(doc)
        assert profile.overall > 0

        result = gate.check(profile)
        assert result.status == GateStatus.PASS

        registry.update("python-testing", {"quality_score": profile.overall})

        audit_log.log(AuditEventType.GATE_PASS, "python-testing")
        telemetry.log_gate_check("python-testing", "pass", result.overall_score)

        audit_entries = audit_log.query(skill_name="python-testing")
        assert len(audit_entries) >= 1

        events = telemetry.read_events(event_type=EventType.GATE_CHECKED)
        assert len(events) >= 1

    def test_low_quality_skill_fails_gate(
        self,
        registry: Registry,
        gate: Gate,
        audit_log: AuditLog,
    ) -> None:
        """A low-quality skill should fail the gate check."""
        doc = CSDFDocument(
            name="bad-skill",
            version="0.1.0",
            description="",
            dimensions={
                "completeness": 0.1,
                "accuracy": 0.1,
                "usability": 0.1,
                "maintainability": 0.1,
            },
        )

        entry = SkillEntry(name="bad-skill", version="0.1.0", description="")
        registry.register(entry)

        profiler = QualityProfiler()
        profile = profiler.profile(doc)
        result = gate.check(profile)
        assert result.status == GateStatus.FAIL

        registry.update("bad-skill", {"quality_score": profile.overall})
        audit_log.log(AuditEventType.GATE_FAIL, "bad-skill")
        entries = audit_log.query(event_type=AuditEventType.GATE_FAIL)
        assert len(entries) >= 1


class TestRegisterMaterializeWorkflow:
    """Test the register -> gate -> materialize workflow."""

    def test_materialize_passing_skill(
        self,
        registry: Registry,
        materializer: Materializer,
        skillpool_dir: Path,
    ) -> None:
        """A passing skill should be materialized successfully."""
        doc = CSDFDocument(
            name="docker-bp",
            version="1.0.0",
            description="Docker best practices",
            triggers=["when using Docker", "when writing Dockerfiles"],
            dimensions={
                "completeness": 0.9,
                "accuracy": 0.9,
                "usability": 0.9,
                "maintainability": 0.9,
            },
            body="## Docker Best Practices\nUse multi-stage builds.",
        )
        entry = SkillEntry(
            name="docker-bp",
            version="1.0.0",
            description="Docker best practices",
            tags=["docker", "containers"],
            quality_score=0.9,
        )
        registry.register(entry)

        result = materializer.materialize(doc, agent_type="codex")
        assert result.success is True

    def test_materialize_with_rollback(
        self,
        materializer: Materializer,
    ) -> None:
        """Materialize a skill and verify version history for rollback."""
        doc = CSDFDocument(
            name="rollback-skill",
            version="1.0.0",
            description="Skill for rollback testing",
            triggers=["when testing rollback"],
            body="Version 1 content",
        )
        result = materializer.materialize(doc, agent_type="codex")
        assert result.success is True

        versions = materializer.list_versions("rollback-skill", agent_type="codex")
        assert len(versions) >= 1


class TestCSDFWorkflow:
    """Test CSDF document parsing and registration."""

    def test_parse_and_register_csdf(
        self,
        registry: Registry,
        quality_profiler: QualityProfiler,
    ) -> None:
        """Parse a CSDF document and register the skill."""
        doc = CSDFDocument(
            name="react-patterns",
            version="2.0.0",
            description="React design patterns",
            triggers=["when building React apps"],
            dimensions={
                "completeness": 0.8,
                "accuracy": 0.85,
                "usability": 0.7,
                "maintainability": 0.75,
            },
            body="## React Patterns\nUse hooks for state management.",
        )
        entry = SkillEntry(
            name=doc.name,
            version=doc.version,
            description=doc.description,
            tags=["react", "patterns"],
        )
        registry.register(entry)

        profile = quality_profiler.profile(doc)
        assert profile.overall > 0

    def test_csdf_round_trip(
        self,
        tmp_path: Path,
    ) -> None:
        """CSDF document should round-trip through serialization."""
        doc = CSDFDocument(
            name="api-design",
            version="1.5.0",
            description="REST API design principles",
            triggers=["when designing APIs"],
            dimensions={
                "completeness": 0.7,
                "accuracy": 0.8,
                "usability": 0.6,
                "maintainability": 0.7,
            },
            body="## API Design\nUse consistent naming.",
        )
        data = doc.model_dump()
        restored = CSDFDocument(**data)
        assert restored.name == doc.name
        assert restored.version == doc.version
        assert restored.description == doc.description


class TestAuditTelemetryIntegration:
    """Test audit and telemetry work together."""

    def test_full_audit_trail(
        self,
        registry: Registry,
        audit_log: AuditLog,
        telemetry: TelemetryLogger,
    ) -> None:
        """Register, update, delete should all be audited."""
        entry = SkillEntry(name="audited-skill", version="1.0.0")
        registry.register(entry)
        audit_log.log(AuditEventType.REGISTER, "audited-skill")
        telemetry.log_registered("audited-skill", quality_score=0.0)

        registry.update("audited-skill", {"quality_score": 0.8})
        audit_log.log(AuditEventType.UPDATE, "audited-skill")
        telemetry.log_updated("audited-skill", changes={"quality_score": 0.8})

        registry.delete("audited-skill")
        audit_log.log(AuditEventType.DELETE, "audited-skill")
        telemetry.log_deleted("audited-skill")

        assert audit_log.count() == 3
        register_entries = audit_log.query(event_type=AuditEventType.REGISTER)
        assert len(register_entries) >= 1

        all_events = telemetry.read_events()
        assert len(all_events) >= 3

    def test_correlation_id_tracing(
        self,
        audit_log: AuditLog,
    ) -> None:
        """Audit entries with correlation IDs should be traceable."""
        corr_id = "trace-abc-123"
        audit_log.log(
            AuditEventType.GATE_PASS,
            "skill-a",
            correlation_id=corr_id,
        )
        audit_log.log(
            AuditEventType.MATERIALIZATION_START,
            "skill-a",
            correlation_id=corr_id,
        )
        audit_log.log(
            AuditEventType.MATERIALIZATION_COMPLETE,
            "skill-a",
            correlation_id=corr_id,
        )

        entries = audit_log.query(skill_name="skill-a")
        assert len(entries) == 3
        for e in entries:
            assert e.correlation_id == corr_id
