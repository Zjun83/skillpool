"""Pytest configuration for skillpool tests."""

import sys
from pathlib import Path

import pytest

# Add src directory to Python path
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


def _create_test_skills(skills_dir: Path) -> Path:
    """Create minimal skill data in a directory and return it."""
    skills_dir.mkdir(exist_ok=True)

    # Create minimal S09 CSDF YAML (used by many test_mcp_server tests)
    (skills_dir / "S09-resilience-degradation.yaml").write_text(
        "id: S09\nname: Resilience & Degradation\nversion: 9.0.0\n"
        "dimension: D5\nweight: 0.111\ndescription: Test skill\n"
        "checklist:\n  - id: S09-C01\n    description: Circuit breaker\n    severity: critical\n"
    )

    # Create minimal multi-dim-review directory (used by skill_rules, skill_definition)
    review_dir = skills_dir / "multi-dim-review"
    review_dir.mkdir(exist_ok=True)
    (review_dir / "SKILL.md").write_text(
        "---\ndescription: Multi-dimension review skill\nversion: 9.0.0\n---\n# Multi-Dim Review\n"
    )
    (review_dir / "RULES.md").write_text("# Review Rules\n")

    # Create minimal skill_graph.yaml
    (skills_dir / "skill_graph.yaml").write_text(
        "graph:\n  name: test\n  total_skills: 1\n  orchestrator: S00\n"
        "  layers:\n    baseline:\n      skills: ['S09']\n"
    )

    return skills_dir
