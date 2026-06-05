# SkillPool MCP API Reference

## Transport

SkillPool supports three MCP transports:

| Transport | Use Case | Configuration |
|-----------|----------|---------------|
| `streamable-http` | Production, multi-agent shared state | `--transport streamable-http --port 8101` |
| `sse` | Legacy browser clients | `--transport sse --port 8101` |
| `stdio` | Single-agent, development | `skillpool-mcp` (default) |

## Authentication

When `SKILLPOOL_API_KEY` is set, all requests require authentication:

- **HTTP header**: `Authorization: Bearer <key>`
- **Tool argument**: `api_key` parameter in tool call arguments

Unauthenticated requests return:
```json
{"error": "unauthorized", "detail": "Invalid or missing API key"}
```

## Resources

### `skill://list`

List all registered skills with L0 metadata.

**Response**: JSON array of skill objects with `id`, `name`, `version`, `dimension`, `weight`, `tags`.

### `skill://{id}/summary`

Get L1 summary of a skill (~200 tokens).

**Parameters**: `{id}` — skill ID (e.g., `S09`, `multi-dim-review`)

### `skill://{id}/definition`

Get full SKILL.md content (L2 tier).

**Parameters**: `{id}` — skill ID or name (dual lookup supported)

### `skill://{id}/manifest.yaml`

Get skill dependencies, conflicts, synergies, and veto rules.

### `skill://{id}/rules`

Get complete skill rules (for review skills).

### `bug://list`

List all collected bugs from BugCollector.

## Tools

### `skill_search`

Search skills by intent description.

**Arguments**:
- `intent` (string): Natural language search query

### `skill_get`

Get skill definition for a specific agent type.

**Arguments**:
- `skill_id` (string): Skill ID or name
- `agent_type` (string, optional): Agent type filter

### `skill_match`

Match skills to a task description.

**Arguments**:
- `task_description` (string): Task to match against
- `agent_type` (string, optional): Agent type filter

### `gate_check`

Evaluate gate decision for a skill operation.

**Arguments**:
- `skill_id` (string): Target skill
- `operation` (string): Operation type
- `context` (object, optional): Additional context

### `skill_register`

Register a skill candidate into the Registry.

**Arguments**:
- `skill_metadata` (object): Skill metadata including security evidence

### `skill_transition`

Transition a skill's lifecycle state.

**Arguments**:
- `skill_id` (string): Target skill
- `from_status` (string): Current status
- `to_status` (string): Target status
- `sandbox_result` (string, optional): Sandbox test result
- `policy_approval` (bool, optional): Policy approval flag

### `health_check`

Check system health status.

**Response**: Health status (SERVING/NOT_SERVING/DEGRADED) with details.

### `review_trigger`

Trigger a multi-dimension review checkpoint.

**Arguments**:
- `checkpoint` (string): L1/L2/L3/L4
- `target` (string): Review target description

### `monitor_evaluate`

Run five-dimension skill evaluation.

**Arguments**:
- `skill_id` (string): Target skill

### `security_scan`

Pre-materialization security gate scan.

**Arguments**:
- `skill_id` (string): Target skill
- `content` (string): Content to scan

### `telemetry_report`

Report a telemetry event.

**Arguments**:
- `event_type` (string): Event type
- `data` (object): Event data

## Supply Chain Evidence

Registry requires supply chain evidence based on `SKILLPOOL_EVIDENCE_TIER`:

| Tier | Required Evidence | Use Case |
|------|-------------------|----------|
| `dev` | None | Local development |
| `ci` | Source pin, SPDX SBOM | CI/CD pipeline |
| `prod` | SPDX SBOM, SLSA provenance, Source pin, Signature | Production |

Set via: `SKILLPOOL_EVIDENCE_TIER=dev`
