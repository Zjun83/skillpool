"""Codex Agent Adapter — skill integration for Codex runtime."""

from __future__ import annotations

from pathlib import Path

from skillpool.csdf import CSDFDocument
from skillpool.materializer import MaterializationResult, Materializer

from .base import AgentAdapter


class CodexAdapter(AgentAdapter):
    """Adapter for Codex agent runtime.

    Codex expects SKILL.md files with ## Triggers / ## Instructions sections.
    """

    def __init__(
        self, materializer: Materializer | None = None, state_dir: Path = Path(".skillpool")
    ) -> None:
        super().__init__(materializer, state_dir)
        self.agent_type = "codex"

    def render_skill(self, doc: CSDFDocument) -> str:
        """Render CSDF as Codex-compatible SKILL.md."""
        triggers = "\n".join(f"- {t}" for t in doc.triggers) if doc.triggers else "- (none)"
        return (
            f"# {doc.name}\n\n"
            f"{doc.description}\n\n"
            f"## Triggers\n{triggers}\n\n"
            f"## Instructions\n{doc.body}\n"
        )

    def install_skill(self, doc: CSDFDocument, target_dir: Path) -> MaterializationResult:
        """Materialize and install skill into Codex skills directory."""
        output_path = target_dir / f"{doc.name}.md"
        return self.materializer.materialize(
            doc, agent_type=self.agent_type, output_path=output_path
        )

    def verify_skill(self, name: str, target_dir: Path) -> bool:
        """Check if a Codex skill file exists and is non-empty."""
        skill_file = target_dir / f"{name}.md"
        return skill_file.exists() and skill_file.stat().st_size > 0
