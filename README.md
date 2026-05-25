# SkillPool V4.1

Multi-agent skill registry, materialization, and lifecycle management.

## Quick Start

```bash
# Install
pip install -e .

# Initialize data directory
skillpool init

# Import existing skills
skillpool registry import ~/.codex/skills/

# Materialize for an agent
skillpool materialize --agent claude-code --target ~/.codex/skills/

# Health check
skillpool health
```

## Architecture

- **Registry** — CSDF-based skill registration with quality scoring
- **Materializer** — Agent-specific skill materialization (Claude Code / Codex / Hermes)
- **Gate** — Dual-track gate checking (soft advisory + hard veto)
- **MCP Server** — 7-tool stdio server for agent runtime queries
- **Evolver** — Skill evolution based on telemetry feedback
- **Bridge** — WAL, freeze detection, and maintenance for registry integrity
- **Audit** — Append-only audit log with event tracking and querying
- **Telemetry** — Usage tracking and skill performance metrics
- **Adapters** — Unified interface for Codex and Claude agent runtimes

## MCP Server Tools

SkillPool exposes 7 tools via stdio MCP protocol:

| Tool | Description |
|------|-------------|
| `skill_list` | List registered skills, optionally filtered by min quality score |
| `skill_get` | Get full details of a specific skill by name |
| `skill_gate` | Run quality gate check on a skill (pass/fail) |
| `check_updates` | Check for available updates by comparing skill versions |
| `report_usage` | Record a skill usage event with outcome tracking |
| `get_emergency_overrides` | List active emergency overrides with expiry status |
| `assess_paradigm` | Assess which paradigm(s) a skill belongs to |

### MCP Configuration

Add to your Codex `config.toml`:

```toml
[mcp_servers.skillpool]
command = "/path/to/python3"
args = ["-m", "skillpool.mcp_server"]
```

## Project Structure

```
skillpool/
├── src/skillpool/          # Source code
│   ├── registry.py         # Skill registration and lookup
│   ├── csdf.py             # CSDF document parser
│   ├── materializer.py     # Agent-specific materialization
│   ├── gate.py             # Quality gate checker
│   ├── quality.py          # Quality profiling and scoring
│   ├── mcp_server.py       # MCP stdio server (7 tools)
│   ├── audit.py            # Append-only audit log
│   ├── telemetry.py        # Usage tracking
│   ├── evolver.py          # Skill evolution engine
│   ├── cli.py              # Click CLI interface
│   ├── adapters/           # Agent runtime adapters
│   │   ├── base.py         # Abstract adapter
│   │   ├── codex_adapter.py
│   │   └── claude_adapter.py
│   └── bridge/             # Registry integrity
│       ├── wal_manager.py  # Write-ahead logging
│       ├── freeze_detector.py
│       └── maintenance.py
├── tests/                  # Test suites (200+ tests)
│   ├── unit/               # Unit tests
│   ├── mcp/                # MCP server tests
│   └── integration/        # Integration tests
└── .skillpool/             # Runtime data (created by init)
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests with coverage
pytest --cov=skillpool --cov-fail-under=85

# Lint
ruff check src/ tests/
ruff format --check src/ tests/

# Type check
mypy src/skillpool --ignore-missing-imports

# Security audit
pip-audit

# Build package
python -m build
```

## CI Pipeline

The project uses GitHub Actions with 4 jobs:

1. **lint** — Ruff check + format + MyPy (Python 3.12)
2. **test** — Pytest with coverage ≥85% (Python 3.11, 3.12 matrix)
3. **security** — pip-audit vulnerability scan
4. **build** — Package build verification (depends on lint+test+security)

## Quality Dimensions

Skills are scored across 12 dimensions:

| Dimension | Weight | Description |
|-----------|--------|-------------|
| completeness | 1.0 | Coverage of stated functionality |
| accuracy | 1.5 | Correctness of outputs |
| usability | 1.0 | Ease of integration and use |
| maintainability | 0.8 | Code quality and documentation |
| performance | 0.7 | Speed and resource efficiency |
| security | 1.2 | Vulnerability resistance |
| reliability | 1.0 | Consistency under varying conditions |
| adaptability | 0.6 | Flexibility across contexts |
| documentation | 0.8 | Quality of inline and external docs |
| testability | 0.7 | Ease of writing and running tests |
| interoperability | 0.5 | Compatibility with other systems |
| observability | 0.5 | Monitoring and debugging support |

## License

MIT
