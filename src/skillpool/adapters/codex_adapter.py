"""Codex Agent Adapter — skill integration for Codex runtime."""

from __future__ import annotations

import logging
from pathlib import Path

from skillpool.config import get_data_dir
from skillpool.csdf import CSDFDocument
from skillpool.materializer import MaterializationResult, Materializer

from .base import AgentAdapter

logger = logging.getLogger(__name__)


class CodexAdapter(AgentAdapter):
    """Adapter for Codex agent runtime.

    Codex expects SKILL.md files with ## Triggers / ## Instructions sections.
    Startup hook auto-registers skills from ~/.skillpool/skills/ on init.
    """

    def __init__(self, materializer: Materializer | None = None, state_dir: Path = Path(".skillpool")) -> None:
        super().__init__(materializer, state_dir)
        self.agent_type = "codex"
        self._skills_dir = get_data_dir() / "skills"

    def render_skill(self, doc: CSDFDocument) -> str:
        """Render CSDF as Codex-compatible SKILL.md."""
        triggers = "\n".join(f"- {t}" for t in doc.triggers) if doc.triggers else "- (none)"
        return f"# {doc.name}\n\n{doc.description}\n\n## Triggers\n{triggers}\n\n## Instructions\n{doc.body}\n"

    def install_skill(self, doc: CSDFDocument, target_dir: Path) -> MaterializationResult:
        """Materialize and install skill into Codex skills directory."""
        output_path = target_dir / f"{doc.name}.md"
        return self.materializer.materialize(doc, agent_type=self.agent_type, output_path=output_path)

    def verify_skill(self, name: str, target_dir: Path) -> bool:
        """Check if a Codex skill file exists and is non-empty."""
        skill_file = target_dir / f"{name}.md"
        return skill_file.exists() and skill_file.stat().st_size > 0

    def on_startup(self, target_dir: Path | None = None) -> dict[str, bool]:
        """Startup hook: auto-register all skills from SkillPool.

        Called when Codex initializes to sync skills from ~/.skillpool/skills/
        to the Codex skills directory.

        Args:
            target_dir: Codex skills directory (defaults to ~/.codex/skills/).

        Returns:
            Dict mapping skill_id to install success status.
        """
        from skillpool.materializer.csdf_loader import load_csdf

        target = target_dir or Path.home() / ".codex" / "skills"
        target.mkdir(parents=True, exist_ok=True)

        results: dict[str, bool] = {}

        if not self._skills_dir.exists():
            logger.info("Codex startup hook: no skills directory found at %s", self._skills_dir)
            return results

        # Scan for CSDF YAML files
        for yaml_file in sorted(self._skills_dir.glob("*.yaml")):
            if yaml_file.name == "skill_graph.yaml":
                continue
            skill_id = yaml_file.stem.split("-")[0]
            try:
                csdf_data = load_csdf(skill_id, self._skills_dir)
                if csdf_data is None:
                    continue
                doc = CSDFDocument(**csdf_data)
                # Render and write directly (bypass broken install_skill)
                rendered = self.render_skill(doc)
                output_path = target / f"{doc.name}.md"
                output_path.write_text(rendered, encoding="utf-8")
                success = output_path.exists() and output_path.stat().st_size > 0
                results[skill_id] = success
                if success:
                    logger.debug("Codex startup hook: installed %s", skill_id)
                else:
                    logger.warning("Codex startup hook: failed to install %s (empty file)", skill_id)
            except Exception as e:
                logger.error("Codex startup hook: error installing %s: %s", skill_id, e)
                results[skill_id] = False

        logger.info("Codex startup hook: registered %d/%d skills", sum(results.values()), len(results))
        return results
