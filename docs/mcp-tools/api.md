# SkillPool MCP Server API

## Protocol

- **Transport**: stdio (JSON-RPC 2.0 over stdin/stdout)
- **Protocol Version**: 2024-11-05

## Methods

### initialize

Initialize the MCP connection.

**Request:**
```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": {"tools": {"listChanged": false}},
    "serverInfo": {"name": "skillpool", "version": "0.1.0"}
  }
}
```

### tools/list

List available MCP tools.

**Request:**
```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
```

**Response:** Array of tool descriptors (see Tools below).

## Tools

### skill_list

List all registered skills with optional quality score filter.

| Parameter   | Type   | Required | Description                |
|-------------|--------|----------|----------------------------|
| min_score   | number | No       | Minimum quality score (0-1)|

**Example:**
```json
{"name": "skill_list", "arguments": {"min_score": 0.7}}
```

### skill_get

Get details of a specific skill by name.

| Parameter   | Type   | Required | Description    |
|-------------|--------|----------|----------------|
| name        | string | Yes      | Skill name     |

**Example:**
```json
{"name": "skill_get", "arguments": {"name": "code-review"}}
```

### skill_gate

Run quality gate check on a skill.

| Parameter     | Type   | Required | Description              |
|---------------|--------|----------|--------------------------|
| name          | string | Yes      | Skill name               |
| override_key  | string | No       | Emergency override key   |

**Example:**
```json
{"name": "skill_gate", "arguments": {"name": "debugging", "override_key": "ops-001"}}
```

**Possible statuses:** `PASS`, `FAIL`, `OVERRIDE`

## Error Codes

| Code   | Meaning        |
|--------|----------------|
| -32700 | Parse error    |
| -32601 | Method not found |

## Starting the Server

```bash
skillpool-mcp
```

Or via Python:
```bash
python -m skillpool.mcp_server
```
