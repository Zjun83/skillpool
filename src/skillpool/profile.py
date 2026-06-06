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

    @classmethod
    def from_dict(cls, data: dict) -> AgentCapabilityProfile:
        """Build a profile from a dict (e.g., MCP experimental.agentProfile or HTTP header).

        Required keys: agent_type, context_window.
        Optional keys: trust_level (default 3), required_capabilities, supported_paradigms.
        """
        agent_type = data.get("agent_type")
        if not agent_type:
            raise ValueError("agent_type is required in profile dict")

        context_window = data.get("context_window")
        if not context_window:
            raise ValueError("context_window is required in profile dict")
        context_window = int(context_window)

        caps = data.get("required_capabilities", set())
        if isinstance(caps, (list, tuple)):
            caps = set(caps)

        paradigms = data.get("supported_paradigms", set())
        if isinstance(paradigms, (list, tuple)):
            paradigms = set(paradigms)

        return cls(
            name=agent_type,
            required_capabilities=caps,
            context_window=context_window,
            trust_level=int(data.get("trust_level", 3)),
            supported_paradigms=paradigms,
        )

    def to_dict(self) -> dict:
        """Serialize profile to dict for MCP transmission or logging."""
        return {
            "agent_type": self.name,
            "context_window": self.context_window,
            "trust_level": self.trust_level,
            "required_capabilities": sorted(self.required_capabilities),
            "supported_paradigms": sorted(self.supported_paradigms),
        }


# ---------------------------------------------------------------------------
# Preset profiles
# ---------------------------------------------------------------------------

CLAUDE_CODE_PROFILE = AgentCapabilityProfile(
    name="claude-code",
    required_capabilities={"bash", "file_system", "python", "web_search", "mcp", "subagent", "task_management"},
    context_window=200000,
    trust_level=3,
    supported_paradigms={"review", "code", "planning", "4d", "docsdd", "sdd", "bdd", "tdd", "test", "debug"},
)

CODEX_PROFILE = AgentCapabilityProfile(
    name="codex",
    required_capabilities={"bash", "file_system", "python", "mcp", "subagent", "web_search"},
    context_window=1000000,
    trust_level=3,
    supported_paradigms={"code", "test", "planning", "review", "sdd", "bdd", "tdd"},
)

HERMES_PROFILE = AgentCapabilityProfile(
    name="hermes",
    required_capabilities={"file_system", "web_search", "bash", "mcp", "subagent", "scheduling", "memory"},
    context_window=200000,
    trust_level=3,
    supported_paradigms={"research", "planning", "code", "test", "debug", "4d"},
)

OPENCLAW_PROFILE = AgentCapabilityProfile(
    name="openclaw",
    required_capabilities={"bash", "file_system", "python", "web_search", "mcp", "subagent", "scheduling", "media_generation"},
    context_window=1000000,
    trust_level=3,
    supported_paradigms={"code", "planning", "test", "automation"},
)
