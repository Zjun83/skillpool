"""Tests for Lifecycle module coverage gaps — uncovered lines from lifecycle.py.

Targeted gaps:
- validate_transition: self-transition, invalid from_state
- get_valid_transitions: REMOVED has no valid transitions
- is_terminal: non-terminal states
- get_state_name: all states
- parse_state: empty string, lowercase, uppercase, mixed case
- check_auto_deprecation: skill with no executions, skill with low effectiveness
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from skillpool.lifecycle import (
    SkillLifecycleState,
    check_auto_deprecation,
    get_state_name,
    get_valid_transitions,
    is_terminal,
    parse_state,
    validate_transition,
)


class TestValidateTransition:
    def test_self_transition_invalid(self):
        """Same from/to -> False."""
        assert validate_transition(SkillLifecycleState.DRAFT, SkillLifecycleState.DRAFT) is False

    def test_invalid_from_state(self):
        """Unknown from_state -> no transitions -> False."""
        assert validate_transition(SkillLifecycleState.REMOVED, SkillLifecycleState.DRAFT) is False

    def test_valid_transition_draft_to_proposed(self):
        assert validate_transition(SkillLifecycleState.DRAFT, SkillLifecycleState.PROPOSED) is True

    def test_invalid_jump_draft_to_active(self):
        assert validate_transition(SkillLifecycleState.DRAFT, SkillLifecycleState.ACTIVE) is False


class TestGetValidTransitions:
    def test_removed_has_no_transitions(self):
        """REMOVED is terminal -> empty list."""
        assert get_valid_transitions(SkillLifecycleState.REMOVED) == []

    def test_draft_has_transitions(self):
        transitions = get_valid_transitions(SkillLifecycleState.DRAFT)
        assert SkillLifecycleState.PROPOSED in transitions
        assert SkillLifecycleState.REMOVED in transitions


class TestIsTerminal:
    def test_removed_is_terminal(self):
        assert is_terminal(SkillLifecycleState.REMOVED) is True

    def test_active_is_not_terminal(self):
        assert is_terminal(SkillLifecycleState.ACTIVE) is False

    def test_archived_is_not_terminal(self):
        """ARCHIVED still has transitions to ACTIVE or REMOVED."""
        assert is_terminal(SkillLifecycleState.ARCHIVED) is False


class TestGetStateName:
    def test_active(self):
        assert get_state_name(SkillLifecycleState.ACTIVE) == "active"

    def test_draft(self):
        assert get_state_name(SkillLifecycleState.DRAFT) == "draft"

    def test_under_review(self):
        assert get_state_name(SkillLifecycleState.UNDER_REVIEW) == "under_review"


class TestParseState:
    def test_lowercase(self):
        assert parse_state("draft") == SkillLifecycleState.DRAFT

    def test_uppercase(self):
        assert parse_state("ACTIVE") == SkillLifecycleState.ACTIVE

    def test_mixed_case(self):
        assert parse_state("Draft") == SkillLifecycleState.DRAFT

    def test_empty_string(self):
        assert parse_state("") is None

    def test_invalid_name(self):
        assert parse_state("nonexistent_state") is None

    def test_whitespace(self):
        assert parse_state("  DRAFT  ") == SkillLifecycleState.DRAFT


class TestCheckAutoDeprecation:
    def test_no_executions_not_deprecated(self):
        """Skill with 0 executions -> no data to deprecate."""
        with patch("skillpool.gain.GainTracker") as MockTracker:
            tracker = MockTracker.return_value
            report = MagicMock()
            report.execution_count = 0
            tracker.report.return_value = report

            with patch("skillpool.combiner.CombinationLifecycleManager"):
                result = check_auto_deprecation("S09")
                assert result is False

    def test_low_effectiveness_with_enough_executions(self):
        """avg_effectiveness < 3.0 with >= 5 executions -> deprecate."""
        with patch("skillpool.gain.GainTracker") as MockTracker:
            tracker = MockTracker.return_value
            report = MagicMock()
            report.execution_count = 10
            report.avg_effectiveness = 2.0
            tracker.report.return_value = report

            with patch("skillpool.combiner.CombinationLifecycleManager") as MockLCM:
                mgr = MockLCM.return_value
                mgr.get_combinations_for_skill.return_value = []
                result = check_auto_deprecation("S09")
                assert result is True

    def test_high_effectiveness_not_deprecated(self):
        """avg_effectiveness >= 3.0 -> not deprecated."""
        with patch("skillpool.gain.GainTracker") as MockTracker:
            tracker = MockTracker.return_value
            report = MagicMock()
            report.execution_count = 10
            report.avg_effectiveness = 7.5
            tracker.report.return_value = report

            result = check_auto_deprecation("S09")
            assert result is False

    def test_cascades_deprecation_to_combinations(self):
        """Deprecation cascades to PROMOTED combinations."""
        with patch("skillpool.gain.GainTracker") as MockTracker:
            tracker = MockTracker.return_value
            report = MagicMock()
            report.execution_count = 10
            report.avg_effectiveness = 2.0
            tracker.report.return_value = report

            with patch("skillpool.combiner.CombinationLifecycleManager") as MockLCM:
                mgr = MockLCM.return_value
                promoted_combo = MagicMock()
                promoted_combo.state.value = 2  # PROMOTED
                mgr.get_combinations_for_skill.return_value = [promoted_combo]

                result = check_auto_deprecation("S09")
                assert result is True
                mgr.transition.assert_called_once()

    def test_import_error_returns_false(self):
        """ImportError -> gracefully returns False."""
        with patch("skillpool.gain.GainTracker", side_effect=ImportError("no module")):
            result = check_auto_deprecation("S09")
            assert result is False

    def test_exception_returns_false(self):
        """Generic exception -> gracefully returns False."""
        with patch("skillpool.gain.GainTracker", side_effect=Exception("unexpected")):
            result = check_auto_deprecation("S09")
            assert result is False
