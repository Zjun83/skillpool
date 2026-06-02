"""Tests for combiner module — combination lifecycle + data models."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from skillpool.combiner.models import (
    CombinationLifecycleState,
    SkillCombination,
    CombinationTransitionResult,
    MIN_VALIDATION_EXECUTIONS,
)
from skillpool.combiner.lifecycle import CombinationLifecycleManager
from skillpool.utils.time_utils import utc_now


class TestCombinationModels:
    """Tests for SkillCombination and related models."""

    def test_combination_id_auto_generated(self):
        combo = SkillCombination(primary="review", enhancers=["karpathy"])
        assert combo.combination_id == "review+karpathy"

    def test_combination_id_with_multiple_enhancers(self):
        combo = SkillCombination(primary="review", enhancers=["simplify", "karpathy"])
        assert combo.combination_id == "review+karpathy+simplify"  # sorted

    def test_initial_state_discovered(self):
        combo = SkillCombination(primary="review", enhancers=["karpathy"])
        assert combo.state == CombinationLifecycleState.DISCOVERED

    def test_initial_state_validating_for_human(self):
        combo = SkillCombination(
            primary="review", enhancers=["karpathy"],
            state=CombinationLifecycleState.VALIDATING,
        )
        assert combo.state == CombinationLifecycleState.VALIDATING

    def test_current_weight_zero_for_rejected(self):
        combo = SkillCombination(
            primary="review", enhancers=["karpathy"],
            state=CombinationLifecycleState.REJECTED,
        )
        assert combo.current_weight() == 0.0

    def test_current_weight_promoted_with_confidence(self):
        combo = SkillCombination(
            primary="review", enhancers=["karpathy"],
            state=CombinationLifecycleState.PROMOTED,
            execution_count=10,
            base_weight=0.8,
        )
        weight = combo.current_weight()
        assert 0 < weight <= 0.8

    def test_current_weight_low_executions(self):
        combo = SkillCombination(
            primary="review", enhancers=["karpathy"],
            state=CombinationLifecycleState.PROMOTED,
            execution_count=2,
            base_weight=0.8,
        )
        weight = combo.current_weight()
        # confidence_factor = min(1.0, 2/5) = 0.4
        assert weight < 0.8 * 0.4 + 0.01  # Allow for time decay

    def test_lifecycle_state_values(self):
        assert CombinationLifecycleState.DISCOVERED == 0
        assert CombinationLifecycleState.VALIDATING == 1
        assert CombinationLifecycleState.PROMOTED == 2
        assert CombinationLifecycleState.REJECTED == 3
        assert CombinationLifecycleState.DEPRECATED == 4
        assert CombinationLifecycleState.RETIRED == 5

    def test_min_validation_executions(self):
        assert MIN_VALIDATION_EXECUTIONS == 5

    def test_transition_result_model(self):
        result = CombinationTransitionResult(
            combination_id="review+karpathy",
            from_state=CombinationLifecycleState.VALIDATING,
            to_state=CombinationLifecycleState.PROMOTED,
            success=True,
            reason="Gain=1.5, Confidence=0.8",
        )
        assert result.success is True


class TestCombinationLifecycleManager:
    """Tests for CombinationLifecycleManager."""

    @pytest.fixture
    def data_dir(self, tmp_path):
        return tmp_path / "combinations"

    @pytest.fixture
    def manager(self, data_dir):
        return CombinationLifecycleManager(data_dir=data_dir)

    def test_create_auto_discovered_combination(self, manager):
        combo = manager.create_combination("review", ["karpathy"])
        assert combo.state == CombinationLifecycleState.DISCOVERED
        assert combo.source == "auto_discovered"

    def test_create_human_specified_combination(self, manager):
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified"
        )
        assert combo.state == CombinationLifecycleState.VALIDATING
        assert combo.source == "human_specified"

    def test_create_duplicate_combination(self, manager):
        combo1 = manager.create_combination("review", ["karpathy"])
        combo2 = manager.create_combination("review", ["karpathy"])
        assert combo1.combination_id == combo2.combination_id

    def test_valid_transitions(self, manager):
        assert manager.validate_transition(
            CombinationLifecycleState.DISCOVERED,
            CombinationLifecycleState.VALIDATING,
        )
        assert manager.validate_transition(
            CombinationLifecycleState.VALIDATING,
            CombinationLifecycleState.PROMOTED,
        )
        assert manager.validate_transition(
            CombinationLifecycleState.VALIDATING,
            CombinationLifecycleState.REJECTED,
        )
        assert manager.validate_transition(
            CombinationLifecycleState.PROMOTED,
            CombinationLifecycleState.DEPRECATED,
        )

    def test_invalid_transitions(self, manager):
        assert not manager.validate_transition(
            CombinationLifecycleState.DISCOVERED,
            CombinationLifecycleState.PROMOTED,
        )
        assert not manager.validate_transition(
            CombinationLifecycleState.RETIRED,
            CombinationLifecycleState.DISCOVERED,
        )
        assert not manager.validate_transition(
            CombinationLifecycleState.PROMOTED,
            CombinationLifecycleState.DISCOVERED,
        )

    def test_transition_discovered_to_validating(self, manager):
        combo = manager.create_combination("review", ["karpathy"])
        result = manager.transition(
            combo.combination_id,
            CombinationLifecycleState.VALIDATING,
        )
        assert result.success
        assert result.to_state == CombinationLifecycleState.VALIDATING

    def test_transition_invalid_path(self, manager):
        combo = manager.create_combination("review", ["karpathy"])
        result = manager.transition(
            combo.combination_id,
            CombinationLifecycleState.PROMOTED,
        )
        assert not result.success
        assert "Invalid transition" in result.reason

    def test_record_execution_auto_transitions(self, manager):
        combo = manager.create_combination("review", ["karpathy"])
        assert combo.state == CombinationLifecycleState.DISCOVERED
        updated = manager.record_execution(combo.combination_id, gain=1.0)
        assert updated.state == CombinationLifecycleState.VALIDATING

    def test_record_execution_updates_stats(self, manager):
        combo = manager.create_combination("review", ["karpathy"])
        manager.record_execution(combo.combination_id, gain=2.0)
        manager.record_execution(combo.combination_id, gain=1.0)
        updated = manager.get_combination(combo.combination_id)
        assert updated.execution_count == 2
        assert updated.gain_avg == pytest.approx(1.5, abs=0.01)
        assert updated.gain_confidence == pytest.approx(0.4, abs=0.01)

    def test_try_promote_not_enough_executions(self, manager):
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified"
        )
        for i in range(3):
            manager.record_execution(combo.combination_id, gain=1.5)
        result = manager.try_promote(combo.combination_id)
        assert not result.success
        assert "executions" in result.reason.lower()

    def test_try_promote_negative_gain_rejected(self, manager):
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified"
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=-0.5)
        result = manager.try_promote(combo.combination_id)
        assert result.to_state == CombinationLifecycleState.REJECTED

    def test_try_promote_success(self, manager):
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified"
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.5)
        result = manager.try_promote(combo.combination_id)
        assert result.success
        assert result.to_state == CombinationLifecycleState.PROMOTED

    def test_get_promoted_combinations(self, manager):
        combo1 = manager.create_combination(
            "review", ["karpathy"], source="human_specified"
        )
        for i in range(6):
            manager.record_execution(combo1.combination_id, gain=1.5)
        manager.try_promote(combo1.combination_id)

        combo2 = manager.create_combination("review", ["simplify"])
        # combo2 is still DISCOVERED

        promoted = manager.get_promoted_combinations("review")
        assert len(promoted) == 1
        assert promoted[0].combination_id == combo1.combination_id

    def test_get_combinations_for_skill(self, manager):
        combo1 = manager.create_combination("review", ["karpathy"])
        combo2 = manager.create_combination("security", ["review"])

        combos = manager.get_combinations_for_skill("review")
        assert len(combos) == 2

    def test_persistence(self, data_dir):
        manager1 = CombinationLifecycleManager(data_dir=data_dir)
        combo = manager1.create_combination(
            "review", ["karpathy"], source="human_specified"
        )
        for i in range(6):
            manager1.record_execution(combo.combination_id, gain=1.5)
        manager1.try_promote(combo.combination_id)

        # New manager instance should load from disk
        manager2 = CombinationLifecycleManager(data_dir=data_dir)
        loaded = manager2.get_combination(combo.combination_id)
        assert loaded is not None
        assert loaded.state == CombinationLifecycleState.PROMOTED

    def test_record_execution_nonexistent(self, manager):
        result = manager.record_execution("nonexistent+combo", gain=1.0)
        assert result is None

    def test_deprecated_to_retired(self, manager):
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified"
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.5)
        manager.try_promote(combo.combination_id)

        # Manually deprecate
        manager.transition(
            combo.combination_id,
            CombinationLifecycleState.DEPRECATED,
            reason="Test deprecation",
        )
        # Check retirement (would need 90 days to auto-trigger, so test transition directly)
        result = manager.transition(
            combo.combination_id,
            CombinationLifecycleState.RETIRED,
            reason="Test retirement",
        )
        assert result.success
        assert result.to_state == CombinationLifecycleState.RETIRED


# ── Extended model tests ──


class TestCombinationModelsExtended:
    """Extended tests for SkillCombination model edge cases."""

    def test_combination_id_explicit_overrides_auto(self):
        """If combination_id is provided explicitly, it should not be overwritten."""
        combo = SkillCombination(
            combination_id="custom-id",
            primary="review",
            enhancers=["karpathy"],
        )
        assert combo.combination_id == "custom-id"

    def test_discovered_at_auto_set(self):
        """discovered_at should be set automatically if not provided."""
        combo = SkillCombination(primary="review", enhancers=["karpathy"])
        assert combo.discovered_at != ""

    def test_discovered_at_preserved_if_set(self):
        """If discovered_at is provided, it should not be overwritten."""
        ts = "2026-01-01T00:00:00"
        combo = SkillCombination(
            primary="review", enhancers=["karpathy"], discovered_at=ts,
        )
        assert combo.discovered_at == ts

    def test_gain_confidence_bounds(self):
        """gain_confidence must be between 0.0 and 1.0."""
        combo = SkillCombination(
            primary="review", enhancers=["karpathy"], gain_confidence=0.5,
        )
        assert combo.gain_confidence == 0.5

        with pytest.raises(Exception):
            SkillCombination(
                primary="review", enhancers=["karpathy"], gain_confidence=1.5,
            )

        with pytest.raises(Exception):
            SkillCombination(
                primary="review", enhancers=["karpathy"], gain_confidence=-0.1,
            )

    def test_base_weight_bounds(self):
        """base_weight must be between 0.0 and 1.0."""
        with pytest.raises(Exception):
            SkillCombination(
                primary="review", enhancers=["karpathy"], base_weight=1.5,
            )

        with pytest.raises(Exception):
            SkillCombination(
                primary="review", enhancers=["karpathy"], base_weight=-0.1,
            )

    def test_current_weight_zero_for_discovered(self):
        combo = SkillCombination(
            primary="review", enhancers=["karpathy"],
            state=CombinationLifecycleState.DISCOVERED,
        )
        assert combo.current_weight() == 0.0

    def test_current_weight_zero_for_deprecated(self):
        combo = SkillCombination(
            primary="review", enhancers=["karpathy"],
            state=CombinationLifecycleState.DEPRECATED,
        )
        assert combo.current_weight() == 0.0

    def test_current_weight_zero_for_retired(self):
        combo = SkillCombination(
            primary="review", enhancers=["karpathy"],
            state=CombinationLifecycleState.RETIRED,
        )
        assert combo.current_weight() == 0.0

    def test_current_weight_validating_with_executions(self):
        """Validating combination should have non-zero weight with executions."""
        combo = SkillCombination(
            primary="review", enhancers=["karpathy"],
            state=CombinationLifecycleState.VALIDATING,
            execution_count=10,
            base_weight=0.8,
        )
        weight = combo.current_weight()
        assert weight > 0

    def test_current_weight_time_decay(self):
        """Weight should decay over time since last execution."""
        now = utc_now()
        recent_ts = now.isoformat()
        old_ts = (now - timedelta(days=50)).isoformat()

        combo_recent = SkillCombination(
            primary="review", enhancers=["karpathy"],
            state=CombinationLifecycleState.PROMOTED,
            execution_count=10,
            base_weight=0.8,
            last_execution=recent_ts,
        )
        combo_old = SkillCombination(
            primary="review", enhancers=["karpathy"],
            state=CombinationLifecycleState.PROMOTED,
            execution_count=10,
            base_weight=0.8,
            last_execution=old_ts,
        )
        assert combo_recent.current_weight() > combo_old.current_weight()

    def test_current_weight_decay_floor(self):
        """Time decay should not go below 0.1."""
        very_old_ts = (utc_now() - timedelta(days=500)).isoformat()
        combo = SkillCombination(
            primary="review", enhancers=["karpathy"],
            state=CombinationLifecycleState.PROMOTED,
            execution_count=10,
            base_weight=0.8,
            last_execution=very_old_ts,
        )
        weight = combo.current_weight()
        # base_weight * max(0.1, ...) * confidence_factor
        # With decay_lambda=0.01, 500 days => 1.0 - 0.01*500 = -4.0, clamped to 0.1
        # confidence_factor = min(1.0, 10/5) = 1.0
        assert weight == pytest.approx(0.8 * 0.1 * 1.0)

    def test_current_weight_no_execution(self):
        """PROMOTED with no last_execution gets time_decay=0.5."""
        combo = SkillCombination(
            primary="review", enhancers=["karpathy"],
            state=CombinationLifecycleState.PROMOTED,
            execution_count=10,
            base_weight=0.8,
            last_execution="",
        )
        weight = combo.current_weight()
        assert weight == pytest.approx(0.8 * 0.5 * 1.0)

    def test_current_weight_invalid_last_execution(self):
        """Invalid last_execution timestamp falls back to time_decay=1.0."""
        combo = SkillCombination(
            primary="review", enhancers=["karpathy"],
            state=CombinationLifecycleState.PROMOTED,
            execution_count=10,
            base_weight=0.8,
            last_execution="not-a-date",
        )
        weight = combo.current_weight()
        # time_decay=1.0, confidence_factor=1.0
        assert weight == pytest.approx(0.8 * 1.0 * 1.0)

    def test_model_serialization_roundtrip(self):
        """SkillCombination should survive JSON roundtrip."""
        combo = SkillCombination(
            primary="review",
            enhancers=["karpathy"],
            state=CombinationLifecycleState.VALIDATING,
            gain_avg=1.5,
            gain_confidence=0.8,
            execution_count=7,
        )
        data = json.loads(combo.model_dump_json())
        restored = SkillCombination(**data)
        assert restored.combination_id == combo.combination_id
        assert restored.primary == combo.primary
        assert restored.enhancers == combo.enhancers
        assert restored.state == combo.state
        assert restored.gain_avg == combo.gain_avg
        assert restored.execution_count == combo.execution_count

    def test_enhancers_empty_list(self):
        """Combination with no enhancers."""
        combo = SkillCombination(primary="review", enhancers=[])
        assert combo.combination_id == "review+"

    def test_transition_result_defaults(self):
        """CombinationTransitionResult defaults."""
        result = CombinationTransitionResult(
            combination_id="test",
            from_state=CombinationLifecycleState.DISCOVERED,
            to_state=CombinationLifecycleState.VALIDATING,
        )
        assert result.success is True
        assert result.reason == ""


# ── Extended lifecycle manager tests ──


class TestCombinationLifecycleManagerExtended:
    """Extended tests for CombinationLifecycleManager edge cases and missing paths."""

    @pytest.fixture
    def data_dir(self, tmp_path):
        return tmp_path / "combinations"

    @pytest.fixture
    def manager(self, data_dir):
        return CombinationLifecycleManager(data_dir=data_dir)

    # ── create_combination edge cases ──

    def test_create_retired_combination_rediscovery(self, manager):
        """A retired combination can be rediscovered, going back to DISCOVERED."""
        combo = manager.create_combination("review", ["karpathy"])
        # Force into RETIRED via transitions
        combo.state = CombinationLifecycleState.VALIDATING
        manager._update_persisted(combo)
        manager.transition(combo.combination_id, CombinationLifecycleState.RETIRED)

        # Re-create the same combination
        rediscovered = manager.create_combination("review", ["karpathy"])
        assert rediscovered.state == CombinationLifecycleState.DISCOVERED
        assert rediscovered.source == "auto_discovered"

    def test_create_retired_combination_with_human_source(self, manager):
        """Rediscovery of retired combination with human source also goes to DISCOVERED."""
        combo = manager.create_combination("review", ["karpathy"])
        combo.state = CombinationLifecycleState.VALIDATING
        manager._update_persisted(combo)
        manager.transition(combo.combination_id, CombinationLifecycleState.RETIRED)

        rediscovered = manager.create_combination(
            "review", ["karpathy"], source="human_specified"
        )
        # Even human_specified source on rediscovery goes to DISCOVERED
        assert rediscovered.state == CombinationLifecycleState.DISCOVERED

    def test_create_with_custom_base_weight(self, manager):
        combo = manager.create_combination(
            "review", ["karpathy"], base_weight=0.9,
        )
        assert combo.base_weight == 0.9

    # ── validate_transition ──

    def test_same_state_transition_is_invalid(self, manager):
        """Transitioning to the same state is not valid."""
        assert not manager.validate_transition(
            CombinationLifecycleState.DISCOVERED,
            CombinationLifecycleState.DISCOVERED,
        )
        assert not manager.validate_transition(
            CombinationLifecycleState.PROMOTED,
            CombinationLifecycleState.PROMOTED,
        )

    def test_rejected_to_discovered_is_valid(self, manager):
        assert manager.validate_transition(
            CombinationLifecycleState.REJECTED,
            CombinationLifecycleState.DISCOVERED,
        )

    def test_deprecated_to_promoted_is_valid(self, manager):
        """DEPRECATED can be re-promoted if gain recovers."""
        assert manager.validate_transition(
            CombinationLifecycleState.DEPRECATED,
            CombinationLifecycleState.PROMOTED,
        )

    def test_deprecated_to_retired_is_valid(self, manager):
        assert manager.validate_transition(
            CombinationLifecycleState.DEPRECATED,
            CombinationLifecycleState.RETIRED,
        )

    def test_retired_no_outgoing_transitions(self, manager):
        """RETIRED is a terminal state with no valid transitions."""
        for target in CombinationLifecycleState:
            if target == CombinationLifecycleState.RETIRED:
                continue
            assert not manager.validate_transition(
                CombinationLifecycleState.RETIRED, target,
            )

    # ── transition ──

    def test_transition_nonexistent_combination(self, manager):
        result = manager.transition(
            "nonexistent+combo", CombinationLifecycleState.VALIDATING,
        )
        assert not result.success
        assert "not found" in result.reason.lower()

    def test_transition_sets_promoted_at(self, manager):
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.5)
        manager.try_promote(combo.combination_id)

        loaded = manager.get_combination(combo.combination_id)
        assert loaded.promoted_at != ""

    def test_transition_sets_deprecated_at(self, manager):
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.5)
        manager.try_promote(combo.combination_id)
        manager.transition(combo.combination_id, CombinationLifecycleState.DEPRECATED)

        loaded = manager.get_combination(combo.combination_id)
        assert loaded.deprecated_at != ""

    def test_transition_sets_rejection_reason(self, manager):
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=-0.5)
        result = manager.try_promote(combo.combination_id)

        loaded = manager.get_combination(combo.combination_id)
        assert loaded.rejection_reason != ""

    def test_transition_to_discovered_resets_validation_data(self, manager):
        """REJECTED → DISCOVERED should reset gain data."""
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.0)
        # Reject it
        manager.transition(combo.combination_id, CombinationLifecycleState.REJECTED)
        # Rediscover it
        manager.transition(combo.combination_id, CombinationLifecycleState.DISCOVERED)

        loaded = manager.get_combination(combo.combination_id)
        assert loaded.gain_avg == 0.0
        assert loaded.gain_confidence == 0.0
        assert loaded.execution_count == 0
        assert loaded.rejection_reason == ""

    # ── record_execution ──

    def test_record_execution_rolling_average(self, manager):
        """Test that gain_avg is a rolling average."""
        combo = manager.create_combination("review", ["karpathy"])
        manager.record_execution(combo.combination_id, gain=2.0)
        loaded = manager.get_combination(combo.combination_id)
        assert loaded.gain_avg == pytest.approx(2.0)

        manager.record_execution(combo.combination_id, gain=4.0)
        loaded = manager.get_combination(combo.combination_id)
        assert loaded.gain_avg == pytest.approx(3.0)

        manager.record_execution(combo.combination_id, gain=1.0)
        loaded = manager.get_combination(combo.combination_id)
        # (2.0 + 4.0 + 1.0) / 3 = 2.333...
        assert loaded.gain_avg == pytest.approx(7.0 / 3.0, abs=0.01)

    def test_record_execution_confidence_caps_at_one(self, manager):
        """Confidence should never exceed 1.0."""
        combo = manager.create_combination("review", ["karpathy"])
        for i in range(20):
            manager.record_execution(combo.combination_id, gain=1.0)
        loaded = manager.get_combination(combo.combination_id)
        assert loaded.gain_confidence == 1.0

    def test_record_execution_updates_last_execution(self, manager):
        combo = manager.create_combination("review", ["karpathy"])
        assert combo.last_execution == ""
        manager.record_execution(combo.combination_id, gain=1.0)
        loaded = manager.get_combination(combo.combination_id)
        assert loaded.last_execution != ""

    def test_record_execution_recent_gain_avg(self, manager):
        """recent_gain_avg uses exponential moving average (0.7/0.3)."""
        combo = manager.create_combination("review", ["karpathy"])
        manager.record_execution(combo.combination_id, gain=1.0)
        loaded = manager.get_combination(combo.combination_id)
        # First execution: recent_gain_avg = gain = 1.0
        assert loaded.recent_gain_avg == pytest.approx(1.0)

        manager.record_execution(combo.combination_id, gain=2.0)
        loaded = manager.get_combination(combo.combination_id)
        # Second: 1.0 * 0.7 + 2.0 * 0.3 = 1.3
        assert loaded.recent_gain_avg == pytest.approx(1.3)

    # ── try_promote ──

    def test_try_promote_wrong_state(self, manager):
        """Can't promote a combination that isn't VALIDATING."""
        combo = manager.create_combination("review", ["karpathy"])
        # combo is DISCOVERED, not VALIDATING
        result = manager.try_promote(combo.combination_id)
        assert not result.success
        assert "not VALIDATING" in result.reason

    def test_try_promote_nonexistent(self, manager):
        result = manager.try_promote("nonexistent+combo")
        assert not result.success
        assert "not found" in result.reason.lower()

    def test_try_promote_low_confidence(self, manager):
        """Enough executions but low confidence should fail."""
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        # Record 6 executions but manipulate confidence directly
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.0)
        # Manually set confidence low
        loaded = manager.get_combination(combo.combination_id)
        loaded.gain_confidence = 0.5
        manager._update_persisted(loaded)

        result = manager.try_promote(combo.combination_id)
        assert not result.success
        assert "confidence" in result.reason.lower()

    def test_try_promote_snapshots_all_time_gain(self, manager):
        """On promotion, all_time_gain_avg and recent_gain_avg are snapshotted."""
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.5)
        result = manager.try_promote(combo.combination_id)
        assert result.success

        loaded = manager.get_combination(combo.combination_id)
        assert loaded.all_time_gain_avg == pytest.approx(loaded.gain_avg, abs=0.01)
        assert loaded.recent_gain_avg == pytest.approx(loaded.gain_avg, abs=0.01)

    # ── check_deprecation ──

    def test_check_deprecation_inactivity(self, manager):
        """No execution in 30 days triggers deprecation."""
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.5)
        manager.try_promote(combo.combination_id)

        # Set last_execution to 31 days ago
        loaded = manager.get_combination(combo.combination_id)
        loaded.last_execution = (utc_now() - timedelta(days=31)).isoformat()
        manager._update_persisted(loaded)

        result = manager.check_deprecation(combo.combination_id)
        assert result is not None
        assert result.to_state == CombinationLifecycleState.DEPRECATED
        assert "31 days" in result.reason

    def test_check_deprecation_gain_decay(self, manager):
        """Recent gain < 50% of all-time gain triggers deprecation."""
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.5)
        manager.try_promote(combo.combination_id)

        # Simulate gain decay
        loaded = manager.get_combination(combo.combination_id)
        loaded.all_time_gain_avg = 2.0
        loaded.recent_gain_avg = 0.5  # 25% of all_time_gain_avg
        # Keep last_execution recent to avoid inactivity trigger
        loaded.last_execution = utc_now().isoformat()
        manager._update_persisted(loaded)

        result = manager.check_deprecation(combo.combination_id)
        assert result is not None
        assert result.to_state == CombinationLifecycleState.DEPRECATED
        assert "50%" in result.reason

    def test_check_deprecation_no_decay(self, manager):
        """Healthy combination should not be deprecated."""
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.5)
        manager.try_promote(combo.combination_id)

        # Keep it healthy
        loaded = manager.get_combination(combo.combination_id)
        loaded.last_execution = utc_now().isoformat()
        loaded.all_time_gain_avg = 1.5
        loaded.recent_gain_avg = 1.4  # 93% of all-time, well above 50%
        manager._update_persisted(loaded)

        result = manager.check_deprecation(combo.combination_id)
        assert result is None

    def test_check_deprecation_not_promoted(self, manager):
        """Non-PROMOTED combinations return None."""
        combo = manager.create_combination("review", ["karpathy"])
        result = manager.check_deprecation(combo.combination_id)
        assert result is None

    def test_check_deprecation_nonexistent(self, manager):
        result = manager.check_deprecation("nonexistent+combo")
        assert result is None

    def test_check_deprecation_invalid_last_execution(self, manager):
        """Invalid last_execution timestamp should not crash."""
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.5)
        manager.try_promote(combo.combination_id)

        loaded = manager.get_combination(combo.combination_id)
        loaded.last_execution = "not-a-valid-date"
        loaded.all_time_gain_avg = 1.5
        loaded.recent_gain_avg = 1.4
        manager._update_persisted(loaded)

        # Should not crash, should return None (no deprecation)
        result = manager.check_deprecation(combo.combination_id)
        assert result is None

    # ── check_retirement ──

    def test_check_retirement_after_90_days(self, manager):
        """Deprecated for >90 days triggers retirement."""
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.5)
        manager.try_promote(combo.combination_id)
        manager.transition(combo.combination_id, CombinationLifecycleState.DEPRECATED)

        # Set deprecated_at to 91 days ago
        loaded = manager.get_combination(combo.combination_id)
        loaded.deprecated_at = (utc_now() - timedelta(days=91)).isoformat()
        manager._update_persisted(loaded)

        result = manager.check_retirement(combo.combination_id)
        assert result is not None
        assert result.to_state == CombinationLifecycleState.RETIRED
        assert "91 days" in result.reason

    def test_check_retirement_not_deprecated(self, manager):
        """Non-DEPRECATED combinations return None."""
        combo = manager.create_combination("review", ["karpathy"])
        result = manager.check_retirement(combo.combination_id)
        assert result is None

    def test_check_retirement_nonexistent(self, manager):
        result = manager.check_retirement("nonexistent+combo")
        assert result is None

    def test_check_retirement_too_recent(self, manager):
        """Recently deprecated (<90 days) should not be retired."""
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.5)
        manager.try_promote(combo.combination_id)
        manager.transition(combo.combination_id, CombinationLifecycleState.DEPRECATED)

        result = manager.check_retirement(combo.combination_id)
        assert result is None

    def test_check_retirement_invalid_deprecated_at(self, manager):
        """Invalid deprecated_at should not crash."""
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=1.5)
        manager.try_promote(combo.combination_id)
        manager.transition(combo.combination_id, CombinationLifecycleState.DEPRECATED)

        loaded = manager.get_combination(combo.combination_id)
        loaded.deprecated_at = "not-a-valid-date"
        manager._update_persisted(loaded)

        result = manager.check_retirement(combo.combination_id)
        assert result is None

    # ── get_validating_combinations ──

    def test_get_validating_combinations(self, manager):
        combo1 = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        combo2 = manager.create_combination(
            "security", ["simplify"], source="human_specified",
        )
        combo3 = manager.create_combination("review", ["simplify"])

        validating = manager.get_validating_combinations()
        ids = {c.combination_id for c in validating}
        assert combo1.combination_id in ids
        assert combo2.combination_id in ids
        assert combo3.combination_id not in ids  # DISCOVERED, not VALIDATING

    def test_get_validating_combinations_empty(self, manager):
        result = manager.get_validating_combinations()
        assert result == []

    # ── get_promoted_combinations ──

    def test_get_promoted_combinations_sorted_by_weight(self, manager):
        """Promoted combinations should be sorted by weight descending."""
        combo1 = manager.create_combination(
            "review", ["karpathy"], source="human_specified", base_weight=0.5,
        )
        combo2 = manager.create_combination(
            "review", ["simplify"], source="human_specified", base_weight=0.9,
        )
        for i in range(6):
            manager.record_execution(combo1.combination_id, gain=1.5)
            manager.record_execution(combo2.combination_id, gain=1.5)
        manager.try_promote(combo1.combination_id)
        manager.try_promote(combo2.combination_id)

        promoted = manager.get_promoted_combinations()
        assert len(promoted) == 2
        assert promoted[0].base_weight >= promoted[1].base_weight

    def test_get_promoted_combinations_no_primary_filter(self, manager):
        """Without primary filter, all promoted combinations are returned."""
        combo1 = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        combo2 = manager.create_combination(
            "security", ["simplify"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo1.combination_id, gain=1.5)
            manager.record_execution(combo2.combination_id, gain=1.5)
        manager.try_promote(combo1.combination_id)
        manager.try_promote(combo2.combination_id)

        promoted = manager.get_promoted_combinations()
        assert len(promoted) == 2

    # ── full lifecycle workflow ──

    def test_full_lifecycle_discovered_to_retired(self, manager):
        """Test complete lifecycle: DISCOVERED → VALIDATING → PROMOTED → DEPRECATED → RETIRED."""
        combo = manager.create_combination("review", ["karpathy"])
        assert combo.state == CombinationLifecycleState.DISCOVERED

        # DISCOVERED → VALIDATING (via record_execution)
        manager.record_execution(combo.combination_id, gain=1.5)
        loaded = manager.get_combination(combo.combination_id)
        assert loaded.state == CombinationLifecycleState.VALIDATING

        # VALIDATING → PROMOTED
        for i in range(5):
            manager.record_execution(combo.combination_id, gain=1.5)
        result = manager.try_promote(combo.combination_id)
        assert result.success

        # PROMOTED → DEPRECATED
        result = manager.transition(
            combo.combination_id, CombinationLifecycleState.DEPRECATED,
        )
        assert result.success

        # DEPRECATED → RETIRED
        result = manager.transition(
            combo.combination_id, CombinationLifecycleState.RETIRED,
        )
        assert result.success

    def test_full_lifecycle_rejected_to_rediscovered(self, manager):
        """Test: VALIDATING → REJECTED → DISCOVERED (rediscovery)."""
        combo = manager.create_combination(
            "review", ["karpathy"], source="human_specified",
        )
        for i in range(6):
            manager.record_execution(combo.combination_id, gain=-0.5)
        result = manager.try_promote(combo.combination_id)
        assert result.to_state == CombinationLifecycleState.REJECTED

        # REJECTED → DISCOVERED
        result = manager.transition(
            combo.combination_id, CombinationLifecycleState.DISCOVERED,
        )
        assert result.success

        loaded = manager.get_combination(combo.combination_id)
        assert loaded.state == CombinationLifecycleState.DISCOVERED
        assert loaded.execution_count == 0
        assert loaded.gain_avg == 0.0

    # ── persistence ──

    def test_persistence_multiple_combinations(self, data_dir):
        """Multiple combinations should all survive persistence."""
        m1 = CombinationLifecycleManager(data_dir=data_dir)
        c1 = m1.create_combination("review", ["karpathy"])
        c2 = m1.create_combination("security", ["simplify"])

        m2 = CombinationLifecycleManager(data_dir=data_dir)
        assert m2.get_combination(c1.combination_id) is not None
        assert m2.get_combination(c2.combination_id) is not None

    def test_persistence_corrupt_line_skipped(self, data_dir):
        """Corrupt lines in JSONL should be skipped without crashing."""
        data_dir.mkdir(parents=True, exist_ok=True)
        combos_file = data_dir / "combinations.jsonl"
        # Write a corrupt line, then a valid one
        combos_file.write_text("not-json\n")

        m = CombinationLifecycleManager(data_dir=data_dir)
        # Should not crash on load
        combo = m.create_combination("review", ["karpathy"])
        assert combo is not None

    # ── lazy loading ──

    def test_lazy_loading(self, data_dir):
        """Combinations are loaded lazily on first access."""
        m = CombinationLifecycleManager(data_dir=data_dir)
        assert not m._loaded
        m.get_combination("nonexistent")
        assert m._loaded
