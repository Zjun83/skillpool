"""
Tests for Skill Lifecycle State Machine
"""

from skillpool.lifecycle import (
    SkillLifecycleState,
    validate_transition,
    get_valid_transitions,
    is_terminal,
    get_state_name,
    parse_state,
)


class TestSkillLifecycleState:
    """Test the 9-state enumeration"""

    def test_nine_states_exist(self):
        expected_states = [
            "DRAFT", "PROPOSED", "UNDER_REVIEW", "APPROVED", "REJECTED",
            "ACTIVE", "DEPRECATED", "ARCHIVED", "REMOVED",
        ]
        actual_states = [s.name for s in SkillLifecycleState]
        assert len(actual_states) == 9
        for state in expected_states:
            assert state in actual_states

    def test_state_values_are_unique(self):
        values = [s.value for s in SkillLifecycleState]
        assert len(values) == len(set(values))


class TestValidateTransition:
    """Test transition validation"""

    def test_valid_draft_to_proposed(self):
        assert validate_transition(SkillLifecycleState.DRAFT, SkillLifecycleState.PROPOSED) is True

    def test_valid_proposed_to_under_review(self):
        assert validate_transition(SkillLifecycleState.PROPOSED, SkillLifecycleState.UNDER_REVIEW) is True

    def test_valid_under_review_to_approved(self):
        assert validate_transition(SkillLifecycleState.UNDER_REVIEW, SkillLifecycleState.APPROVED) is True

    def test_valid_approved_to_active(self):
        assert validate_transition(SkillLifecycleState.APPROVED, SkillLifecycleState.ACTIVE) is True

    def test_valid_active_to_deprecated(self):
        assert validate_transition(SkillLifecycleState.ACTIVE, SkillLifecycleState.DEPRECATED) is True

    def test_valid_deprecated_to_archived(self):
        assert validate_transition(SkillLifecycleState.DEPRECATED, SkillLifecycleState.ARCHIVED) is True

    def test_invalid_draft_to_active(self):
        assert validate_transition(SkillLifecycleState.DRAFT, SkillLifecycleState.ACTIVE) is False

    def test_invalid_active_to_draft(self):
        assert validate_transition(SkillLifecycleState.ACTIVE, SkillLifecycleState.DRAFT) is False

    def test_removed_to_anything_is_invalid(self):
        for state in SkillLifecycleState:
            if state != SkillLifecycleState.REMOVED:
                assert validate_transition(SkillLifecycleState.REMOVED, state) is False

    def test_same_state_is_invalid(self):
        for state in SkillLifecycleState:
            assert validate_transition(state, state) is False


class TestGetValidTransitions:
    """Test getting valid transitions from a state"""

    def test_draft_transitions(self):
        transitions = get_valid_transitions(SkillLifecycleState.DRAFT)
        assert SkillLifecycleState.PROPOSED in transitions
        assert SkillLifecycleState.REMOVED in transitions
        assert len(transitions) == 2

    def test_under_review_transitions(self):
        transitions = get_valid_transitions(SkillLifecycleState.UNDER_REVIEW)
        assert SkillLifecycleState.APPROVED in transitions
        assert SkillLifecycleState.REJECTED in transitions
        assert SkillLifecycleState.PROPOSED in transitions
        assert len(transitions) == 3

    def test_active_transitions(self):
        transitions = get_valid_transitions(SkillLifecycleState.ACTIVE)
        assert SkillLifecycleState.DEPRECATED in transitions
        assert SkillLifecycleState.ARCHIVED in transitions
        assert len(transitions) == 2

    def test_removed_no_transitions(self):
        transitions = get_valid_transitions(SkillLifecycleState.REMOVED)
        assert len(transitions) == 0

    def test_sorted_by_value(self):
        transitions = get_valid_transitions(SkillLifecycleState.UNDER_REVIEW)
        values = [t.value for t in transitions]
        assert values == sorted(values)


class TestIsTerminal:
    """Test terminal state detection"""

    def test_removed_is_terminal(self):
        assert is_terminal(SkillLifecycleState.REMOVED) is True

    def test_draft_not_terminal(self):
        assert is_terminal(SkillLifecycleState.DRAFT) is False

    def test_active_not_terminal(self):
        assert is_terminal(SkillLifecycleState.ACTIVE) is False

    def test_archived_not_terminal(self):
        assert is_terminal(SkillLifecycleState.ARCHIVED) is False


class TestHelperFunctions:
    """Test helper functions"""

    def test_get_state_name(self):
        assert get_state_name(SkillLifecycleState.DRAFT) == "draft"
        assert get_state_name(SkillLifecycleState.UNDER_REVIEW) == "under_review"
        assert get_state_name(SkillLifecycleState.ACTIVE) == "active"

    def test_parse_state_valid(self):
        assert parse_state("draft") == SkillLifecycleState.DRAFT
        assert parse_state("DRAFT") == SkillLifecycleState.DRAFT
        assert parse_state("Draft") == SkillLifecycleState.DRAFT
        assert parse_state("active") == SkillLifecycleState.ACTIVE

    def test_parse_state_invalid(self):
        assert parse_state("invalid_state") is None
        assert parse_state("") is None


class TestLifecycleWorkflow:
    """Test complete lifecycle workflows"""

    def test_happy_path(self):
        path = [
            SkillLifecycleState.DRAFT,
            SkillLifecycleState.PROPOSED,
            SkillLifecycleState.UNDER_REVIEW,
            SkillLifecycleState.APPROVED,
            SkillLifecycleState.ACTIVE,
        ]
        for i in range(len(path) - 1):
            assert validate_transition(path[i], path[i + 1]) is True

    def test_rejection_path(self):
        path = [
            SkillLifecycleState.DRAFT,
            SkillLifecycleState.PROPOSED,
            SkillLifecycleState.UNDER_REVIEW,
            SkillLifecycleState.REJECTED,
            SkillLifecycleState.DRAFT,
        ]
        for i in range(len(path) - 1):
            assert validate_transition(path[i], path[i + 1]) is True

    def test_deprecation_path(self):
        assert validate_transition(SkillLifecycleState.ACTIVE, SkillLifecycleState.DEPRECATED) is True
        assert validate_transition(SkillLifecycleState.DEPRECATED, SkillLifecycleState.ARCHIVED) is True

    def test_early_removal(self):
        assert validate_transition(SkillLifecycleState.DRAFT, SkillLifecycleState.REMOVED) is True
