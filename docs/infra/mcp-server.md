# MCP Server

SkillPool exposes 7 Model Context Protocol tools for AI agent integration.

## Configuration

Add to your MCP client config:

```json
{
  "mcpServers": {
    "skillpool": {
      "command": "python",
      "args": ["-m", "skillpool.mcp_server"],
      "env": {
        "SKILLPOOL_DIR": ".skillpool"
      }
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| skill_list | List all registered skills |
| skill_get | Get details of a specific skill |
| skill_assess_paradigm | Assess which paradigm a skill belongs to |
| check_updates | Check for skill updates |
| get_emergency_overrides | Get emergency override configurations |
| report_usage | Report skill usage metrics |
| get_gate_status | Get gate status for a skill |

## Protocol

The MCP server runs on stdio and follows the MCP specification:

1. Client sends `initialize` request
2. Server responds with capabilities
3. Client sends `tools/list` to discover tools
4. Client sends `tools/call` to invoke tools
