"""Registry Layer — Skill metadata and version truth source.

Architecture constraint:
- Registry MUST NOT execute skills
- Registry stores metadata, versions, state, signatures, SBOM, licenses
- State transitions require Audit record
"""
from __future__ import annotations

__all__ = [
    "AuditUnavailableError",
    "IllegalStateTransitionError",
    "PolicyDeniedError",
    "ProblemDetail",
    "Registry",
    "SandboxRequiredError",
    "SkillNotFoundError",
    "SkillRecord",
    "SupplyChainEvidenceMissingError",
]

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from skillpool.registry.models import (
    ProblemDetail,
    RegisterSkillRequest,
    RegisterSkillResponse,
    SkillMetadata,
    SkillStatus,
    StateTransitionRequest,
    StateTransitionResponse,
)

logger = logging.getLogger(__name__)


@dataclass
class SkillRecord:
    """Internal skill record in Registry."""
    metadata: SkillMetadata
    created_at: datetime
    updated_at: datetime
    evidence: set[str] = field(default_factory=set)
    audit_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize SkillRecord to dict for JSON persistence."""
        return {
            "metadata": {
                "skill_id": self.metadata.skill_id,
                "name": self.metadata.name,
                "version": self.metadata.version,
                "status": self.metadata.status.value,
                "description": self.metadata.description,
                "author": self.metadata.author,
                "created_at": self.metadata.created_at,
                "updated_at": self.metadata.updated_at,
                "tags": self.metadata.tags,
                "dependencies": self.metadata.dependencies,
                "security": self.metadata.security,
                "quality_score": self.metadata.quality_score,
            },
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "evidence": sorted(self.evidence),
            "audit_refs": list(self.audit_refs),
        }

    @classmethod
    def from_dict(cls, data: dict) -> SkillRecord:
        """Deserialize SkillRecord from dict."""
        meta = data.get("metadata", {})
        if isinstance(meta, dict):
            status_val = meta.get("status", "draft")
            try:
                status_enum = SkillStatus(status_val)
            except ValueError:
                status_enum = SkillStatus.DRAFT
            meta_obj = SkillMetadata(
                skill_id=meta.get("skill_id", ""),
                name=meta.get("name", ""),
                version=meta.get("version", ""),
                status=status_enum,
                description=meta.get("description", ""),
                author=meta.get("author", ""),
                created_at=meta.get("created_at", ""),
                updated_at=meta.get("updated_at", ""),
                tags=meta.get("tags", []),
                dependencies=meta.get("dependencies", []),
                security=meta.get("security", {}),
                quality_score=meta.get("quality_score", 0.0),
            )
        else:
            meta_obj = meta
        return cls(
            metadata=meta_obj,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            evidence=set(data.get("evidence", [])),
            audit_refs=data.get("audit_refs", []),
        )


# Legal state transitions
LEGAL_TRANSITIONS = {
    ("draft", "imported"),
    ("imported", "testing"),
    ("testing", "enabled"),
    ("testing", "disabled"),
    ("enabled", "disabled"),
    ("enabled", "deprecated"),
    ("deprecated", "disabled"),
    ("disabled", "testing"),
}

# Illegal transitions
ILLEGAL_TRANSITIONS = {
    ("draft", "enabled"),
    ("imported", "enabled"),
}

# Required evidence per environment (SLSA-aligned)
# dev=L0 (no requirements), ci=L1 (source pin + SBOM), prod=L2+ (full evidence)
SUPPLY_CHAIN_PROFILES = {
    "dev": set(),  # SLSA Build L0 — no requirements for local development
    "ci": {"source pin", "SPDX SBOM"},  # SLSA Build L1 — provenance exists
    "prod": {"SPDX SBOM", "SLSA provenance", "source pin", "signature"},  # SLSA Build L2+
}

# Default: production-level evidence (backward compatible)
REQUIRED_EVIDENCE = SUPPLY_CHAIN_PROFILES["prod"]


class AuditUnavailableError(Exception):
    """Audit unavailable — fail closed."""
    pass


class SupplyChainEvidenceMissingError(Exception):
    """Missing SPDX/SLSA/signature evidence."""
    pass


class IllegalStateTransitionError(Exception):
    """Illegal lifecycle transition."""
    pass


class SkillNotFoundError(Exception):
    """Skill not found in Registry."""
    pass


class SandboxRequiredError(Exception):
    """Sandbox pass required."""
    pass


class PolicyDeniedError(Exception):
    """Policy approval denied."""
    pass


class Registry:
    """
    Registry layer — skill metadata and lifecycle governance.

    Hard rules:
    - Requires SPDX SBOM, SLSA provenance, source pin, signature
    - Audit must be available for all mutations
    - State transitions follow legal paths only

    Lookup supports both skill_id (e.g., "S09") and name (e.g., "resilience-degradation").
    """

    def __init__(self, audit_layer, registry_path: str | None = None) -> None:
        self._skills: dict[str, SkillRecord] = {}
        self._by_name: dict[str, str] = {}  # name -> skill_id index for dual lookup
        self._audit = audit_layer
        self._registry_path = Path(registry_path) if registry_path else None
        self._evidence_profile: str = os.environ.get("SKILLPOOL_EVIDENCE_TIER", "prod")
        self._required_evidence: set[str] = SUPPLY_CHAIN_PROFILES.get(
            self._evidence_profile, SUPPLY_CHAIN_PROFILES["prod"]
        )
        self._load()

    def _load(self) -> None:
        """Load registry from persistent storage if path is configured.

        Supports both JSON object format (single JSON dict) and JSONL format
        (one record per line), with automatic detection.
        """
        if not self._registry_path:
            return
        if not self._registry_path.exists():
            return
        try:
            content = self._registry_path.read_text(encoding="utf-8").strip()
            if not content:
                return

            # Try JSON object format first (standard Registry format)
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    for sid, sdata in data.items():
                        rec = SkillRecord.from_dict(sdata)
                        self._skills[sid] = rec
                        self._by_name[rec.metadata.name] = sid
                    return
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

            # Try JSONL format (one record per line)
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = SkillRecord.from_dict(json.loads(line))
                    self._skills[rec.metadata.skill_id] = rec
                    self._by_name[rec.metadata.name] = rec.metadata.skill_id
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
        except Exception as exc:
            logger.warning("Registry load failed from %s: %s", self._registry_path, exc)

    def _save(self) -> None:
        """Persist registry to disk if path is configured."""
        if not self._registry_path:
            return
        try:
            self._registry_path.parent.mkdir(parents=True, exist_ok=True)
            data = {sid: rec.to_dict() for sid, rec in self._skills.items()}
            self._registry_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("Registry save failed to %s: %s", self._registry_path, exc)

    def _check_audit_available(self) -> bool:
        """Check if Audit layer is available."""
        return self._audit.is_available()

    def register_candidate(
        self,
        request: RegisterSkillRequest,
    ) -> RegisterSkillResponse:
        """
        Register a skill candidate into testing state.

        Prerequisites:
        - SPDX SBOM present
        - SLSA provenance present
        - Source pin present
        - Signature present
        - Audit available

        Returns skill in 'testing' state, NOT production routable.
        """
        skill_id = request.skill_metadata.skill_id

        if not self._check_audit_available():
            raise AuditUnavailableError("Audit unavailable - cannot register skill")

        security = request.skill_metadata.security
        evidence = set()

        if security.get("sbom_ref") or security.get("sbom"):
            evidence.add("SPDX SBOM")
        if security.get("provenance_ref") or security.get("provenance"):
            evidence.add("SLSA provenance")
        if security.get("source_pin") or security.get("source_ref") or security.get("source"):
            evidence.add("source pin")
        if security.get("signature_ref") or security.get("signature") or security.get("digest"):
            evidence.add("signature")

        missing = self._required_evidence - evidence
        if missing:
            raise SupplyChainEvidenceMissingError(
                f"Missing required evidence: {missing}. "
                f"Provided fields: {list(security.keys())}. "
                f"Current profile: {self._evidence_profile} "
                f"(set SKILLPOOL_EVIDENCE_TIER=dev to relax)"
            )

        now = datetime.now(UTC)
        record = SkillRecord(
            metadata=request.skill_metadata,
            created_at=now,
            updated_at=now,
            evidence=evidence,
        )
        record.metadata.status = SkillStatus.TESTING

        audit_ref = self._audit.append(
            action="register_skill_candidate",
            object_id=skill_id,
            result="success",
        )
        record.audit_refs.append(audit_ref)

        self._skills[skill_id] = record
        self._by_name[request.skill_metadata.name] = skill_id
        self._save()

        return RegisterSkillResponse(
            context=request.context,
            skill_id=skill_id,
            status="testing",
            audit_ref=audit_ref,
        )

    def transition_state(
        self,
        skill_id: str,
        request: StateTransitionRequest,
        sandbox_result: str | None = None,
        policy_approval: bool = False,
    ) -> StateTransitionResponse:
        """
        Transition skill state with Audit fail-closed and prerequisites.

        Prerequisites for 'enabled':
        - Sandbox L1, L2, L3 pass
        - Policy approval exists
        - Audit available
        """
        if not self._check_audit_available():
            raise AuditUnavailableError("Audit unavailable - cannot transition state")

        record = self._skills.get(skill_id)
        if not record:
            raise SkillNotFoundError(f"Skill not found: {skill_id}")

        from_status = request.from_status.value
        to_status = request.to_status.value

        if record.metadata.status.value != from_status:
            raise IllegalStateTransitionError(
                f"Current state {record.metadata.status.value} != requested {from_status}"
            )

        if (from_status, to_status) in ILLEGAL_TRANSITIONS:
            self._audit.append(
                action="illegal_state_transition",
                object_id=skill_id,
                result="denied",
            )
            raise IllegalStateTransitionError(
                f"Illegal transition: {from_status} -> {to_status}"
            )

        if (from_status, to_status) not in LEGAL_TRANSITIONS:
            self._audit.append(
                action="illegal_state_transition",
                object_id=skill_id,
                result="denied",
            )
            raise IllegalStateTransitionError(
                f"Unknown transition: {from_status} -> {to_status}"
            )

        if to_status == "enabled":
            if sandbox_result != "pass":
                raise SandboxRequiredError("Sandbox pass required for enabled state")
            if not policy_approval:
                raise PolicyDeniedError("Policy approval required for enabled state")

        record.metadata.status = SkillStatus(to_status)
        record.updated_at = datetime.now(UTC)

        audit_ref = self._audit.append(
            action="transition_skill_state",
            object_id=skill_id,
            result="success",
        )
        record.audit_refs.append(audit_ref)
        self._save()

        return StateTransitionResponse(
            context=request.context,
            skill_id=skill_id,
            from_status=from_status,
            to_status=to_status,
            audit_ref=audit_ref,
        )

    def get_skill(self, skill_id: str) -> SkillRecord | None:
        """Get skill metadata from Registry truth source.

        Supports lookup by skill_id (e.g., "S09") or name (e.g., "resilience-degradation").
        """
        # Try by skill_id first
        record = self._skills.get(skill_id)
        if record is not None:
            return record

        # Try by name index
        mapped_id = self._by_name.get(skill_id)
        if mapped_id is not None:
            return self._skills.get(mapped_id)

        return None

    def is_enabled(self, skill_id: str) -> bool:
        """Check if skill version is routable by Execution Engine."""
        record = self._skills.get(skill_id)
        return record is not None and record.metadata.status == SkillStatus.ENABLED

    def get_supply_chain_evidence(self, skill_id: str) -> dict | None:
        """Get supply chain evidence for a skill.

        Returns dict with: skill_id, evidence (set), missing, is_complete.
        """
        record = self._skills.get(skill_id)
        if not record:
            return None
        missing = REQUIRED_EVIDENCE - record.evidence
        return {
            "skill_id": skill_id,
            "evidence": sorted(record.evidence),
            "missing": sorted(missing),
            "is_complete": len(missing) == 0,
        }

    def verify_evidence_integrity(self, skill_id: str) -> list[str]:
        """Verify supply chain evidence integrity for a skill.

        Returns list of issues found (empty = all valid).
        """
        record = self._skills.get(skill_id)
        if not record:
            return [f"Skill not found: {skill_id}"]

        issues = []
        missing = REQUIRED_EVIDENCE - record.evidence
        if missing:
            issues.append(f"Missing evidence: {sorted(missing)}")

        # Check security metadata fields
        security = record.metadata.security
        if not security.get("sbom_ref") and not security.get("sbom"):
            if "SPDX SBOM" in record.evidence:
                issues.append("SBOM evidence claimed but no sbom_ref/sbom field")
        if not security.get("signature_ref") and not security.get("signature") and not security.get("digest"):
            if "signature" in record.evidence:
                issues.append("Signature evidence claimed but no signature field")

        return issues


# Backward-compatible alias
SkillRegistry = Registry
