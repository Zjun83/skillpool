# SkillPool MCP Server — API Reference

> Protocol: JSON-RPC 2.0 over stdio  
> Protocol Version: `2024-11-05`

## Overview

The SkillPool MCP Server exposes skill registry operations as MCP tools. It communicates
via stdio transport — the client writes JSON-RPC requests to the server's stdin and reads
JSON-RPC responses from stdout.

## Lifecycle

### `initialize`

Required first message. Returns server capabilities and protocol version.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": { "name": "my-client", "version": "1.0.0" }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": { "tools": { "listChanged": false } },
    "serverInfo": { "name": "skillpool", "version": "0.1.0" }
  }
}
```

---

## Tool Discovery

### `tools/list`

Returns all available tools and their input schemas.

**Request:**
```json
{ "jsonrpc": "2.0", "id": 2, "method": "tools/list" }
```

**Response:** Array of tool definitions (see Tools section below).

---

## Tools

### `skill_list`

List all registered skills, optionally filtered by minimum quality score.

**Input Schema:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `min_score` | number | No | Minimum quality score filter (0.0–1.0) |

**Example:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "skill_list",
    "arguments": { "min_score": 0.7 }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "[{\"name\": \"code-review\", \"quality_score\": 0.85, ...}]"
      }
    ]
  }
}
```

---

### `skill_get`

Get details of a specific skill by name.

**Input Schema:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | **Yes** | Skill name to look up |

**Example:**
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "skill_get",
    "arguments": { "name": "code-review" }
  }
}
```

**Response (found):** Full skill entry as JSON text.  
**Response (not found):** `Skill 'xxx' not found`

---

### `skill_gate`

Run a quality gate check on a registered skill.

**Input Schema:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | **Yes** | Skill name to check |
| `override_key` | string | No | Emergency override key (bypasses failed gate) |

**Gate Logic:**
- Score ≥ 0.6 → `PASS`
- Score < 0.6 and no override → `FAIL`
- Score < 0.6 with valid override → `OVERRIDE`

**Example:**
```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "skill_gate",
    "arguments": { "name": "debugging", "override_key": "emergency-001" }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"name\": \"debugging\", \"status\": \"PASS\", \"score\": 0.78}"
      }
    ]
  }
}
```

---

## Error Handling

| Code | Message | Meaning |
|------|---------|---------|
| -32700 | Parse error | Invalid JSON in request |
| -32601 | Method not found | Unknown method name |

---

## Configuration

The server auto-discovers the `.skillpool/` directory by walking up from `cwd`.
If not found, it defaults to `cwd/.skillpool/`.

### Registry Format

Registry entries are stored in `.skillpool/registry.jsonl` — one JSON object per line:

```json
{"name": "skill-name", "version": "1.0.0", "status": "active", "quality_score": 0.85, "dimensions": {...}}
```

---

## Running the Server

```bash
# Direct
python -m skillpool.mcp_server

# Via entry point (after pip install)
skillpool-mcp
```
