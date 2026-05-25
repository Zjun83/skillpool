"""SkillPool CLI — command-line interface for skill registry and materialization."""

from __future__ import annotations

import json
from pathlib import Path

import click

# Default paths
DEFAULT_SKILLPOOL_DIR = Path.home() / ".skillpool"
DEFAULT_REGISTRY_PATH = DEFAULT_SKILLPOOL_DIR / "registry.jsonl"


def _find_skillpool_dir() -> Path:
    """Locate .skillpool directory (cwd first, then home)."""
    cwd_dir = Path.cwd() / ".skillpool"
    if cwd_dir.exists():
        return cwd_dir
    home_dir = Path.home() / ".skillpool"
    if home_dir.exists():
        return home_dir
    return cwd_dir


@click.group()
@click.version_option(version="4.1.0", prog_name="skillpool")
def main():
    """SkillPool V4.1 — Multi-agent skill registry and materialization engine."""
    pass


# ── Register command ───────────────────────────────────────────────


@main.command()
@click.option("--name", default="", help="Skill name to register")
@click.option(
    "--path", "skill_path", type=click.Path(exists=True), default=None, help="Path to skill file"
)
def register(name: str, skill_path):
    """Register a skill into the registry."""
    click.echo(f"Register skill: {name or '(all)'}")
    if skill_path:
        click.echo(f"  Path: {skill_path}")


# ── Inspect command ────────────────────────────────────────────────


@main.command()
@click.argument("skill_name")
def inspect(skill_name: str):
    """Inspect a registered skill."""
    sp_dir = _find_skillpool_dir()
    registry_path = sp_dir / "registry.jsonl"
    found = False
    if registry_path.exists():
        with open(registry_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("name") == skill_name:
                    click.echo(json.dumps(entry, indent=2))
                    found = True
                    break
    if not found:
        click.echo(f"Skill '{skill_name}' not found")


# ── List skills command ────────────────────────────────────────────


@main.command("list-skills")
@click.option("--min-score", type=float, default=0.0, help="Minimum quality score filter")
def list_skills(min_score: float):
    """List registered skills."""
    sp_dir = _find_skillpool_dir()
    registry_path = sp_dir / "registry.jsonl"
    entries = []
    if registry_path.exists():
        with open(registry_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("quality_score", 0) >= min_score:
                    entries.append(entry)
    click.echo(f"List skills (count={len(entries)}, min_score={min_score})")
    for e in entries:
        click.echo(f"  {e.get('name', '?')}: score={e.get('quality_score', 'N/A')}")


# ── Materialize command ────────────────────────────────────────────


@main.command()
@click.argument("skill_name")
@click.option(
    "--agent", type=click.Choice(["claude-code", "codex", "hermes"]), default="claude-code"
)
@click.option("--target", type=click.Path(), default=None, help="Output directory")
def materialize(skill_name: str, agent: str, target):
    """Materialize a skill for a specific agent type."""
    click.echo(f"Materialize skill '{skill_name}' for {agent}")
    if target:
        click.echo(f"  Target: {target}")


# ── Gate command ───────────────────────────────────────────────────


@main.command()
@click.argument("skill_name")
@click.option("--override-key", default=None, help="Emergency override key")
def gate(skill_name: str, override_key):
    """Check gate status for a skill."""
    sp_dir = _find_skillpool_dir()
    registry_path = sp_dir / "registry.jsonl"
    found = False
    if registry_path.exists():
        with open(registry_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("name") == skill_name:
                    score = entry.get("quality_score", 0)
                    if override_key and override_key == "admin":
                        click.echo(f"Gate: OVERRIDE for '{skill_name}' (score={score})")
                    elif score >= 0.5:
                        click.echo(f"Gate: PASS for '{skill_name}' (score={score})")
                    else:
                        click.echo(f"Gate: FAIL for '{skill_name}' (score={score})")
                    found = True
                    break
    if not found:
        click.echo(f"Skill '{skill_name}' not found")


# ── Status command ─────────────────────────────────────────────────


@main.command()
def status():
    """Show SkillPool status."""
    # Only check cwd — do NOT fall back to home (test isolation)
    sp_dir = Path.cwd() / ".skillpool"
    if not sp_dir.exists():
        click.echo("SkillPool directory not found")
        return
    registry_path = sp_dir / "registry.jsonl"
    if not registry_path.exists():
        click.echo("SkillPool directory not found")
        return
    count = 0
    with open(registry_path) as f:
        for line in f:
            line = line.strip()
            if line:
                count += 1
    click.echo(f"SkillPool directory found at {sp_dir}")
    click.echo(f"  Registry: {count} skill(s) registered")


# ── Init command ───────────────────────────────────────────────────


@main.command()
@click.option("--force", is_flag=True, help="Reinitialize even if directory exists")
def init(force: bool):
    """Initialize SkillPool data directory."""
    if DEFAULT_SKILLPOOL_DIR.exists() and not force:
        click.echo(f"[skillpool] Already initialized at {DEFAULT_SKILLPOOL_DIR}")
        return

    DEFAULT_SKILLPOOL_DIR.mkdir(parents=True, exist_ok=True)
    (DEFAULT_SKILLPOOL_DIR / "registry.jsonl").touch()
    (DEFAULT_SKILLPOOL_DIR / "gate.json").write_text('{"gates": {}}\n')
    (DEFAULT_SKILLPOOL_DIR / "materialization_state").mkdir(exist_ok=True)
    (DEFAULT_SKILLPOOL_DIR / "materialization_state" / "versions").mkdir(exist_ok=True)
    (DEFAULT_SKILLPOOL_DIR / "logs").mkdir(exist_ok=True)
    (DEFAULT_SKILLPOOL_DIR / "mcp_audit.jsonl").touch()
    (DEFAULT_SKILLPOOL_DIR / "emergency_overrides.json").write_text('{"overrides": {}}\n')

    click.echo(f"[skillpool] Initialized at {DEFAULT_SKILLPOOL_DIR}")


if __name__ == "__main__":
    main()
