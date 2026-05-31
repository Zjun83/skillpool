# Codex Integration with SkillPool

> **Date**: 2026-05-29
> **Status**: Active

## Configuration

### MCP Server
- Config file: `~/.codex/config.toml`
- SkillPool MCP: configured via `[mcp_servers.skillpool]`
- Command: `python3 -m skillpool.mcp_server`

### Skill Paths
- Original Codex skills: `~/.codex/skills/` (backed up to `*.bak/`)
- SkillPool canonical: `~/.skillpool/skills/`
- Symlinks: `~/.codex/skills/<name>/` → `~/.skillpool/skills/<name>/`
- System skills (NOT migrated): `~/.codex/skills/.system/` (5 built-in: imagegen, openai-docs, plugin-creator, skill-creator, skill-installer)

### Channels
| Operation | Channel | Tool |
|-----------|---------|------|
| Register skill | CLI | `skillpool register --path <SKILL.md>` |
| List skills | CLI/MCP | `skillpool list-skills` / `skill_list` |
| Get skill details | MCP | `skill_get` |
| Gate check | CLI/MCP | `skillpool gate <name>` / `skill_gate` |
| Check updates | MCP | `check_updates` |
| Report usage | MCP | `report_usage` |

### Audit
- Log file: `~/.skillpool/logs/audit.jsonl`
- Format: JSONL (one JSON object per line)
- Fields: timestamp, agent, skill_name, action, result

### Migrated Skills
55 skills registered from Codex (51 custom) + OpenClaw (3 custom) + project (12-dim-review).
All passed Gate check (quality_score ≥ 0.6).
