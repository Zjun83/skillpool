"""SkillPool Agent Adapter — Base class for agent runtime integration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from skillpool.csdf import CSDFDocument
from skillpool.materializer import MaterializationResult, Materializer


class AgentAdapter(ABC):
    """Base class for agent-specific skill adapters.

    Subclasses must implement:
    - render_skill: format a CSDF document for the target agent
    - install_skill: place the rendered skill in the agent's runtime directory
    - verify_skill: confirm the skill is accessible to the agent
    """

    def __init__(
        self, materializer: Materializer | None = None, state_dir: Path = Path(".skillpool")
    ) -> None:
        self.materializer = materializer or Materializer(state_dir)

    @abstractmethod
    def render_skill(self, doc: CSDFDocument) -> str:
        """Render a CSDF document into the agent's native format."""
        ...

    @abstractmethod
    def install_skill(self, doc: CSDFDocument, target_dir: Path) -> MaterializationResult:
        """Render and install a skill into the agent's runtime directory."""
        ...

    @abstractmethod
    def verify_skill(self, name: str, target_dir: Path) -> bool:
        """Verify a skill is installed and accessible."""
        ...

    def materialize_and_install(self, doc: CSDFDocument, target_dir: Path) -> MaterializationResult:
        """Convenience: render + install in one call."""
        return self.install_skill(doc, target_dir)
