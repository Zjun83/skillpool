"""Pytest configuration for skillpool tests."""

import sys
from pathlib import Path

# Add src directory to Python path
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


def _create_test_skills(skills_dir: Path) -> Path:
    """Create minimal skill data in a directory and return it."""
    skills_dir.mkdir(exist_ok=True)

    # Create minimal S00 orchestrator YAML (referenced by skill_graph and protocol tests)
    (skills_dir / "S00-orchestrator.yaml").write_text(
        "id: S00\nname: Orchestrator\nversion: 9.0.0\n"
        "dimension: ALL\nweight: null\ndescription: Master orchestrator\n"
        "checklist: []\n"
    )

    # Create minimal S09 CSDF YAML (used by many test_mcp_server tests)
    (skills_dir / "S09-resilience-degradation.yaml").write_text(
        "id: S09\nname: Resilience & Degradation\nversion: 9.0.0\n"
        "dimension: D5\nweight: 0.111\ndescription: Test skill\n"
        "checklist:\n  - id: S09-C01\n    description: Circuit breaker\n    severity: critical\n"
    )

    # Create minimal S05a and S13a (referenced by protocol boundary tests)
    (skills_dir / "S05a-security-transport.yaml").write_text(
        "id: S05a\nname: Security Transport\nversion: 9.0.0\n"
        "dimension: D3\nweight: 0.148\ndescription: Transport security\nchecklist: []\n"
    )
    (skills_dir / "S13a-testability-unit.yaml").write_text(
        "id: S13a\nname: Testability Unit\nversion: 9.0.0\n"
        "dimension: D7\nweight: 0.120\ndescription: Unit testability\nchecklist: []\n"
    )

    # Create minimal multi-dim-review directory (used by skill_rules, skill_definition)
    review_dir = skills_dir / "multi-dim-review"
    review_dir.mkdir(exist_ok=True)
    (review_dir / "SKILL.md").write_text(
        "---\ndescription: Multi-dimension review skill\nversion: 9.0.0\n---\n# Multi-Dim Review\n"
    )
    (review_dir / "RULES.md").write_text("# Review Rules\n\nD3 安全合规性 VETO: D3<7.0 → 阻断\n")

    # Create minimal scaffold-docs directory (used by e2e/protocol tests)
    scaffold_dir = skills_dir / "scaffold-docs"
    scaffold_dir.mkdir(exist_ok=True)
    (scaffold_dir / "SKILL.md").write_text(
        "---\ndescription: Documentation scaffolding skill\nversion: 1.0.0\n---\n# Scaffold Docs\nGenerate documentation structure and templates for projects.\n"
    )

    # Create minimal skill_graph.yaml
    (skills_dir / "skill_graph.yaml").write_text(
        "graph:\n  name: test\n  total_skills: 1\n  orchestrator: S00\n"
        "  layers:\n    baseline:\n      skills: ['S09']\n"
    )

    return skills_dir
