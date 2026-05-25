"""SkillPool test fixtures — shared across all test suites."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ── Path constants ──────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_SKILLS_DIR = FIXTURES_DIR / "sample_skills"
SAMPLE_REGISTRY = FIXTURES_DIR / "sample_registry.jsonl"
SAMPLE_CSDF = FIXTURES_DIR / "sample_csdf.yaml"


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def tmp_skillpool_dir(tmp_path: Path) -> Path:
    """Provide a temporary .skillpool directory with standard structure."""
    sp_dir = tmp_path / ".skillpool"
    sp_dir.mkdir()
    (sp_dir / "registry.jsonl").touch()
    (sp_dir / "gate.json").write_text('{"gates": {}}\n')
    (sp_dir / "materialization_state").mkdir()
    (sp_dir / "materialization_state" / "versions").mkdir()
    (sp_dir / "logs").mkdir()
    (sp_dir / "mcp_audit.jsonl").touch()
    (sp_dir / "emergency_overrides.json").write_text('{"overrides": {}}\n')
    return sp_dir


@pytest.fixture
def sample_skills_dir() -> Path:
    """Provide path to sample SKILL.md fixtures."""
    if not SAMPLE_SKILLS_DIR.exists():
        pytest.skip("Sample skills fixtures not yet created (Step 3)")
    return SAMPLE_SKILLS_DIR


@pytest.fixture
def populated_registry(tmp_skillpool_dir: Path) -> Path:
    """Provide a registry.jsonl with sample entries."""
    registry = tmp_skillpool_dir / "registry.jsonl"
    entries = [
        {
            "name": "test-skill-1",
            "version": "1.0.0",
            "status": "active",
            "quality_score": 0.85,
            "paradigm": "general",
            "csdf": {"name": "test-skill-1", "version": "1.0.0"},
        },
        {
            "name": "test-skill-2",
            "version": "2.1.0",
            "status": "active",
            "quality_score": 0.72,
            "paradigm": "general",
            "csdf": {"name": "test-skill-2", "version": "2.1.0"},
        },
    ]
    with open(registry, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return registry
