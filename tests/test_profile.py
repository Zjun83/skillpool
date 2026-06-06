"""Tests for AgentCapabilityProfile and preset profiles."""

from __future__ import annotations

import pytest

from skillpool.profile import (
    CLAUDE_CODE_PROFILE,
    CODEX_PROFILE,
    HERMES_PROFILE,
    OPENCLAW_PROFILE,
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
        result = p.can_execute(
            {
                "required_capabilities": {"bash"},
                "min_trust_level": 2,
                "paradigm": "code",
            }
        )
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
# from_dict / to_dict — dynamic profile construction
# ---------------------------------------------------------------------------


class TestFromDict:
    def test_minimal_required_fields(self):
        p = AgentCapabilityProfile.from_dict({"agent_type": "test", "context_window": 1000000})
        assert p.name == "test"
        assert p.context_window == 1000000
        assert p.trust_level == 3  # default
        assert p.required_capabilities == set()
        assert p.supported_paradigms == set()

    def test_full_fields(self):
        p = AgentCapabilityProfile.from_dict({
            "agent_type": "my-agent",
            "context_window": 200000,
            "trust_level": 2,
            "required_capabilities": ["bash", "python", "mcp"],
            "supported_paradigms": ["code", "test", "planning"],
        })
        assert p.name == "my-agent"
        assert p.context_window == 200000
        assert p.trust_level == 2
        assert p.required_capabilities == {"bash", "python", "mcp"}
        assert p.supported_paradigms == {"code", "test", "planning"}

    def test_capabilities_as_set_input(self):
        p = AgentCapabilityProfile.from_dict({
            "agent_type": "t",
            "context_window": 128000,
            "required_capabilities": {"a", "b"},
        })
        assert p.required_capabilities == {"a", "b"}

    def test_missing_agent_type_raises(self):
        with pytest.raises(ValueError, match="agent_type is required"):
            AgentCapabilityProfile.from_dict({"context_window": 128000})

    def test_missing_context_window_raises(self):
        with pytest.raises(ValueError, match="context_window is required"):
            AgentCapabilityProfile.from_dict({"agent_type": "t"})

    def test_context_window_as_string(self):
        p = AgentCapabilityProfile.from_dict({"agent_type": "t", "context_window": "1000000"})
        assert p.context_window == 1000000

    def test_trust_level_as_string(self):
        p = AgentCapabilityProfile.from_dict({"agent_type": "t", "context_window": 128000, "trust_level": "3"})
        assert p.trust_level == 3


class TestToDict:
    def test_roundtrip(self):
        original = AgentCapabilityProfile(
            name="test",
            required_capabilities={"bash", "python"},
            context_window=200000,
            trust_level=3,
            supported_paradigms={"code", "test"},
        )
        d = original.to_dict()
        restored = AgentCapabilityProfile.from_dict(d)
        assert restored.name == original.name
        assert restored.context_window == original.context_window
        assert restored.trust_level == original.trust_level
        assert restored.required_capabilities == original.required_capabilities
        assert restored.supported_paradigms == original.supported_paradigms

    def test_output_sorted(self):
        p = AgentCapabilityProfile(
            name="t",
            required_capabilities={"z", "a"},
            supported_paradigms={"y", "b"},
        )
        d = p.to_dict()
        assert d["required_capabilities"] == ["a", "z"]
        assert d["supported_paradigms"] == ["b", "y"]


# ---------------------------------------------------------------------------
# Preset profiles (updated V4.3 values)
# ---------------------------------------------------------------------------


class TestPresetProfiles:
    @pytest.mark.parametrize(
        "profile",
        [CLAUDE_CODE_PROFILE, CODEX_PROFILE, HERMES_PROFILE, OPENCLAW_PROFILE],
        ids=["claude-code", "codex", "hermes", "openclaw"],
    )
    def test_preset_instantiable(self, profile):
        assert isinstance(profile, AgentCapabilityProfile)
        assert profile.name
        assert profile.required_capabilities
        assert profile.trust_level >= 1
        assert profile.supported_paradigms

    def test_claude_code_profile_values(self):
        assert CLAUDE_CODE_PROFILE.name == "claude-code"
        assert "mcp" in CLAUDE_CODE_PROFILE.required_capabilities
        assert "subagent" in CLAUDE_CODE_PROFILE.required_capabilities
        assert "task_management" in CLAUDE_CODE_PROFILE.required_capabilities
        assert CLAUDE_CODE_PROFILE.context_window == 200000
        assert CLAUDE_CODE_PROFILE.trust_level == 3
        assert "test" in CLAUDE_CODE_PROFILE.supported_paradigms
        assert "debug" in CLAUDE_CODE_PROFILE.supported_paradigms

    def test_codex_profile_values(self):
        assert CODEX_PROFILE.name == "codex"
        assert "mcp" in CODEX_PROFILE.required_capabilities
        assert "subagent" in CODEX_PROFILE.required_capabilities
        assert "web_search" in CODEX_PROFILE.required_capabilities
        assert CODEX_PROFILE.context_window == 1000000
        assert CODEX_PROFILE.trust_level == 3
        assert "planning" in CODEX_PROFILE.supported_paradigms
        assert "review" in CODEX_PROFILE.supported_paradigms

    def test_hermes_profile_values(self):
        assert HERMES_PROFILE.name == "hermes"
        assert "bash" in HERMES_PROFILE.required_capabilities
        assert "mcp" in HERMES_PROFILE.required_capabilities
        assert "scheduling" in HERMES_PROFILE.required_capabilities
        assert "memory" in HERMES_PROFILE.required_capabilities
        assert HERMES_PROFILE.context_window == 200000
        assert HERMES_PROFILE.trust_level == 3
        assert "code" in HERMES_PROFILE.supported_paradigms
        assert "test" in HERMES_PROFILE.supported_paradigms

    def test_openclaw_profile_values(self):
        assert OPENCLAW_PROFILE.name == "openclaw"
        assert "mcp" in OPENCLAW_PROFILE.required_capabilities
        assert "scheduling" in OPENCLAW_PROFILE.required_capabilities
        assert "media_generation" in OPENCLAW_PROFILE.required_capabilities
        assert OPENCLAW_PROFILE.context_window == 1000000
        assert OPENCLAW_PROFILE.trust_level == 3
        assert "automation" in OPENCLAW_PROFILE.supported_paradigms

    def test_all_profiles_trust_level_3(self):
        """All agents have trust_level=3 (user requirement)."""
        for p in [CLAUDE_CODE_PROFILE, CODEX_PROFILE, HERMES_PROFILE, OPENCLAW_PROFILE]:
            assert p.trust_level == 3

    def test_claude_code_can_execute_code_skill(self):
        result = CLAUDE_CODE_PROFILE.can_execute(
            {
                "required_capabilities": {"bash", "python"},
                "min_trust_level": 2,
                "paradigm": "code",
            }
        )
        assert result == (True, "ok")

    def test_hermes_can_execute_bash_skill(self):
        """Hermes now has bash capability (trust_level=3)."""
        ok, _ = HERMES_PROFILE.can_execute({"required_capabilities": {"bash"}})
        assert ok is True

    def test_codex_can_execute_planning(self):
        """Codex now supports planning paradigm."""
        ok, _ = CODEX_PROFILE.can_execute({"paradigm": "planning"})
        assert ok is True
