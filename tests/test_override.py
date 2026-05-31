"""Tests for EmergencyOverride — 紧急降权协议。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from skillpool.paradigm.override import (
    EmergencyOverride,
    GateFile,
    OverrideEvent,
    OverrideLevel,
    OverrideTrigger,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def gate_dir(tmp_path: Path) -> Path:
    """Isolated gate directory under pytest's tmp_path."""
    d = tmp_path / "gates"
    d.mkdir()
    return d


@pytest.fixture
def override(gate_dir: Path) -> EmergencyOverride:
    """EmergencyOverride with isolated gate_dir."""
    return EmergencyOverride(gate_dir=gate_dir)


# ---------------------------------------------------------------------------
# 1. override() creates OverrideEvent with correct trust reduction
# ---------------------------------------------------------------------------

class TestOverride:
    def test_creates_event_with_correct_fields(self, override: EmergencyOverride) -> None:
        ev = override.override(
            trigger=OverrideTrigger.SECURITY_EVENT,
            level=OverrideLevel.WARN,
            target_skill="skill-a",
            target_agent="agent-1",
            reason="suspicious activity",
            current_trust=3,
        )
        assert isinstance(ev, OverrideEvent)
        assert ev.trigger == OverrideTrigger.SECURITY_EVENT
        assert ev.level == OverrideLevel.WARN
        assert ev.target_skill == "skill-a"
        assert ev.target_agent == "agent-1"
        assert ev.original_trust == 3
        assert ev.new_trust == 2  # WARN: trust - 1
        assert ev.reason == "suspicious activity"

    def test_trust_reduction_warn(self, override: EmergencyOverride) -> None:
        ev = override.override(
            trigger=OverrideTrigger.MANUAL,
            level=OverrideLevel.WARN,
            target_skill="s1",
            current_trust=3,
        )
        assert ev.new_trust == 2

    def test_trust_reduction_degrade(self, override: EmergencyOverride) -> None:
        ev = override.override(
            trigger=OverrideTrigger.MANUAL,
            level=OverrideLevel.DEGRADE,
            target_skill="s2",
            current_trust=3,
        )
        assert ev.new_trust == 1

    def test_trust_reduction_quarantine(self, override: EmergencyOverride) -> None:
        ev = override.override(
            trigger=OverrideTrigger.SECURITY_EVENT,
            level=OverrideLevel.QUARANTINE,
            target_skill="s3",
            current_trust=3,
        )
        assert ev.new_trust == 0

    def test_trust_reduction_kill(self, override: EmergencyOverride) -> None:
        ev = override.override(
            trigger=OverrideTrigger.UNRECOVERABLE_ERROR,
            level=OverrideLevel.KILL,
            target_skill="s4",
            current_trust=3,
        )
        assert ev.new_trust == 0


# ---------------------------------------------------------------------------
# 2. is_blocked() returns true after quarantine/kill
# ---------------------------------------------------------------------------

class TestIsBlocked:
    def test_blocked_after_quarantine(self, override: EmergencyOverride) -> None:
        override.override(
            trigger=OverrideTrigger.SECURITY_EVENT,
            level=OverrideLevel.QUARANTINE,
            target_skill="bq",
            current_trust=3,
        )
        assert override.is_blocked("bq") is True

    def test_blocked_after_kill(self, override: EmergencyOverride) -> None:
        override.override(
            trigger=OverrideTrigger.UNRECOVERABLE_ERROR,
            level=OverrideLevel.KILL,
            target_skill="bk",
            current_trust=3,
        )
        assert override.is_blocked("bk") is True

    def test_not_blocked_after_warn(self, override: EmergencyOverride) -> None:
        override.override(
            trigger=OverrideTrigger.MANUAL,
            level=OverrideLevel.WARN,
            target_skill="bw",
            current_trust=3,
        )
        assert override.is_blocked("bw") is False

    def test_not_blocked_after_degrade(self, override: EmergencyOverride) -> None:
        override.override(
            trigger=OverrideTrigger.RESOURCE_EXHAUSTION,
            level=OverrideLevel.DEGRADE,
            target_skill="bd",
            current_trust=3,
        )
        assert override.is_blocked("bd") is False

    def test_not_blocked_by_default(self, override: EmergencyOverride) -> None:
        assert override.is_blocked("unknown-skill") is False


# ---------------------------------------------------------------------------
# 3. get_trust_level() reflects override
# ---------------------------------------------------------------------------

class TestGetTrustLevel:
    def test_reflects_warn(self, override: EmergencyOverride) -> None:
        override.override(
            trigger=OverrideTrigger.MANUAL,
            level=OverrideLevel.WARN,
            target_skill="tw",
            current_trust=3,
        )
        assert override.get_trust_level("tw") == 2

    def test_reflects_degrade(self, override: EmergencyOverride) -> None:
        override.override(
            trigger=OverrideTrigger.MANUAL,
            level=OverrideLevel.DEGRADE,
            target_skill="td",
            current_trust=3,
        )
        assert override.get_trust_level("td") == 1

    def test_reflects_quarantine(self, override: EmergencyOverride) -> None:
        override.override(
            trigger=OverrideTrigger.MANUAL,
            level=OverrideLevel.QUARANTINE,
            target_skill="tq",
            current_trust=3,
        )
        assert override.get_trust_level("tq") == 0

    def test_default_trust_for_unknown(self, override: EmergencyOverride) -> None:
        assert override.get_trust_level("never-overridden") == 3


# ---------------------------------------------------------------------------
# 4. restore() resets trust_level
# ---------------------------------------------------------------------------

class TestRestore:
    def test_restore_resets_trust_and_unblocks(self, override: EmergencyOverride) -> None:
        override.override(
            trigger=OverrideTrigger.SECURITY_EVENT,
            level=OverrideLevel.QUARANTINE,
            target_skill="rs",
            current_trust=3,
        )
        assert override.is_blocked("rs") is True

        result = override.restore("rs", trust_level=3)
        assert result is True
        assert override.get_trust_level("rs") == 3
        assert override.is_blocked("rs") is False

    def test_restore_nonexistent_returns_false(self, override: EmergencyOverride) -> None:
        """restore() returns False for non-existent skills (no-op)."""
        result = override.restore("ghost", trust_level=2)
        assert result is False  # No gate file to restore
        assert override.get_trust_level("ghost") == 3  # Returns default trust


# ---------------------------------------------------------------------------
# 5. check_expired() auto-restores expired overrides (short TTL)
# ---------------------------------------------------------------------------

class TestCheckExpired:
    def test_auto_restores_expired(self, gate_dir: Path) -> None:
        eo = EmergencyOverride(gate_dir=gate_dir)
        eo.override(
            trigger=OverrideTrigger.RESOURCE_EXHAUSTION,
            level=OverrideLevel.WARN,
            target_skill="exp",
            current_trust=3,
            ttl_seconds=1,
        )
        assert eo.get_trust_level("exp") == 2

        time.sleep(1.5)

        expired = eo.check_expired()
        assert "exp" in expired
        assert eo.get_trust_level("exp") == 3
        assert eo.is_blocked("exp") is False

    def test_non_expired_stays(self, override: EmergencyOverride) -> None:
        override.override(
            trigger=OverrideTrigger.MANUAL,
            level=OverrideLevel.WARN,
            target_skill="noexp",
            current_trust=3,
            ttl_seconds=3600,
        )
        expired = override.check_expired()
        assert "noexp" not in expired
        assert override.get_trust_level("noexp") == 2

    def test_no_ttl_never_expires(self, override: EmergencyOverride) -> None:
        override.override(
            trigger=OverrideTrigger.MANUAL,
            level=OverrideLevel.WARN,
            target_skill="perma",
            current_trust=3,
        )
        expired = override.check_expired()
        assert "perma" not in expired


# ---------------------------------------------------------------------------
# 6. Gate file JSON persistence
# ---------------------------------------------------------------------------

class TestGateFilePersistence:
    def test_override_writes_gate_file(self, gate_dir: Path) -> None:
        eo = EmergencyOverride(gate_dir=gate_dir)
        eo.override(
            trigger=OverrideTrigger.SECURITY_EVENT,
            level=OverrideLevel.QUARANTINE,
            target_skill="persist-skill",
            current_trust=3,
        )
        gate_path = gate_dir / "persist-skill.json"
        assert gate_path.exists()

        data = json.loads(gate_path.read_text())
        assert data["skill_id"] == "persist-skill"
        assert data["trust_level"] == 0
        assert data["blocked"] is False

    def test_new_override_reads_existing_gate(self, gate_dir: Path) -> None:
        eo1 = EmergencyOverride(gate_dir=gate_dir)
        eo1.override(
            trigger=OverrideTrigger.MANUAL,
            level=OverrideLevel.WARN,
            target_skill="shared",
            current_trust=3,
        )

        # Second instance reads from same dir
        eo2 = EmergencyOverride(gate_dir=gate_dir)
        assert eo2.get_trust_level("shared") == 2
        assert eo2.is_blocked("shared") is False


# ---------------------------------------------------------------------------
# 7. _compute_new_trust for WARN/DEGRADE/QUARANTINE/KILL
# ---------------------------------------------------------------------------

class TestComputeNewTrust:
    @pytest.mark.parametrize(
        "level, current, expected",
        [
            (OverrideLevel.WARN, 3, 2),
            (OverrideLevel.WARN, 1, 0),
            (OverrideLevel.WARN, 0, 0),
            (OverrideLevel.DEGRADE, 3, 1),
            (OverrideLevel.DEGRADE, 2, 0),
            (OverrideLevel.DEGRADE, 0, 0),
            (OverrideLevel.QUARANTINE, 3, 0),
            (OverrideLevel.QUARANTINE, 1, 0),
            (OverrideLevel.QUARANTINE, 0, 0),
            (OverrideLevel.KILL, 3, 0),
            (OverrideLevel.KILL, 0, 0),
        ],
    )
    def test_trust_computation(
        self,
        override: EmergencyOverride,
        level: OverrideLevel,
        current: int,
        expected: int,
    ) -> None:
        assert override._compute_new_trust(current, level) == expected


# ---------------------------------------------------------------------------
# 8. OverrideLevel and OverrideTrigger enums
# ---------------------------------------------------------------------------

class TestEnums:
    def test_override_level_values(self) -> None:
        assert OverrideLevel.WARN.value == "warn"
        assert OverrideLevel.DEGRADE.value == "degrade"
        assert OverrideLevel.QUARANTINE.value == "quarantine"
        assert OverrideLevel.KILL.value == "kill"
        assert len(OverrideLevel) == 4

    def test_override_trigger_values(self) -> None:
        assert OverrideTrigger.SECURITY_EVENT.value == "security_event"
        assert OverrideTrigger.RESOURCE_EXHAUSTION.value == "resource_exhaustion"
        assert OverrideTrigger.UNRECOVERABLE_ERROR.value == "unrecoverable_error"
        assert OverrideTrigger.MANUAL.value == "manual"
        assert len(OverrideTrigger) == 4


# ---------------------------------------------------------------------------
# 9. GateFile to_dict / from_dict roundtrip
# ---------------------------------------------------------------------------

class TestGateFileRoundtrip:
    def test_roundtrip(self) -> None:
        original = GateFile(
            skill_id="rt-skill",
            trust_level=1,
            blocked=True,
            override_history=[
                {"level": "warn", "timestamp": "2026-01-01T00:00:00"},
                {"level": "degrade", "timestamp": "2026-01-02T00:00:00"},
            ],
        )
        d = original.to_dict()
        restored = GateFile.from_dict(d)

        assert restored.skill_id == original.skill_id
        assert restored.trust_level == original.trust_level
        assert restored.blocked == original.blocked
        assert restored.override_history == original.override_history

    def test_to_dict_structure(self) -> None:
        gf = GateFile(
            skill_id="struct-skill",
            trust_level=2,
            blocked=False,
            override_history=[],
        )
        d = gf.to_dict()
        assert set(d.keys()) == {"skill_id", "trust_level", "blocked", "override_history"}
        assert isinstance(d["override_history"], list)

    def test_empty_history_roundtrip(self) -> None:
        gf = GateFile(skill_id="empty", trust_level=3, blocked=False, override_history=[])
        restored = GateFile.from_dict(gf.to_dict())
        assert restored.override_history == []
