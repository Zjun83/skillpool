# Audit & Telemetry

SkillPool provides two complementary observability systems.

## Audit Log

Immutable, append-only log of all skill operations.

```python
from skillpool.audit import AuditLog, AuditEventType

audit = AuditLog(".skillpool/audit", session_id="my-session")

# Log events
audit.log(AuditEventType.REGISTER, "my-skill")
audit.log(AuditEventType.GATE_PASS, "my-skill")
audit.log(AuditEventType.MATERIALIZATION_COMPLETE, "my-skill")

# Query
entries = audit.query(skill_name="my-skill")
entries = audit.query(event_type=AuditEventType.GATE_PASS)

# Count
total = audit.count()
```

## Telemetry

Structured event logging for metrics and monitoring.

```python
from skillpool.telemetry import TelemetryLogger, EventType

telemetry = TelemetryLogger(".skillpool/telemetry", session_id="my-session")

# Log events
telemetry.log_registered("my-skill", quality_score=0.9)
telemetry.log_gate_check("my-skill", "pass", 0.9)
telemetry.log_materialize("my-skill", status="success")
telemetry.log_updated("my-skill", changes={"version": "1.1.0"})
telemetry.log_deleted("my-skill")

# Read events
events = telemetry.read_events()
events = telemetry.read_events(event_type=EventType.GATE_CHECKED)
```

## Correlation IDs

Both audit and telemetry support correlation IDs for distributed tracing:

```python
audit.log(AuditEventType.REGISTER, "skill-a", correlation_id="trace-123")
audit.log(AuditEventType.GATE_PASS, "skill-a", correlation_id="trace-123")
entries = audit.query(skill_name="skill-a")
for e in entries:
    assert e.correlation_id == "trace-123"
```
