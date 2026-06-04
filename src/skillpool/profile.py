"""Agent capability profiles for skill matching and execution gating."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentCapabilityProfile:
    """Describes an agent's capabilities used to determine skill compatibility.

    Attributes:
        name: Unique identifier for the profile.
        required_capabilities: Set of capability strings the agent possesses.
        context_window: Maximum context window size in tokens.
        trust_level: Trust level (1-3), higher = more privileged.
        supported_paradigms: Set of paradigm strings the agent supports.
    """

    name: str
    required_capabilities: set[str] = field(default_factory=set)
    context_window: int = 128000
    trust_level: int = 1
    supported_paradigms: set[str] = field(default_factory=set)

    def can_execute(self, skill_requirements: dict) -> tuple[bool, str]:
        """Check whether this profile satisfies the given skill requirements.

        Args:
            skill_requirements: Dict with optional keys:
                - 'required_capabilities': set[str] of capabilities needed
                - 'min_trust_level': int minimum trust level
                - 'paradigm': str paradigm the skill belongs to

        Returns:
            (True, 'ok') if all requirements are met,
            (False, 'missing: <detail>') otherwise.
        """
        # Check required capabilities
        required_caps = skill_requirements.get("required_capabilities", set())
        if isinstance(required_caps, (list, tuple)):
            required_caps = set(required_caps)
        missing_caps = required_caps - self.required_capabilities
        if missing_caps:
            return (False, f"missing: capabilities {sorted(missing_caps)}")

        # Check minimum trust level
        min_trust = skill_requirements.get("min_trust_level", 0)
        if min_trust > self.trust_level:
            return (False, f"missing: trust_level {min_trust} > {self.trust_level}")

        # Check paradigm support
        paradigm = skill_requirements.get("paradigm")
        if paradigm and paradigm not in self.supported_paradigms:
            return (False, f"missing: paradigm '{paradigm}'")

        return (True, "ok")


# ---------------------------------------------------------------------------
# Preset profiles
# ---------------------------------------------------------------------------

CLAUDE_CODE_PROFILE = AgentCapabilityProfile(
    name="claude-code",
    required_capabilities={"bash", "file_system", "python", "web_search"},
    context_window=200000,
    trust_level=3,
    supported_paradigms={"review", "code", "planning", "4d", "docsdd", "sdd", "bdd", "tdd"},
)

CODEX_PROFILE = AgentCapabilityProfile(
    name="codex",
    required_capabilities={"bash", "file_system", "python"},
    context_window=128000,
    trust_level=2,
    supported_paradigms={"code", "test", "4d", "sdd", "bdd", "tdd"},
)

HERMES_PROFILE = AgentCapabilityProfile(
    name="hermes",
    required_capabilities={"file_system", "web_search"},
    context_window=32000,
    trust_level=1,
    supported_paradigms={"research", "planning", "4d", "docsdd"},
)

OPENCLAW_PROFILE = AgentCapabilityProfile(
    name="openclaw",
    required_capabilities={"bash", "file_system", "python", "web_search"},
    context_window=128000,
    trust_level=2,
    supported_paradigms={"review", "code", "test", "planning", "4d", "docsdd", "sdd", "bdd", "tdd"},
)
