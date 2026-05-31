# Contributing to SkillPool

Thank you for your interest in contributing to SkillPool! This document provides guidelines and instructions for contributing.

## Code of Conduct

Be respectful, constructive, and inclusive. We follow the [Contributor Covenant](https://www.contributor-covenant.org/) code of conduct.

## How to Contribute

### Reporting Bugs

1. Search existing issues to avoid duplicates
2. Open a new issue using the **Bug Report** template
3. Include: Python version, OS, steps to reproduce, expected vs actual behavior

### Suggesting Features

1. Open an issue using the **Feature Request** template
2. Describe the use case and expected benefit
3. Wait for maintainer feedback before implementing

### Submitting Pull Requests

1. **Fork** the repository
2. **Create a branch** from `main`: `git checkout -b feat/your-feature`
3. **Write code** following our style guidelines below
4. **Add tests** — all new features and bug fixes must have tests
5. **Run the full suite**: `make test`
6. **Commit** with conventional commits:
   - `feat: add skill dependency graph`
   - `fix: resolve search scoring edge case`
   - `docs: update API reference`
   - `refactor: simplify registry persistence`
7. **Open a PR** against `main` using the PR template
8. **Address review feedback** promptly

## Development Setup

```bash
# Clone and enter the project
git clone https://github.com/your-org/skillpool.git
cd skillpool

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env

# Run development server
make dev
```

## Code Style

- **Python 3.11+** — use modern syntax (type hints, match/case, etc.)
- **Line length**: 100 characters max
- **Formatting**: `ruff format` (Black-compatible)
- **Linting**: `ruff check`
- **Type checking**: `mypy --strict`
- **Import order**: stdlib → third-party → local (sorted)

## Testing

```bash
make test          # Run all tests
make test-cov      # Run with coverage report
make test-fast     # Skip slow/integration tests
```

- Unit tests go in `tests/unit/`
- Integration tests go in `tests/integration/`
- Test files mirror `src/` structure: `src/skillpool/foo.py` → `tests/unit/test_foo.py`
- Minimum coverage target: **80%**

## Project Structure

```
skillpool/
├── src/skillpool/       # Core library
│   ├── adapters/        # AI agent adapters (Claude, Codex)
│   ├── bridge/          # WAL, maintenance, freeze detection
│   ├── cli.py           # CLI entry point
│   └── ...
├── app/                 # FastAPI application
├── tests/               # Test suite
├── deploy/              # Deployment configs
└── docs/                # Documentation
```

## Release Process

1. Maintainers update `CHANGELOG.md`
2. Version bumped in `pyproject.toml` and `src/skillpool/__init__.py`
3. Tag created: `git tag v4.1.1`
4. GitHub Actions builds and publishes

## Questions?

Open a [Discussion](https://github.com/your-org/skillpool/discussions) or ask in issues.
