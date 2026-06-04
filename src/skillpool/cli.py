"""SkillPool CLI — command-line interface for skill governance and materialization."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import click

from skillpool.config import get_data_dir

DEFAULT_SKILLPOOL_DIR = get_data_dir()


def _find_skillpool_dir() -> Path:
    """Locate .skillpool directory (cwd first, then env/home)."""
    cwd_dir = Path.cwd() / ".skillpool"
    if cwd_dir.exists():
        return cwd_dir
    env_dir = get_data_dir()
    if env_dir.exists():
        return env_dir
    return cwd_dir


@click.group()
@click.version_option(version="4.3.0")
def main():
    """SkillPool V4.3 — AI Agent Skill Governance & Delivery Platform."""


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
@click.option("--force", is_flag=True, help="Force re-materialize all skills")
def sync(agent_type: str, target_dir: str | None, force: bool):
    """Incremental sync — only re-materialize changed skills.

    Compares content hashes; skips unchanged files.
    """
    import hashlib
    import yaml

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

    sp_dir = _find_skillpool_dir()
    skills_dir = sp_dir / "skills"
    out_path = Path(target_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Hash state file for incremental sync
    hash_file = out_path / ".sync_hashes.yaml"
    old_hashes: dict[str, str] = {}
    if hash_file.exists() and not force:
        try:
            old_hashes = yaml.safe_load(hash_file.read_text()) or {}
        except yaml.YAMLError:
            old_hashes = {}

    mat = Materializer(profile=profile)
    new_hashes: dict[str, str] = {}
    synced = 0
    skipped = 0

    if not skills_dir.exists():
        click.echo(f"No skills directory found at {skills_dir}")
        return

    for yaml_file in skills_dir.glob("*.yaml"):
        content = yaml_file.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()[:16]
        skill_id = yaml_file.stem
        new_hashes[skill_id] = content_hash

        if not force and old_hashes.get(skill_id) == content_hash:
            skipped += 1
            continue

        result = mat.materialize(csdf_path=yaml_file)
        if result.status == "success" and result.skill:
            skill_file = out_path / f"{result.skill.id}.md"
            skill_file.write_text(result.skill.markdown)
            synced += 1

    # Also process directory-based skills
    for skill_dir in skills_dir.iterdir():
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            skill_md = skill_dir / "SKILL.md"
            content = skill_md.read_bytes()
            content_hash = hashlib.sha256(content).hexdigest()[:16]
            skill_id = skill_dir.name
            new_hashes[skill_id] = content_hash

            if not force and old_hashes.get(skill_id) == content_hash:
                skipped += 1
                continue

            # Copy directory skill as-is
            import shutil
            dest_dir = out_path / skill_id
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            shutil.copytree(skill_dir, dest_dir)
            synced += 1

    # Save new hashes
    hash_file.write_text(yaml.dump(new_hashes, default_flow_style=False))

    click.echo(f"[sync] Synced {synced} skill(s), skipped {skipped} unchanged -> {target_dir}")

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


@main.command()
@click.argument("skill_id")
@click.option("--upgrade-type", default="PATCH",
              type=click.Choice(["PATCH", "MINOR", "MAJOR"]),
              help="Evolution upgrade type")
@click.option("--updates", default=None,
              help="JSON string of field updates to apply")
def evolve(skill_id: str, upgrade_type: str, updates: str | None):
    """Execute an evolution for a skill: write changes to CSDF YAML + re-materialize.

    This is the CLI counterpart of the evolution_proposal + execute_evolution
    MCP tools, providing a direct command-line path for skill evolution.
    """
    from skillpool.evolver import EvolverLayer
    from skillpool.audit import AuditLayer

    audit = AuditLayer()
    evolver = EvolverLayer(audit_layer=audit)

    # Parse updates if provided
    update_dict = {}
    if updates:
        try:
            update_dict = json.loads(updates)
        except json.JSONDecodeError:
            click.echo(f"Invalid JSON in --updates: {updates}")
            return

    # Create proposal
    proposal = evolver.create_proposal(
        context={"skill_id": skill_id},
        upgrade_type=upgrade_type,
    )

    # Execute evolution
    result = evolver.execute_evolution(proposal.proposal_id, updates=update_dict)

    if result["status"] == "success":
        click.echo(f"Evolved: {skill_id} v{result['version']}")
        click.echo(f"  Proposal: {proposal.proposal_id}")
        click.echo(f"  YAML updated: {result['yaml_updated']}")
        if result.get("materialized"):
            click.echo(f"  Re-materialized: yes")
    else:
        click.echo(f"Evolution failed: {result.get('error', result['status'])}")


@main.command()
@click.argument("proposal_id")
def heal(proposal_id: str):
    """Execute a healing proposal: apply fix and verify via BDD.

    This is the CLI counterpart of the healing_execute MCP tool.
    Use 'skillpool review --checkpoint L3' to scan for bugs first.
    """
    from skillpool.evolver import EvolverLayer
    from skillpool.monitor.bug_collector import BugCollector
    from skillpool.monitor.self_healing import SelfHealingLoop
    from skillpool.audit import AuditLayer

    audit = AuditLayer()
    evolver = EvolverLayer(audit_layer=audit)
    collector = BugCollector(audit_layer=audit)
    loop = SelfHealingLoop(bug_collector=collector, evolver=evolver, audit_layer=audit)

    result = loop.execute_healing(proposal_id)

    if result["status"] == "not_found":
        click.echo(f"Healing proposal '{proposal_id}' not found.")
        click.echo("Run a scan first to generate proposals.")
    elif result["status"] == "needs_human":
        click.echo(f"MAJOR upgrade requires human approval.")
    elif result["status"] == "verified":
        click.echo(f"Healed: {result['proposal_id']}")
        click.echo(f"  BDD passed: {result['verification']['bdd_passed']}")
        if result['verification'].get('yaml_updated') or result['verification'].get('yaml_restored'):
            click.echo(f"  YAML changes persisted: yes")
    elif result["status"] == "rolled_back":
        click.echo(f"Healing rolled back: {result['proposal_id']}")
        click.echo(f"  Reason: {result['verification']['reason']}")
    else:
        click.echo(f"Healing result: {result}")


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


# ── Gate ────────────────────────────────────────────────────────────


@main.group()
def gate():
    """4D paradigm gate management — assess, transition, status."""


@gate.command()
@click.argument("task_description")
@click.option("--policy", "policy_path", type=click.Path(exists=True), default=None,
              help="Path to gate.policy YAML file")
@click.option("--files", "changed_files", default=None,
              help="Comma-separated list of changed files")
def assess(task_description: str, policy_path: str | None, changed_files: str | None):
    """Assess task complexity and set gate level.

    Example: skillpool gate assess "new feature for core module" --policy gate.policy
    """
    from skillpool.gate_policy.state_machine import GateStateMachine
    from skillpool.gate_policy.parser import load_gate_policy

    policy = None
    if policy_path:
        policy = load_gate_policy(Path(policy_path))

    files_list = changed_files.split(",") if changed_files else []
    gate_path = Path(tempfile.gettempdir()) / "skillpool_gate.json"
    sm = GateStateMachine(gate_path)

    level = sm.assess(task_description, files_list, policy)
    click.echo(f"Assessed level: {level}")
    click.echo(f"Current phase: {sm.state.current_phase}")
    if sm.state.assessed_at:
        click.echo(f"Assessed at: {sm.state.assessed_at}")


@gate.command()
@click.argument("target_phase")
@click.option("--state-path", type=click.Path(), default=None,
              help="Path to gate.json file")
def transition(target_phase: str, state_path: str | None):
    """Transition gate to target phase.

    Valid phases: IDLE, ASSESSING, DOCSDD, SDD, BDD, TDD, REVIEW, COMPLETE

    Example: skillpool gate transition DOCSDD
    """
    from skillpool.gate_policy.state_machine import GateStateMachine
    from skillpool.gate_policy.parser import GatePolicyError

    gate_path = Path(state_path) if state_path else Path(tempfile.gettempdir()) / "skillpool_gate.json"
    sm = GateStateMachine(gate_path)

    try:
        result = sm.transition(target_phase)
        click.echo(f"Transitioned to: {result.current_phase}")
        click.echo(f"Phase history: {len(result.phase_history)} transitions")
    except GatePolicyError as e:
        click.echo(f"Error [{e.error_code}]: {e.detail}", err=True)
        raise SystemExit(1)


@gate.command("status")
@click.option("--state-path", type=click.Path(), default=None,
              help="Path to gate.json file")
def gate_status(state_path: str | None):
    """Show current gate state.

    Example: skillpool gate status
    """
    from skillpool.gate_policy.state_machine import GateStateMachine

    gate_path = Path(state_path) if state_path else Path(tempfile.gettempdir()) / "skillpool_gate.json"
    sm = GateStateMachine(gate_path)
    s = sm.state

    click.echo(f"Current phase: {s.current_phase}")
    click.echo(f"Assessed level: {s.assessed_level or 'N/A'}")
    click.echo(f"Incremental mode: {s.incremental_mode}")
    click.echo(f"Phase history: {len(s.phase_history)} transitions")
    if s.changed_files:
        click.echo(f"Changed files: {', '.join(s.changed_files)}")
    if s.review_checkpoint.triggered:
        click.echo(f"Review checkpoint: triggered (level={s.review_checkpoint.checkpoint_level})")
    click.echo(f"Artifacts: {len([v for v in s.artifacts.values() if v])} complete / {len(s.artifacts)} total")


@gate.command("reset")
@click.option("--state-path", type=click.Path(), default=None,
              help="Path to gate.json file")
def gate_reset(state_path: str | None):
    """Reset gate state to IDLE (preserves created_at).

    Example: skillpool gate reset
    """
    from skillpool.gate_policy.state_machine import GateStateMachine

    gate_path = Path(state_path) if state_path else Path(tempfile.gettempdir()) / "skillpool_gate.json"
    sm = GateStateMachine(gate_path)
    result = sm.reset()
    click.echo(f"Gate reset to: {result.current_phase}")
    click.echo(f"Preserved created_at: {result.metadata.created_at}")


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
        default_log = get_data_dir() / "logs" / "runtime_audit.jsonl"
        click.echo(f"[audit-runtime] Full log: {default_log}")
    else:
        click.echo(f"[audit-runtime] Full log: {log_path}")


# ---------------------------------------------------------------------------
# cost command group
# ---------------------------------------------------------------------------


@main.group()
def cost() -> None:
    """Cost estimation and budget management."""


@cost.command()
@click.argument("skill_id")
@click.option("--skill-length", type=int, default=0, help="Character count of skill definition")
@click.option("--review-level", type=click.Choice(["L0", "L1", "L2", "L3+L2+"]), default="L1", help="Complexity review level")
@click.option("--include-review-checkpoint/--no-review-checkpoint", default=False, help="Include review checkpoint overhead")
@click.option("--emergency-bypass-path", type=str, default=None, help="Path to emergency_overrides.json")
def estimate(
    skill_id: str,
    skill_length: int,
    review_level: str,
    include_review_checkpoint: bool,
    emergency_bypass_path: str | None,
) -> None:
    """Estimate session cost for a skill execution (P50 pricing).

    Uses conservative $0.003/1K tokens pricing model.
    """
    from skillpool.cost.token_governor import TokenGovernor, PRESET_AGENT_CONFIGS

    governor = TokenGovernor(PRESET_AGENT_CONFIGS)
    result = governor.estimate_session_cost(
        skill_id=skill_id,
        skill_length=skill_length,
        review_level=review_level,
        include_review_checkpoint=include_review_checkpoint,
        emergency_bypass_path=emergency_bypass_path,
    )
    click.echo(f"Skill: {result.skill_id}")
    click.echo(f"Skill Length: {result.skill_length} chars")
    click.echo(f"Token Count: {result.token_count}")
    click.echo(f"Base Cost: ${result.base_cost_usd:.6f}")
    if result.l2_review_overhead_usd > 0:
        click.echo(f"L2 Review Overhead: ${result.l2_review_overhead_usd:.6f}")
    if result.l3_review_overhead_usd > 0:
        click.echo(f"L3 Review Overhead: ${result.l3_review_overhead_usd:.6f}")
    if result.review_checkpoint_overhead_usd > 0:
        click.echo(f"Review Checkpoint Overhead: ${result.review_checkpoint_overhead_usd:.6f}")
    click.echo(f"Total Cost: ${result.total_cost_usd:.6f}")
    click.echo(f"Price: ${result.price_per_1k_tokens}/1K tokens (P50)")
    if not result.gate_passed:
        click.echo(f"Gate: BLOCKED — {result.gate_block_reason}")
    if result.emergency_bypass_active:
        click.echo("Emergency Bypass: ACTIVE")
