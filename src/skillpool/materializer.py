"""SkillPool Materializer — Render skills for target agent runtimes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, model_validator

from skillpool.csdf import CSDFDocument


class MaterializationResult(BaseModel):
    """Result of a skill materialization operation."""

    skill_name: str
    version: str
    agent_type: str
    output_path: str
    success: bool
    timestamp: str = ""
    error: str = ""

    @model_validator(mode="after")
    def _set_timestamp(self) -> MaterializationResult:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        return self


# Agent-specific templates for materialization
AGENT_TEMPLATES: dict[str, str] = {
    "codex": "# {name}\n\n{description}\n\n## Triggers\n{triggers}\n\n## Instructions\n{body}\n",
    "claude": (
        "# {name}\n\n{description}\n\n### When to use\n{triggers}\n\n### Instructions\n{body}\n"
    ),
    "generic": "# {name} (v{version})\n\n{description}\n\nTriggers: {triggers}\n\n{body}\n",
}


class Materializer:
    """Materialize skills into agent-specific runtime formats.

    Takes a CSDFDocument and renders it into the appropriate format
    for a target agent type. Stores versioned snapshots for rollback.
    """

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir / "materialization_state"
        self._versions_dir = self._state_dir / "versions"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._versions_dir.mkdir(parents=True, exist_ok=True)

    def materialize(
        self,
        doc: CSDFDocument,
        agent_type: str = "codex",
        output_path: Path | None = None,
    ) -> MaterializationResult:
        """Materialize a CSDF document for a target agent.

        Args:
            doc: The CSDF document to materialize.
            agent_type: Target agent type (codex, claude, generic).
            output_path: Optional explicit output path.

        Returns:
            MaterializationResult with success status and output path.
        """
        template = AGENT_TEMPLATES.get(agent_type, AGENT_TEMPLATES["generic"])

        try:
            triggers_str = "\n".join(f"- {t}" for t in doc.triggers) if doc.triggers else "- (none)"
            rendered = template.format(
                name=doc.name,
                version=doc.version,
                description=doc.description,
                triggers=triggers_str,
                body=doc.body,
            )
        except KeyError as e:
            return MaterializationResult(
                skill_name=doc.name,
                version=doc.version,
                agent_type=agent_type,
                output_path="",
                success=False,
                error=f"Template formatting error: {e}",
            )

        if output_path is None:
            output_path = self._state_dir / f"{doc.name}_{agent_type}.md"

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
        except OSError as e:
            return MaterializationResult(
                skill_name=doc.name,
                version=doc.version,
                agent_type=agent_type,
                output_path="",
                success=False,
                error=f"Write error: {e}",
            )

        self._save_version(doc.name, agent_type, doc.version, rendered)

        return MaterializationResult(
            skill_name=doc.name,
            version=doc.version,
            agent_type=agent_type,
            output_path=str(output_path),
            success=True,
        )

    def _save_version(self, name: str, agent_type: str, version: str, content: str) -> None:
        """Save a versioned snapshot of the materialized skill."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        version_file = self._versions_dir / f"{name}_{agent_type}_{version}_{ts}.md"
        version_file.write_text(content, encoding="utf-8")

    def list_versions(self, name: str, agent_type: str = "codex") -> list[str]:
        """List available versions for a materialized skill."""
        prefix = f"{name}_{agent_type}_"
        versions = []
        for f in self._versions_dir.iterdir():
            if f.name.startswith(prefix) and f.suffix == ".md":
                versions.append(f.name)
        return sorted(versions, reverse=True)

    def rollback(self, name: str, agent_type: str, version_tag: str) -> MaterializationResult:
        """Rollback to a specific version of a materialized skill."""
        version_file = self._versions_dir / version_tag
        if not version_file.exists():
            return MaterializationResult(
                skill_name=name,
                version="unknown",
                agent_type=agent_type,
                output_path="",
                success=False,
                error=f"Version not found: {version_tag}",
            )

        content = version_file.read_text(encoding="utf-8")
        output_path = self._state_dir / f"{name}_{agent_type}.md"
        output_path.write_text(content, encoding="utf-8")

        return MaterializationResult(
            skill_name=name,
            version="rolled-back",
            agent_type=agent_type,
            output_path=str(output_path),
            success=True,
        )
