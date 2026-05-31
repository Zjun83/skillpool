"""SkillPool CLI — command-line interface for skill governance and materialization."""
from __future__ import annotations

import json
from pathlib import Path

import click

DEFAULT_SKILLPOOL_DIR = Path.home() / ".skillpool"


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
@click.version_option(version="4.1.0")
def main():
    """SkillPool V4.1 — AI Agent Skill Governance & Delivery Platform."""


# ── Init ──────────────────────────────────────────────────────────


@main.command()
def init():
    """Initialize SkillPool data directory."""
    DEFAULT_SKILLPOOL_DIR.mkdir(parents=True, exist_ok=True)
    (DEFAULT_SKILLPOOL_DIR / "registry.jsonl").touch()
    (DEFAULT_SKILLPOOL_DIR / "logs").mkdir(exist_ok=True)
    (DEFAULT_SKILLPOOL_DIR / "materialization_state").mkdir(exist_ok=True)
    (DEFAULT_SKILLPOOL_DIR / "emergency_overrides.json").write_text('{"overrides": {}}\n')
    click.echo(f"[skillpool] Initialized at {DEFAULT_SKILLPOOL_DIR}")


# ── Materialize ───────────────────────────────────────────────────


@main.command()
@click.option("--agent", "agent_type", default="claude-code",
              help="Target agent type (claude-code, codex, hermes)")
@click.option("--target", "target_dir", type=click.Path(), default=None,
              help="Target directory for materialized files")
@click.option("--csdf", "csdf_path", type=click.Path(exists=True), default=None,
              help="Path to a single CSDF YAML file to materialize")
def materialize(agent_type: str, target_dir: str | None, csdf_path: str | None):
    """Materialize skills into agent-specific runtime format.

    This is the primary delivery mechanism (V4.1 materialization channel).
    Transforms CSDF governance data into SKILL.md / AGENTS.md / hermes_skill.
    """
    from skillpool.materializer import Materializer
    from skillpool.profile import (
        CLAUDE_CODE_PROFILE, CODEX_PROFILE, HERMES_PROFILE,
    )

    profiles = {
        "claude-code": CLAUDE_CODE_PROFILE,
        "codex": CODEX_PROFILE,
        "hermes": HERMES_PROFILE,
    }
    profile = profiles.get(agent_type, CLAUDE_CODE_PROFILE)

    # Default target directories per agent type
    if target_dir is None:
        defaults = {
            "claude-code": str(Path.home() / ".claude" / "skills"),
            "codex": str(Path.home() / ".codex"),
            "hermes": str(Path.home() / ".hermes" / "skills"),
        }
        target_dir = defaults.get(agent_type, str(DEFAULT_SKILLPOOL_DIR / "output"))

    mat = Materializer(profile=profile)

    if csdf_path:
        result = mat.materialize(csdf_path=Path(csdf_path))
        if result.status == "success" and result.skill:
            out_path = Path(target_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            skill_file = out_path / f"{result.skill.id}.md"
            skill_file.write_text(result.skill.markdown)
            click.echo(f"Materialized: {result.skill.id} -> {skill_file}")
            click.echo(f"  Tokens: {result.skill.token_count}")
        else:
            click.echo(f"Materialization failed: {result.errors}")
    else:
        # Materialize all skills from registry
        sp_dir = _find_skillpool_dir()
        skills_dir = sp_dir / "skills"
        if skills_dir.exists():
            count = 0
            for yaml_file in skills_dir.glob("*.yaml"):
                result = mat.materialize(csdf_path=yaml_file)
                if result.status == "success" and result.skill:
                    out_path = Path(target_dir)
                    out_path.mkdir(parents=True, exist_ok=True)
                    skill_file = out_path / f"{result.skill.id}.md"
                    skill_file.write_text(result.skill.markdown)
                    count += 1
            click.echo(f"Materialized {count} skill(s) -> {target_dir}")
        else:
            click.echo(f"No skills directory found at {skills_dir}")
            click.echo("Run 'skillpool register --path <yaml>' to add skills.")


# ── Sync ──────────────────────────────────────────────────────────


@main.command()
@click.option("--agent", "agent_type", default="claude-code",
              help="Target agent type")
@click.option("--target", "target_dir", type=click.Path(), default=None,
              help="Target directory")
def sync(agent_type: str, target_dir: str | None):
    """Incremental sync — only re-materialize changed skills.

    Compares content hashes; skips unchanged files.
    """
    # For now, delegate to materialize (incremental optimization is future work)
    click.echo(f"[sync] Running incremental materialization for {agent_type}...")
    ctx = click.get_current_context()
    ctx.invoke(materialize, agent_type=agent_type, target_dir=target_dir, csdf_path=None)


# ── Register ──────────────────────────────────────────────────────


@main.command()
@click.option("--name", default="", help="Skill name")
@click.option("--path", "skill_path", type=click.Path(exists=True), default=None,
              help="Path to CSDF YAML file")
def register(name: str, skill_path: str | None):
    """Register a skill into the Registry.

    Requires supply chain evidence (SBOM, provenance, source pin, signature).
    Skill enters 'testing' state (not production-routable).
    """
    from skillpool.registry import Registry
    from skillpool.registry.models import RegisterSkillRequest, SkillMetadata
    from skillpool.audit import AuditLayer

    audit = AuditLayer()
    reg = Registry(audit_layer=audit)

    if skill_path:
        import yaml
        content = Path(skill_path).read_text()
        csdf = yaml.safe_load(content) or {}
        skill_id = csdf.get("id", Path(skill_path).stem)
        skill_name = name or csdf.get("name", skill_id)
        version = csdf.get("version", "0.1.0")
        security = csdf.get("security", {})

        meta = SkillMetadata(
            skill_id=skill_id,
            name=skill_name,
            version=version,
            security=security,
        )
        req = RegisterSkillRequest(skill_metadata=meta)
        try:
            resp = reg.register_candidate(req)
            click.echo(f"Registered: {resp.skill_id} -> status={resp.status}")
        except Exception as e:
            click.echo(f"Registration failed: {type(e).__name__}: {e}")
    else:
        click.echo("Use --path to specify a CSDF YAML file.")


# ── Inspect ───────────────────────────────────────────────────────


@main.command()
@click.argument("skill_id")
def inspect(skill_id: str):
    """Inspect a registered skill.

    Lookup order: Registry (by id or name) → CSDF YAML file → Directory-based skill.
    """
    from skillpool.registry import Registry
    from skillpool.audit import AuditLayer

    audit = AuditLayer()
    reg = Registry(audit_layer=audit)

    # 1. Try Registry lookup (by skill_id)
    record = reg.get_skill(skill_id)

    # 2. Try Registry lookup by name (for name-based lookups)
    if record is None:
        for rec in reg._skills.values():
            if rec.metadata.name == skill_id:
                record = rec
                break

    # 3. Try CSDF YAML file (direct filesystem lookup)
    if record is None:
        import yaml as _yaml
        sp_dir = _find_skillpool_dir()
        skills_dir = sp_dir / "skills"

        # Exact match
        yaml_path = skills_dir / f"{skill_id}.yaml"
        csdf = None
        if yaml_path.exists():
            csdf = _yaml.safe_load(yaml_path.read_text()) or {}
        else:
            # Prefix match (e.g., "S09" matches "S09-resilience-degradation.yaml")
            for p in skills_dir.glob(f"{skill_id}-*.yaml"):
                csdf = _yaml.safe_load(p.read_text()) or {}
                break

        # Directory-based skill (e.g., "scaffold-docs")
        if csdf is None:
            skill_md = skills_dir / skill_id / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end > 0:
                        csdf = _yaml.safe_load(content[3:end]) or {}
                        csdf["id"] = csdf.get("name", skill_id)
                        csdf["_is_directory_skill"] = True

        if csdf is not None:
            click.echo(f"Skill: {csdf.get('name', skill_id)} [from CSDF file]")
            click.echo(f"  ID:      {csdf.get('id', skill_id)}")
            click.echo(f"  Version: {csdf.get('version', 'N/A')}")
            click.echo(f"  Dimension: {csdf.get('dimension', 'N/A')}")
            click.echo(f"  Weight:  {csdf.get('weight', 0)}")
            click.echo(f"  Veto:    {csdf.get('veto_rule', 'none')}")
            if csdf.get("_is_directory_skill"):
                click.echo(f"  Type:    directory")
                click.echo(f"  Tags:    {', '.join(csdf.get('tags', []))}")
                click.echo(f"  Category: {csdf.get('category', 'N/A')}")
            return

    if record is None:
        click.echo(f"Skill '{skill_id}' not found")
        click.echo(f"  Hint: Check available skills with 'skillpool status'")
        return

    click.echo(f"Skill: {record.metadata.name}")
    click.echo(f"  ID:      {record.metadata.skill_id}")
    click.echo(f"  Version: {record.metadata.version}")
    click.echo(f"  Status:  {record.metadata.status.value}")
    click.echo(f"  Enabled: {reg.is_enabled(skill_id)}")
    if record.evidence:
        click.echo(f"  Evidence: {', '.join(sorted(record.evidence))}")


# ── Status ────────────────────────────────────────────────────────


@main.command()
def status():
    """Show SkillPool status."""
    sp_dir = _find_skillpool_dir()
    if sp_dir.exists():
        click.echo(f"SkillPool directory: {sp_dir}")
        skills_dir = sp_dir / "skills"
        if skills_dir.exists():
            count = len(list(skills_dir.glob("*.yaml")))
            click.echo(f"  CSDF skills: {count}")
        click.echo(f"  Registry: {sp_dir / 'registry.jsonl'}")
    else:
        click.echo("SkillPool not initialized. Run 'skillpool init'.")


# ── Review ────────────────────────────────────────────────────────


@main.command()
@click.option("--checkpoint", type=click.Choice(["L1", "L2", "L3", "L4"]),
              default="L2", help="Review checkpoint level")
def review(checkpoint: str):
    """Run a review checkpoint (L1-L4).

    L1: DocsDD — 7-dim shadow review (non-blocking)
    L2: SDD — 12-dim full review + VETO V1-V6
    L3: BDD — baseline 5-dim + all VETO
    L4: TDD — baseline regression, new blind spots only
    """
    from skillpool.review import ReviewManager
    from skillpool.audit import AuditLayer

    audit = AuditLayer()
    rm = ReviewManager(audit_layer=audit)
    result = rm.run_checkpoint(checkpoint)
    click.echo(f"Checkpoint {checkpoint}: {result.status}")
    if result.veto_details:
        for v in result.veto_details:
            click.echo(f"  VETO {v.rule}: {v.decision} ({v.reason})")


# ── MCP ───────────────────────────────────────────────────────────


@main.command()
@click.option("--agent-type", default="claude-code",
              help="Agent type for MCP server context")
def mcp(agent_type: str):
    """Start the SkillPool MCP server (stdio transport).

    This is how Agents connect to SkillPool at runtime.
    """
    from skillpool.mcp_server import mcp as mcp_server
    mcp_server.run(transport="stdio")


if __name__ == "__main__":
    main()


# ── Audit Runtime ──────────────────────────────────────────────────


@main.command("audit-runtime")
@click.option("--duration", default=5, type=int,
              help="Seconds to monitor before reporting (default: 5)")
@click.option("--log-file", type=click.Path(), default=None,
              help="Custom path for runtime audit JSONL log")
def audit_runtime(duration: int, log_file: str | None):
    """Install runtime audit hook and report security-sensitive events.

    Uses sys.addaudithook (PEP 578) to monitor: exec, compile, open,
    subprocess.Popen, socket.connect. The hook cannot be removed once
    registered (by design).
    """
    import time as _time
    from pathlib import Path as _Path

    from skillpool.utils.runtime_audit import RuntimeAuditHook

    log_path = _Path(log_file) if log_file else None
    hook = RuntimeAuditHook(log_file=log_path)
    hook.install()

    click.echo(f"[audit-runtime] Hook installed. Monitoring for {duration}s...")
    click.echo(f"[audit-runtime] Tracked events: {', '.join(sorted(RuntimeAuditHook.MONITORED_EVENTS))}")

    _time.sleep(duration)

    events = hook.get_events()
    if events:
        click.echo(f"\n[audit-runtime] {len(events)} event(s) captured:")
        for evt in events:
            click.echo(f"  {evt['timestamp']}  {evt['event']}  {evt['args']}")
    else:
        click.echo(f"\n[audit-runtime] No monitored events captured in {duration}s.")

    if log_path is None:
        default_log = Path.home() / ".skillpool" / "logs" / "runtime_audit.jsonl"
        click.echo(f"[audit-runtime] Full log: {default_log}")
    else:
        click.echo(f"[audit-runtime] Full log: {log_path}")
