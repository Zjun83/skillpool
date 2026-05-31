"""Audit Layer V4.0 — Immutable audit evidence with OpenTelemetry alignment.

Upgraded from V3.4 (17 fields) to V4.0 (34 fields) per V1.1 Section 8.12.
OpenTelemetry-compatible: trace_id, span_id, parent_span_id, event_id.
Hash chain integrity with append-only design.

Architecture constraint:
- Audit MUST NOT be bypassed
- Audit is append-only integrity-protected
- Audit unavailable = fail closed for mutations
"""
from __future__ import annotations

__all__ = [
    "AuditLayer",
    "AuditRecord",
    "AuditUnavailableError",
    "log_event",
]

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from skillpool.utils.time_utils import utc_now


def isoformat_z(dt) -> str:
    """Return ISO 8601 format with Z suffix for UTC."""
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


@dataclass
class AuditRecord:
    """Immutable audit record — 34-field OTel-aligned schema (V4.0)."""

    # ── Core identity (OTel-aligned) ──
    audit_id: str
    event_id: str = ""
    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""

    # ── Temporal ──
    event_type: str = "skill_pool_event"
    event_time: Any = field(default_factory=utc_now)
    created_at: str = ""
    updated_at: str = ""
    duration_ms: float = 0.0

    # ── Actor & session ──
    actor: str = "system"
    agent_id: str = ""  # Required by audit_record.v4.json schema (SPIFFE SVID or agent identifier)
    session_id: str = ""
    tenant_id: str = "default"

    # ── Source & target ──
    source_component: str = "SkillPool"
    action: str = ""
    resource_type: str = "skill"
    resource_id: str = ""

    # ── Request routing ──
    request_id: str = ""
    correlation_id: str = ""

    # ── Decision & result ──
    policy_decision: str = "allow"
    decision: str = ""
    result: str = "success"
    reason: str = ""
    severity: str = "INFO"

    # ── Integrity (hash chain) ──
    previous_hash: str = ""
    current_hash: str = ""
    chain_index: int = 0
    signature: str = ""

    # ── Content hashes ──
    input_hash: str = ""
    output_hash: str = ""

    # ── Metadata & compliance ──
    metadata_json: str = "{}"
    retention_class: str = "hot"
    compliance_tags: str = ""

    # ── Geo (optional) ──
    geo_location: str = ""

    # ── Backward compat aliases ──
    @property
    def hash(self) -> str:
        """Backward compat: hash → current_hash."""
        return self.current_hash

    @hash.setter
    def hash(self, value: str) -> None:
        self.current_hash = value

    @property
    def object_type(self) -> str:
        """Backward compat: object_type → resource_type."""
        return self.resource_type

    @object_type.setter
    def object_type(self, value: str) -> None:
        self.resource_type = value

    @property
    def object_id(self) -> str:
        """Backward compat: object_id → resource_id."""
        return self.resource_id

    @object_id.setter
    def object_id(self, value: str) -> None:
        self.resource_id = value

    @property
    def audit_ref(self) -> str:
        """Backward compat: audit_ref → audit_id."""
        return self.audit_id

    @audit_ref.setter
    def audit_ref(self, value: str) -> None:
        self.audit_id = value


def log_event(
    action: str,
    actor: str = "system",
    resource_type: str = "skill",
    resource_id: str = "",
    result: str = "success",
    reason: str = "",
    severity: str = "INFO",
    tenant_id: str = "default",
    source_component: str = "SkillPool",
    duration_ms: float = 0.0,
    metadata: dict[str, Any] | None = None,
    trace_id: str = "",
    request_id: str = "",
    session_id: str = "",
    agent_id: str = "",
    **kwargs: Any,
) -> AuditRecord:
    """
    Convenience function to create an audit event with auto-filled fields.

    Generates event_id (UUID7-like), trace_id (if not provided), span_id,
    and input/output hashes automatically. Suitable for one-liner audit logging.

    Args:
        action: Action performed (e.g., "register_skill", "approve_evolution")
        actor: Identity performing the action
        resource_type: Type of resource acted upon
        resource_id: ID of resource acted upon
        result: "success" / "failure" / "denied"
        reason: Human-readable explanation
        severity: INFO / WARN / ERROR / CRITICAL
        tenant_id: Tenant identifier
        source_component: Originating component
        duration_ms: Operation duration in milliseconds
        metadata: Arbitrary key-value metadata
        trace_id: OTel trace ID (auto-generated if empty)
        request_id: Request correlation ID
        session_id: User session ID
        **kwargs: Additional fields passed to AuditRecord

    Returns:
        Fully populated AuditRecord
    """
    now = utc_now()
    event_id = kwargs.pop("event_id", str(uuid.uuid4()))
    span_id = kwargs.pop("span_id", uuid.uuid4().hex[:16])
    parent_span_id = kwargs.pop("parent_span_id", "")

    # Hash inputs for integrity
    payload = json.dumps({
        "action": action,
        "actor": actor,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "result": result,
        "timestamp": isoformat_z(now),
    }, sort_keys=True)
    input_hash = hashlib.sha256(payload.encode()).hexdigest()

    record = AuditRecord(
        audit_id=f"audit-{event_id}",
        event_id=event_id,
        trace_id=trace_id or os.urandom(16).hex(),
        span_id=span_id,
        parent_span_id=parent_span_id,
        event_type="skill_pool_event",
        event_time=now,
        created_at=isoformat_z(now),
        updated_at=isoformat_z(now),
        duration_ms=duration_ms,
        actor=actor,
        agent_id=agent_id or actor,  # Default agent_id to actor if not provided
        session_id=session_id,
        tenant_id=tenant_id,
        source_component=source_component,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id or f"req-{uuid.uuid4().hex[:12]}",
        correlation_id=kwargs.pop("correlation_id", ""),
        policy_decision=kwargs.pop("policy_decision", "allow"),
        decision=kwargs.pop("decision", result),
        result=result,
        reason=reason,
        severity=severity,
        input_hash=input_hash,
        output_hash="",
        metadata_json=json.dumps(metadata or {}, sort_keys=True, ensure_ascii=False),
        retention_class=kwargs.pop("retention_class", "hot"),
        compliance_tags=kwargs.pop("compliance_tags", ""),
        geo_location=kwargs.pop("geo_location", ""),
        signature="",
        chain_index=0,
        previous_hash="",
        current_hash="",
    )

    # Compute final hash over all non-hash fields
    all_fields = {
        "event_id": record.event_id,
        "trace_id": record.trace_id,
        "span_id": record.span_id,
        "action": record.action,
        "actor": record.actor,
        "resource_type": record.resource_type,
        "resource_id": record.resource_id,
        "result": record.result,
        "timestamp": record.created_at,
        "previous_hash": record.previous_hash,
    }
    record.current_hash = hashlib.sha256(
        json.dumps(all_fields, sort_keys=True).encode()
    ).hexdigest()

    return record


class AuditUnavailableError(Exception):
    """Audit unavailable — fail closed."""
    pass


class AuditLayer:
    """
    Audit layer — immutable evidence ledger (V4.0).

    Hard rules:
    - MUST NOT be bypassed
    - MUST NOT be rewritten
    - MUST NOT be replaced by logs
    - Unavailable = fail closed for mutations
    """

    GENESIS_HASH = "0" * 64

    def __init__(self, available: bool = True, max_entries: int = 10000) -> None:
        self._available = available
        self._records: list[AuditRecord] = []
        self._last_hash = self.GENESIS_HASH
        self._max_entries = max_entries

    def _rotate(self) -> None:
        """Rotate audit log when entries exceed max_entries.

        Keeps the most recent max_entries records, preserving hash chain integrity
        by re-anchoring the oldest retained record as the new genesis.
        """
        if len(self._records) <= self._max_entries:
            return
        cutoff = len(self._records) - self._max_entries
        self._records = self._records[cutoff:]
        # Re-anchor: the oldest retained record becomes the new genesis reference
        if self._records:
            self._records[0].previous_hash = self.GENESIS_HASH

    def is_available(self) -> bool:
        """Check if Audit layer is available."""
        return self._available

    def set_available(self, available: bool) -> None:
        """Set availability (for testing)."""
        self._available = available

    def append(
        self,
        action: str,
        object_id: str = "",
        result: str = "success",
        actor: str = "system",
        tenant_id: str = "default",
        source_component: str = "SkillPool",
        **kwargs: Any,
    ) -> str:
        """
        Append immutable audit record (backward-compatible interface).

        Uses the upgraded log_event() internally to produce 34-field records.

        Returns audit_ref for traceability.

        Raises:
            AuditUnavailableError if Audit is unavailable
        """
        if not self._available:
            raise AuditUnavailableError("Audit unavailable — cannot append record")

        chain_index = len(self._records)
        previous_hash = self._last_hash

        record = log_event(
            action=action,
            actor=actor,
            resource_type=kwargs.pop("object_type", "skill"),
            resource_id=object_id,
            result=result,
            reason=kwargs.pop("reason", ""),
            severity=kwargs.pop("severity", "INFO"),
            tenant_id=tenant_id,
            source_component=source_component,
            duration_ms=kwargs.pop("duration_ms", 0.0),
            metadata=kwargs.pop("metadata", None),
            trace_id=kwargs.pop("trace_id", ""),
            request_id=kwargs.pop("request_id", ""),
            session_id=kwargs.pop("session_id", ""),
            agent_id=kwargs.pop("agent_id", ""),
            **kwargs,
        )

        record.previous_hash = previous_hash
        record.chain_index = chain_index

        # Recompute hash with chain position
        chain_payload = json.dumps({
            "event_id": record.event_id,
            "trace_id": record.trace_id,
            "span_id": record.span_id,
            "action": record.action,
            "actor": record.actor,
            "resource_type": record.resource_type,
            "resource_id": record.resource_id,
            "result": record.result,
            "timestamp": record.created_at,
            "chain_index": chain_index,
            "previous_hash": previous_hash,
        }, sort_keys=True)
        record.current_hash = hashlib.sha256(chain_payload.encode()).hexdigest()
        record.signature = record.current_hash

        self._records.append(record)
        self._last_hash = record.current_hash

        self._rotate()
        return record.audit_id

    def log_event_record(self, action: str, **kwargs: Any) -> AuditRecord:
        """
        Log a fully-detailed event (new V4.0 interface).

        Thin wrapper around the module-level log_event() that also
        appends to the chain.

        Args:
            action: Action name
            **kwargs: All AuditRecord fields

        Returns:
            The created AuditRecord
        """
        if not self._available:
            raise AuditUnavailableError("Audit unavailable — cannot log event")

        record = log_event(action=action, **kwargs)
        chain_index = len(self._records)
        record.previous_hash = self._last_hash
        record.chain_index = chain_index

        chain_payload = json.dumps({
            "event_id": record.event_id,
            "trace_id": record.trace_id,
            "span_id": record.span_id,
            "action": record.action,
            "actor": record.actor,
            "resource_type": record.resource_type,
            "resource_id": record.resource_id,
            "result": record.result,
            "timestamp": record.created_at,
            "chain_index": chain_index,
            "previous_hash": self._last_hash,
        }, sort_keys=True)
        record.current_hash = hashlib.sha256(chain_payload.encode()).hexdigest()
        record.signature = record.current_hash

        self._records.append(record)
        self._last_hash = record.current_hash

        return record

    def get_records(self, object_id: str | None = None) -> list[AuditRecord]:
        """Get audit records, optionally filtered by resource_id (or object_id compat)."""
        if object_id:
            return [
                r for r in self._records
                if r.resource_id == object_id
            ]
        return list(self._records)

    def get_record_count(self) -> int:
        """Return total number of audit records."""
        return len(self._records)

    def verify_integrity(self) -> bool:
        """
        Verify hash chain integrity.

        Returns True if all records form a valid chain.
        """
        expected_hash = self.GENESIS_HASH

        for idx, record in enumerate(self._records):
            if record.previous_hash != expected_hash:
                return False

            chain_payload = json.dumps({
                "event_id": record.event_id,
                "trace_id": record.trace_id,
                "span_id": record.span_id,
                "action": record.action,
                "actor": record.actor,
                "resource_type": record.resource_type,
                "resource_id": record.resource_id,
                "result": record.result,
                "timestamp": record.created_at,
                "chain_index": idx,
                "previous_hash": expected_hash,
            }, sort_keys=True)

            expected_hash = hashlib.sha256(chain_payload.encode()).hexdigest()

            if record.current_hash != expected_hash:
                return False

        return True

    def export_otel_traces(self) -> list[dict[str, Any]]:
        """
        Export records in OpenTelemetry-compatible format.

        Returns:
            List of dicts with OTel standard fields: traceId, spanId, name, attributes, etc.
        """
        from datetime import timezone

        traces = []
        for record in self._records:
            event_time = record.event_time
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)

            traces.append({
                "traceId": record.trace_id,
                "spanId": record.span_id,
                "parentSpanId": record.parent_span_id or None,
                "name": f"{record.source_component}.{record.action}",
                "kind": "INTERNAL",
                "startTimeUnixNano": str(int(event_time.timestamp() * 1e9)),
                "endTimeUnixNano": str(int((event_time.timestamp() + record.duration_ms / 1000) * 1e9)),
                "attributes": {
                    "audit.id": record.audit_id,
                    "event.id": record.event_id,
                    "actor": record.actor,
                    "action": record.action,
                    "resource.type": record.resource_type,
                    "resource.id": record.resource_id,
                    "decision": record.decision,
                    "result": record.result,
                    "severity": record.severity,
                    "tenant.id": record.tenant_id,
                    "compliance.tags": record.compliance_tags,
                },
                "status": {"code": 1 if record.result == "success" else 2},
            })
        return traces
