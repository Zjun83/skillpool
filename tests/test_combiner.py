"""Tests for combiner module — combination lifecycle + data models."""
import json
import tempfile
from pathlib import Path

import pytest

from skillpool.combiner.models import (
    CombinationLifecycleState,
    SkillCombination,
    CombinationTransitionResult,
    MIN_VALIDATION_EXECUTIONS,
)
from skillpool.combiner.lifecycle import CombinationLifecycleManager


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
