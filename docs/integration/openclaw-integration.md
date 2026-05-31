# OpenClaw Integration with SkillPool

> **Date**: 2026-05-29
> **Status**: Active

## Configuration

### MCP Server
- Config file: `~/.openclaw/openclaw.json`
- Added `mcpServers.skillpool` section
- Command: `python3 -m skillpool.mcp_server`
- Env: `SKILLPOOL_DIR=/root/.skillpool`

### Security Controls
- **Tool whitelist**: skill_list, skill_get, skill_gate, check_updates
- **Disabled tools**: report_usage, get_emergency_overrides, assess_paradigm
- **Audit log**: `~/.skillpool/logs/audit.jsonl`

### Skill Paths
- Original OpenClaw skills: `~/.openclaw/skills/` (backed up to `*.bak/`)
- SkillPool canonical: `~/.skillpool/skills/`
- Symlinks: `~/.openclaw/skills/<name>/` → `~/.skillpool/skills/<name>/`
- Bundled skills (NOT migrated): managed by OpenClaw internally, queryable via MCP

### Channels
| Operation | Channel | Tool |
|-----------|---------|------|
| Register skill | CLI | `skillpool register --path <SKILL.md>` |
| List skills | MCP | `skill_list` |
| Get skill details | MCP | `skill_get` |
| Gate check | MCP | `skill_gate` |
| Check updates | MCP | `check_updates` |

### Custom Skills Migrated
- agent-reach (17-platform internet access)
- file-task-execution-skill (filesystem collaboration)
- knowledge-refiner (Obsidian Vault import)
