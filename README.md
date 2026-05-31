# SkillPool v4.3.0

> AI Agent Skill Governance & Delivery Platform — MCP Resources/Tools/Prompts architecture

## Quick Start

```bash
# Install (editable)
pip install -e .

# CLI
skillpool --version
skillpool inspect S09

# MCP Server (stdio)
skillpool-mcp
```

## Architecture (V4.3 Dual-Channel)

| Channel | Transport | Purpose |
|---------|-----------|---------|
| CLI | Start Hook | Materialization — one-time SKILL.md file writes |
| MCP Resources | stdio | Read-only context delivery (skill definitions, audit, bugs) |
| MCP Tools | stdio | State-changing governance actions (register, gate, heal) |
| MCP Prompts | stdio | User-controlled templates (review, skill context) |

## MCP Resources (Read-Only)

| URI | Description |
|-----|-------------|
| `skill://list` | All skills metadata (L0 tier, ~50 tokens/skill) |
| `skill://{id}/summary` | Medium detail (L1 tier, ~200 tokens) |
| `skill://{id}/definition` | Full SKILL.md content (L2 tier) |
| `skill://{id}/manifest.yaml` | Dependencies, conflicts, veto rules |
| `skill://{id}/x-execution` | Execution method + input/output schema |
| `skill://graph` | Skill dependency DAG |
| `audit://records` | Audit hash chain (read-only, immutable) |
| `bug://list` | BugCollector defect records |

## MCP Tools (Governance Actions)

| Tool | Description |
|------|-------------|
| `gate_check` | Gate decision (ALLOW/GUARD/ESCALATE/DENY) |
| `telemetry_report` | Report telemetry event |
| `audit_verify` | Verify audit hash chain integrity |
| `security_scan` | Pre-materialization security gate |
| `healing_scan` | Scan bugs for recurring defects, propose healing |
| `healing_execute` | Execute healing with BDD verify + auto-rollback |
| `skill_register` | Register skill candidate into Registry |
| `skill_transition` | Transition skill lifecycle state |
| `evolution_trigger` | Record defect triggering evolution |
| `evolution_proposal` | Create recommendation-only evolution proposal |
| `monitor_evaluate` | Five-dimension skill evaluation |
| `health_check` | System health check |
| `review_trigger` | Trigger review checkpoint (L1-L4) |

## MCP Prompts (User-Controlled)

| Prompt | Description |
|--------|-------------|
| `skill_context {skill_id}` | Inject skill definition + dependencies |
| `trigger_review` | Multi-dimension review (uses MCP Resources) |
| `gate_status {skill_id}` | Check gate decision for a skill |

## Security Architecture

Three-layer pre-materialization security gate:
1. **Hook layer**: SecurityScanner — YAML safety + dangerous pattern scanning
2. **MCP layer**: `gate_check` tool — complexity assessment + profile matching
3. **Audit layer**: Immutable hash chain — all actions recorded, tamper-evident

Timeout degradation: `gate_check` → DENY, `telemetry` → silent, `health_check` → DEGRADED

## Key Modules

| Module | Description |
|--------|-------------|
| Lifecycle | 9-state skill lifecycle state machine |
| Profile | Agent capability profiles (Claude Code/Codex/Hermes) |
| Gate | Gate management + complexity assessment |
| Materializer | CSDF → SKILL.md materialization engine (14 mapping rules) |
| LazySkillLoader | L0/L1/L2 tiered loading with cache + thread safety |
| Resolver | Skill chain resolution + DAG + circuit breaker + rate limiter |
| Review | Review trigger + VETO V1-V6 + L1-L4 checkpoints |
| BugCollector | 4-stage defect pipeline (Capture→Enrich→Filter→Persist) |
| SelfHealingLoop | BugCollector → Evolver → BDD verify → auto-rollback |
| SecurityScanner | YAML safety + dangerous pattern scanning + signature placeholder |
| Audit | 34-field OTel audit + SHA-256 hash chain |
| Evolver | Defect accumulation + Add/Merge/Discard evolution |
| Registry | Skill registry + supply chain evidence + 9-state lifecycle |

## Test Baseline

1027 tests passing (V4.3.0)

## License

MIT
