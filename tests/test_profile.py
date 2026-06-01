"""Tests for AgentCapabilityProfile and preset profiles."""

from __future__ import annotations

import pytest

from skillpool.profile import (
    CLAUDE_CODE_PROFILE,
    CODEX_PROFILE,
    HERMES_PROFILE,
    AgentCapabilityProfile,
)


# ---------------------------------------------------------------------------
# Profile creation
# ---------------------------------------------------------------------------


class TestProfileCreation:
    def test_default_values(self):
        p = AgentCapabilityProfile(name="test")
        assert p.name == "test"
        assert p.required_capabilities == set()
        assert p.context_window == 128000
        assert p.trust_level == 1
        assert p.supported_paradigms == set()

    def test_custom_values(self):
        p = AgentCapabilityProfile(
            name="custom",
            required_capabilities={"a", "b"},
            context_window=64000,
            trust_level=2,
            supported_paradigms={"x", "y"},
        )
        assert p.required_capabilities == {"a", "b"}
        assert p.context_window == 64000
        assert p.trust_level == 2
        assert p.supported_paradigms == {"x", "y"}


# ---------------------------------------------------------------------------
# can_execute — matching scenarios
# ---------------------------------------------------------------------------


class TestCanExecuteMatch:
    def test_empty_requirements(self):
        p = AgentCapabilityProfile(name="t")
        assert p.can_execute({}) == (True, "ok")

    def test_capabilities_subset(self):
        p = AgentCapabilityProfile(name="t", required_capabilities={"a", "b", "c"})
        assert p.can_execute({"required_capabilities": {"a", "b"}}) == (True, "ok")

    def test_trust_level_sufficient(self):
        p = AgentCapabilityProfile(name="t", trust_level=3)
        assert p.can_execute({"min_trust_level": 2}) == (True, "ok")

    def test_trust_level_exact(self):
        p = AgentCapabilityProfile(name="t", trust_level=2)
        assert p.can_execute({"min_trust_level": 2}) == (True, "ok")

    def test_paradigm_supported(self):
        p = AgentCapabilityProfile(name="t", supported_paradigms={"code", "test"})
        assert p.can_execute({"paradigm": "code"}) == (True, "ok")

    def test_all_requirements_met(self):
        p = AgentCapabilityProfile(
            name="t",
            required_capabilities={"bash", "python"},
            trust_level=3,
            supported_paradigms={"code"},
        )
        result = p.can_execute({
            "required_capabilities": {"bash"},
            "min_trust_level": 2,
            "paradigm": "code",
        })
        assert result == (True, "ok")

    def test_capabilities_as_list(self):
        p = AgentCapabilityProfile(name="t", required_capabilities={"a", "b"})
        assert p.can_execute({"required_capabilities": ["a"]}) == (True, "ok")


# ---------------------------------------------------------------------------
# can_execute — non-matching scenarios
# ---------------------------------------------------------------------------


class TestCanExecuteMismatch:
    def test_missing_capability(self):
        p = AgentCapabilityProfile(name="t", required_capabilities={"a"})
        ok, msg = p.can_execute({"required_capabilities": {"b"}})
        assert ok is False
        assert "missing" in msg and "b" in msg

    def test_missing_multiple_capabilities(self):
        p = AgentCapabilityProfile(name="t", required_capabilities={"a"})
        ok, msg = p.can_execute({"required_capabilities": {"b", "c"}})
        assert ok is False
        assert "missing" in msg

    def test_insufficient_trust(self):
        p = AgentCapabilityProfile(name="t", trust_level=1)
        ok, msg = p.can_execute({"min_trust_level": 3})
        assert ok is False
        assert "trust_level" in msg

    def test_unsupported_paradigm(self):
        p = AgentCapabilityProfile(name="t", supported_paradigms={"code"})
        ok, msg = p.can_execute({"paradigm": "research"})
        assert ok is False
        assert "paradigm" in msg and "research" in msg

    def test_capability_check_before_trust(self):
        """Capabilities are checked first; trust never reached if caps missing."""
        p = AgentCapabilityProfile(name="t", required_capabilities={"a"}, trust_level=1)
        ok, msg = p.can_execute({"required_capabilities": {"z"}, "min_trust_level": 5})
        assert ok is False
        assert "capabilities" in msg  # fails on caps, not trust


# ---------------------------------------------------------------------------
# Preset profiles
# ---------------------------------------------------------------------------


class TestPresetProfiles:
    @pytest.mark.parametrize(
        "profile",
        [CLAUDE_CODE_PROFILE, CODEX_PROFILE, HERMES_PROFILE],
        ids=["claude-code", "codex", "hermes"],
    )
    def test_preset_instantiable(self, profile):
        assert isinstance(profile, AgentCapabilityProfile)
        assert profile.name
        assert profile.required_capabilities
        assert profile.trust_level >= 1
        assert profile.supported_paradigms

    def test_claude_code_profile_values(self):
        assert CLAUDE_CODE_PROFILE.name == "claude-code"
        assert CLAUDE_CODE_PROFILE.required_capabilities == {"bash", "file_system", "python", "web_search"}
        assert CLAUDE_CODE_PROFILE.context_window == 200000
        assert CLAUDE_CODE_PROFILE.trust_level == 3
        assert CLAUDE_CODE_PROFILE.supported_paradigms == {"review", "code", "planning", "docsdd", "sdd", "bdd", "tdd"}

    def test_codex_profile_values(self):
        assert CODEX_PROFILE.name == "codex"
        assert CODEX_PROFILE.required_capabilities == {"bash", "file_system", "python"}
        assert CODEX_PROFILE.context_window == 128000
        assert CODEX_PROFILE.trust_level == 2
        assert CODEX_PROFILE.supported_paradigms == {"code", "test", "sdd", "bdd", "tdd"}

    def test_hermes_profile_values(self):
        assert HERMES_PROFILE.name == "hermes"
        assert HERMES_PROFILE.required_capabilities == {"file_system", "web_search"}
        assert HERMES_PROFILE.context_window == 32000
        assert HERMES_PROFILE.trust_level == 1
        assert HERMES_PROFILE.supported_paradigms == {"research", "planning", "docsdd"}

    def test_claude_code_can_execute_code_skill(self):
        result = CLAUDE_CODE_PROFILE.can_execute({
            "required_capabilities": {"bash", "python"},
            "min_trust_level": 2,
            "paradigm": "code",
        })
        assert result == (True, "ok")

    def test_hermes_cannot_execute_bash_skill(self):
        ok, msg = HERMES_PROFILE.can_execute({"required_capabilities": {"bash"}})
        assert ok is False

    def test_codex_cannot_execute_research_paradigm(self):
        ok, msg = CODEX_PROFILE.can_execute({"paradigm": "research"})
        assert ok is False
