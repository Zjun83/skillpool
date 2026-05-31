# SkillPool V4.1 Infrastructure Gap Analysis

> **Date**: 2026-05-31
> **Version**: V4.1.0 (pip-installed, editable from `/root/skillpool`)
> **Test Baseline**: 765 passed (3.52s)

## Executive Summary

SkillPool V4.1 is installed and functionally complete at the code level (765 tests passing). The primary gaps are in **runtime infrastructure stability** (systemd services crash-looping), **agent integration parity** (Hermes sync broken, Codex using stdio instead of gateway), and **gateway routing** (vMCP not proxying skillpool despite being configured). The core package, CLI, materialization pipeline, and Claude Code integration are all operational.

---

## Status Matrix

| # | Area | Component | Status | Evidence |
|---|------|-----------|--------|----------|
| 1 | MCP Server | `skillpool-mcp` in PATH | GREEN | `/root/hermes-agent/.venv/bin/skillpool-mcp` |
| 2 | MCP Server | systemd service `mcp-gateway-skillpool` | YELLOW | `activating auto-restart` (crash loop, restart counter high) |
| 3 | MCP Server | MCP endpoint on :8001 | GREEN | Responds to `initialize` JSON-RPC |
| 4 | vMCP Gateway | `vmcp-gateway.service` on :9000 | YELLOW | `activating auto-restart`, restart counter at 502 |
| 5 | vMCP Gateway | `/health` endpoint | RED | `gateway not responding` |
| 6 | vMCP Gateway | SkillPool route `/mcp/skillpool` | RED | Returns `{"detail":"Method Not Allowed"}` (FastAPI default, not proxying) |
| 7 | Agent: Claude Code | MCP config in `.mcp.json` | GREEN | `skillpool: { command: "skillpool-mcp" }` (stdio) |
| 8 | Agent: Claude Code | MCP config in `settings.json` | GREEN | `mcpServers` present with skillpool entry |
| 9 | Agent: Claude Code | Start hook (security + materialize) | GREEN | 1 hook: `skillpool-security-check.sh && skillpool materialize` |
| 10 | Agent: Codex | MCP config in `config.toml` | YELLOW | `skillpool: { command: "skillpool-mcp" }` (stdio, not via gateway) |
| 11 | Agent: OpenClaw | MCP config in `openclaw.json` | GREEN | All 3 agents (pm-agent, code-agent, site-agent) have `skillpool` MCP server |
| 12 | Agent: Hermes | Sync timer `skillpool-hermes-sync.timer` | RED | Service `failed` (exit code 127 = command not found) |
| 13 | Skills: CSDF YAML | Skills in `~/.skillpool/skills/` | GREEN | 22 YAML files (S00-S21) + `skill_graph.yaml` |
| 14 | Skills: Materialized | Skills in `~/.claude/skills/` | GREEN | 24 `.md` files (S00-S21 + unknown.md) + `multi-dim-review` symlink + `agent-reach` |
| 15 | Skills: Multi-dim-review | Full skill directory | GREEN | RULES.md, SKILL.md, state.yaml, blindspots/, changelog/, backups/, archive/ |
| 16 | Package | pip installation | GREEN | V4.1.0, editable install from `/root/skillpool` |
| 17 | Package | CLI `skillpool` | GREEN | `skillpool --help` works, subcommands: init, materialize, etc. |
| 18 | Tests | pytest baseline | GREEN | 765 passed, 0 failed |
| 19 | Security | `skillpool-security-check.sh` | GREEN | Script exists, validates CSDF fields + dangerous patterns |
| 20 | Security | vMCP audit logging | YELLOW | Service crash-looping, audit log not being written |

---

## Detailed Findings

### GREEN: Fully Operational

**1. Package Installation & CLI**
- `skillpool` V4.1.0 installed as editable package at `/root/hermes-agent/.venv/lib/python3.12/site-packages`
- Source at `/root/skillpool`, dependencies: click, fastmcp, pydantic, pyyaml
- CLI fully functional with `init`, `materialize`, and other subcommands

**2. Test Suite**
- 765 tests passing in 3.52s -- no failures, no skips reported
- Covers all modules: lifecycle, profile, gate, telemetry, materializer, resolver, review, cost, health, paradigm, audit, evolver, graph, monitor, registry

**3. Claude Code Integration**
- MCP server configured in both `.mcp.json` (project-level) and `settings.json` (user-level)
- Start hook runs security check + materialization on every session start
- 24 materialized skill files in `~/.claude/skills/`
- `multi-dim-review` symlinked to `~/.skillpool/skills/multi-dim-review/`

**4. OpenClaw Integration**
- All 3 OpenClaw agents (pm-agent, code-agent, site-agent) have `skillpool` MCP server configured
- Using stdio transport (`command: "skillpool-mcp"`)

**5. CSDF Skill Definitions**
- 22 YAML skill definitions (S00-S21) in `~/.skillpool/skills/`
- `skill_graph.yaml` dependency graph present
- Multi-dim-review skill fully populated with RULES.md, SKILL.md, state.yaml, blindspots/, changelog/, backups/, archive/

**6. Security Check Script**
- `/usr/local/bin/skillpool-security-check.sh` validates YAML syntax, required CSDF fields, and dangerous patterns
- Integrated into Claude Code Start hook

---

### YELLOW: Partially Operational

**7. MCP Gateway Service (`mcp-gateway-skillpool.service`)**
- **Status**: `activating auto-restart` -- service is crash-looping
- **Port**: 8001 (supergateway stdio-to-StreamableHTTP)
- **MCP endpoint**: Despite crash-loop, the MCP endpoint on :8001 does respond to `initialize` requests, suggesting the service restarts frequently enough to serve requests intermittently
- **Root cause**: Likely the supergateway process is crashing after startup. The service was `enabled` and recently restarted (9s uptime at time of check)
- **Impact**: Intermittent availability for HTTP-based MCP clients; stdio clients (Claude Code, Codex, OpenClaw) are unaffected since they launch `skillpool-mcp` directly

**8. vMCP Gateway Service (`vmcp-gateway.service`)**
- **Status**: `activating auto-restart`, restart counter at 502
- **Port**: 9000 (FastAPI security gateway)
- **Health endpoint**: Not responding at `http://127.0.0.1:9000/health`
- **SkillPool route**: Returns FastAPI default `Method Not Allowed` instead of proxying to :8001
- **Root cause**: The gateway process starts but crashes shortly after (502 restarts accumulated). The routing configuration may be correct but the service never stabilizes long enough to serve traffic
- **Impact**: All HTTP-routed MCP traffic (ClawMem, agent-search, codex-guard) is unreliable. Clients using direct stdio connections bypass this issue

**9. Codex Integration**
- **Config**: `config.toml` has `[mcp_servers.skillpool]` with `command = "skillpool-mcp"` (stdio)
- **Gap**: Not configured to use the vMCP gateway route (`http://127.0.0.1:9000/mcp/skillpool`), which would provide audit logging and security filtering
- **Impact**: Codex can use SkillPool but bypasses the security gateway. This is acceptable while the gateway is unstable but should be migrated once the gateway stabilizes

**10. vMCP Audit Logging**
- **Expected**: `/var/log/vmcp-audit.jsonl` with 34-field OTel audit records
- **Actual**: Gateway is crash-looping, so audit records are not being written
- **Impact**: No centralized audit trail for MCP tool calls through the gateway

---

### RED: Not Operational

**11. vMCP Gateway Health & Routing**
- **Health**: `http://127.0.0.1:9000/health` returns no response
- **Routing**: `http://127.0.0.1:9000/mcp/skillpool` returns FastAPI default error, not proxying to :8001
- **Root cause**: The `vmcp-gateway.py` process crashes repeatedly (502 restarts). The service starts, logs "Application startup complete", then crashes. This suggests a runtime error in the request handling path, possibly in the proxy/routing logic
- **Impact**: The entire vMCP security layer is non-functional. All MCP traffic that should be routed through the gateway (ClawMem, agent-search, codex-guard, skillpool) is unavailable via HTTP

**12. Hermes Sync Service**
- **Service**: `skillpool-hermes-sync.service` -- `failed` (exit code 127)
- **Timer**: `skillpool-hermes-sync.timer` -- `active` (triggering the failing service)
- **Script**: `/usr/local/bin/skillpool-hermes-sync.sh` exists and contains `skillpool materialize --agent hermes --target ~/.hermes/skills/`
- **Root cause**: Exit code 127 means "command not found". The `skillpool` CLI is installed in the Hermes venv (`/root/hermes-agent/.venv/bin/skillpool-mcp`) but the systemd service runs as `root` without the venv in PATH. The script needs the full path to the `skillpool` binary or the venv must be activated
- **Impact**: Hermes does not receive materialized skills. The `~/.hermes/skills/` directory is not being populated

---

## Remediation Plan

### Priority 1: Fix Hermes Sync (exit code 127)

The fix is straightforward -- the sync script needs the full path to the `skillpool` binary.

**File**: `/usr/local/bin/skillpool-hermes-sync.sh`
**Change**: Replace `skillpool materialize` with `/root/hermes-agent/.venv/bin/skillpool materialize`
**Then**: `systemctl restart skillpool-hermes-sync.service`

### Priority 2: Stabilize vMCP Gateway

The gateway has accumulated 502 restarts. Investigation needed:

1. Check the gateway logs: `journalctl -u vmcp-gateway.service -n 50`
2. Check for Python import errors or missing dependencies in `/usr/local/bin/vmcp-gateway.py`
3. Verify the proxy target (`http://127.0.0.1:8001`) is reachable from the gateway process
4. Check if the FastAPI app has a `/health` route defined (it may not, causing 404s)
5. Consider adding a `RestartSec=5` to the unit file to slow the crash loop

### Priority 3: Stabilize MCP Gateway for SkillPool

The `mcp-gateway-skillpool.service` is also crash-looping but less severely. Same investigation pattern:

1. `journalctl -u mcp-gateway-skillpool.service -n 50`
2. Check if the supergateway process is exiting due to the backend `skillpool.mcp_server` crashing
3. Test the backend directly: `/root/hermes-agent/.venv/bin/python3 -m skillpool.mcp_server`

### Priority 4: Migrate Codex to Gateway Route (after P2/P3)

Once the vMCP gateway is stable, update Codex config:

```toml
[mcp_servers.skillpool]
url = "http://127.0.0.1:9000/mcp/skillpool"
```

This enables audit logging and security filtering for Codex MCP calls.

### Priority 5: Add vMCP Health Endpoint

The gateway should expose a `/health` endpoint that checks:
- Gateway process is alive
- All backend MCP servers are reachable
- Returns JSON with per-backend status

---

## Architecture Diagram (Current State)

```
                    +-----------------------+
                    |   Claude Code         |
                    |  (stdio: skillpool-mcp)|  GREEN
                    +-----------+-----------+
                                |
                    +-----------v-----------+
                    |   OpenClaw (3 agents) |
                    |  (stdio: skillpool-mcp)|  GREEN
                    +-----------+-----------+
                                |
                    +-----------v-----------+
                    |   Codex               |
                    |  (stdio: skillpool-mcp)|  YELLOW (no gateway)
                    +-----------+-----------+
                                |
              +-----------------v------------------+
              |         skillpool-mcp              |
              |  /root/hermes-agent/.venv/bin/     |  GREEN
              +-----------------+------------------+
                                |
              +-----------------v------------------+
              |    SkillPool V4.1 Core             |
              |    765 tests | 22 CSDF skills      |  GREEN
              +------------------------------------+

              +-----------------+------------------+
              |  mcp-gateway-skillpool (:8001)     |  YELLOW (crash loop)
              |  supergateway stdio->HTTP          |
              +-----------------+------------------+
                                |
              +-----------------v------------------+
              |  vmcp-gateway (:9000)              |  RED (502 restarts)
              |  FastAPI security proxy            |
              +------------------------------------+

              +-----------------+------------------+
              |  skillpool-hermes-sync             |  RED (exit 127)
              |  timer -> oneshot service          |
              +------------------------------------+
```

---

## Summary Counts

| Status | Count | Areas |
|--------|-------|-------|
| GREEN | 12 | Package, CLI, tests, Claude Code, OpenClaw, CSDF skills, materialized skills, security script |
| YELLOW | 4 | MCP gateway service, vMCP gateway service, Codex integration, audit logging |
| RED | 4 | vMCP health/routing, Hermes sync, vMCP proxy functionality, gateway audit trail |

**Overall Assessment**: The SkillPool V4.1 codebase and core delivery pipeline are production-ready. The gaps are exclusively in the **infrastructure/operations layer** -- systemd services that crash-loop and a sync script with a PATH issue. None of these gaps affect the core skill governance, materialization, or review functionality. They affect **observability** (audit logging) and **agent parity** (Hermes not receiving skills).
