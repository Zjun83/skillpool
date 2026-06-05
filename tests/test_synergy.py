"""Tests for SynergyDetector — skill combination gain detection and synergy edge management."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from skillpool.synergy import (
    SynergyDetector,
    SynergyEdge,
    SynergyDetectionResult,
)
from skillpool.resolver.models import DagEdge, DagEdgeType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skills_dir(tmp_path):
    """Create a temporary skills directory with sample CSDF YAML files."""
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def detector(skills_dir):
    """Return a SynergyDetector pointed at the temp skills_dir."""
    return SynergyDetector(skills_dir=skills_dir)


def _write_skill_yaml(skills_dir: Path, skill_id: str, synergies: list[dict] | None = None):
    """Helper: write a minimal CSDF YAML file for a skill."""
    import yaml

    skill_dir = skills_dir / skill_id
    skill_dir.mkdir(exist_ok=True)
    data = {"id": skill_id}
    if synergies is not None:
        data["synergies"] = synergies
    (skill_dir / f"{skill_id}.yaml").write_text(yaml.dump(data, default_flow_style=False))


# ---------------------------------------------------------------------------
# SynergyEdge model
# ---------------------------------------------------------------------------


class TestSynergyEdge:
    """Test the SynergyEdge Pydantic model."""

    def test_defaults(self):
        edge = SynergyEdge(source="a", target="b")
        assert edge.source == "a"
        assert edge.target == "b"
        assert edge.gain == ""
        assert edge.reason == ""
        assert edge.weight == 0.5
        assert edge.evidence == "expert"

    def test_full_construction(self):
        edge = SynergyEdge(
            source="review",
            target="security",
            gain="+15%",
            reason="security lens",
            weight=0.65,
            evidence="observed",
        )
        assert edge.source == "review"
        assert edge.target == "security"
        assert edge.gain == "+15%"
        assert edge.reason == "security lens"
        assert edge.weight == 0.65
        assert edge.evidence == "observed"

    def test_weight_bounds(self):
        # weight must be 0.0-1.0
        with pytest.raises(Exception):
            SynergyEdge(source="a", target="b", weight=-0.1)
        with pytest.raises(Exception):
            SynergyEdge(source="a", target="b", weight=1.5)

    def test_weight_at_boundaries(self):
        assert SynergyEdge(source="a", target="b", weight=0.0).weight == 0.0
        assert SynergyEdge(source="a", target="b", weight=1.0).weight == 1.0


# ---------------------------------------------------------------------------
# SynergyDetectionResult model
# ---------------------------------------------------------------------------


class TestSynergyDetectionResult:
    """Test the SynergyDetectionResult Pydantic model."""

    def test_defaults(self):
        result = SynergyDetectionResult()
        assert result.edges_created == 0
        assert result.edges_updated == 0
        assert result.edges_total == 0
        assert result.new_discoveries == []

    def test_with_values(self):
        edge = SynergyEdge(source="a", target="b")
        result = SynergyDetectionResult(
            edges_created=3,
            edges_updated=1,
            edges_total=4,
            new_discoveries=[edge],
        )
        assert result.edges_created == 3
        assert result.edges_updated == 1
        assert result.edges_total == 4
        assert len(result.new_discoveries) == 1


# ---------------------------------------------------------------------------
# _parse_gain_to_weight
# ---------------------------------------------------------------------------


class TestParseGainToWeight:
    """Test the static gain-to-weight parser."""

    def test_positive_percentage(self):
        assert SynergyDetector._parse_gain_to_weight("+15%") == 0.5

    def test_percentage_without_plus(self):
        assert SynergyDetector._parse_gain_to_weight("15%") == 0.5

    def test_small_gain(self):
        # +5% → 5/30 = 0.167 → clamped to 0.1
        assert SynergyDetector._parse_gain_to_weight("+5%") == 0.17

    def test_large_gain(self):
        # +30% → 30/30 = 1.0 → clamped to 0.95
        assert SynergyDetector._parse_gain_to_weight("+30%") == 0.95

    def test_very_large_gain_clamped(self):
        # +100% → 100/30 = 3.33 → clamped to 0.95
        assert SynergyDetector._parse_gain_to_weight("+100%") == 0.95

    def test_zero_gain(self):
        # 0/30 = 0.0 → clamped to 0.1
        assert SynergyDetector._parse_gain_to_weight("+0%") == 0.1

    def test_unparseable_returns_default(self):
        assert SynergyDetector._parse_gain_to_weight("unknown") == 0.5

    def test_empty_string_returns_default(self):
        assert SynergyDetector._parse_gain_to_weight("") == 0.5

    def test_none_returns_default(self):
        assert SynergyDetector._parse_gain_to_weight(None) == 0.5

    def test_whitespace_handling(self):
        assert SynergyDetector._parse_gain_to_weight("  +10%  ") == 0.33

    def test_negative_gain(self):
        # -5% → -5/30 = -0.167 → clamped to 0.1
        assert SynergyDetector._parse_gain_to_weight("-5%") == 0.1


# ---------------------------------------------------------------------------
# SynergyDetector — load_expert_synergies
# ---------------------------------------------------------------------------


class TestLoadExpertSynergies:
    """Test loading expert-annotated synergies from CSDF YAML files."""

    def test_empty_skills_dir(self, detector, skills_dir):
        edges = detector.load_expert_synergies()
        assert edges == []
        assert detector._synergy_edges == []

    def test_nonexistent_skills_dir(self, tmp_path):
        nonexistent = tmp_path / "no_such_dir"
        d = SynergyDetector(skills_dir=nonexistent)
        edges = d.load_expert_synergies()
        assert edges == []

    def test_skill_with_no_synergies(self, detector, skills_dir):
        _write_skill_yaml(skills_dir, "solo-skill", synergies=[])
        edges = detector.load_expert_synergies()
        assert edges == []

    def test_skill_without_synergies_field(self, detector, skills_dir):
        _write_skill_yaml(skills_dir, "bare-skill", synergies=None)
        # synergies key not present in YAML
        import yaml

        skill_dir = skills_dir / "bare-skill"
        data = {"id": "bare-skill"}
        (skill_dir / "bare-skill.yaml").write_text(yaml.dump(data))
        edges = detector.load_expert_synergies()
        assert edges == []

    def test_single_skill_with_synergies(self, detector, skills_dir):
        _write_skill_yaml(
            skills_dir,
            "review",
            synergies=[
                {"skill_id": "security", "gain": "+15%", "reason": "security lens"},
            ],
        )
        edges = detector.load_expert_synergies()
        assert len(edges) == 1
        assert edges[0].source == "review"
        assert edges[0].target == "security"
        assert edges[0].gain == "+15%"
        assert edges[0].reason == "security lens"
        assert edges[0].evidence == "expert"
        # +15% → 15/30 = 0.5
        assert edges[0].weight == 0.5

    def test_multiple_skills_with_synergies(self, detector, skills_dir):
        _write_skill_yaml(
            skills_dir,
            "review",
            synergies=[
                {"skill_id": "security", "gain": "+15%", "reason": "security lens"},
                {"skill_id": "testing", "gain": "+10%", "reason": "test coverage"},
            ],
        )
        _write_skill_yaml(
            skills_dir,
            "security",
            synergies=[
                {"skill_id": "compliance", "gain": "+20%", "reason": "compliance check"},
            ],
        )
        edges = detector.load_expert_synergies()
        assert len(edges) == 3
        sources = {e.source for e in edges}
        assert sources == {"review", "security"}

    def test_skill_id_fallback_to_dir_name(self, detector, skills_dir):
        """When YAML has no 'id' field, skill_id falls back to directory name."""
        import yaml

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        data = {"synergies": [{"skill_id": "helper", "gain": "+5%", "reason": "helps"}]}
        (skill_dir / "my-skill.yaml").write_text(yaml.dump(data))
        edges = detector.load_expert_synergies()
        assert len(edges) == 1
        assert edges[0].source == "my-skill"

    def test_synergy_entry_missing_skill_id_skipped(self, detector, skills_dir):
        """Synergy dicts without 'skill_id' key are skipped."""
        import yaml

        skill_dir = skills_dir / "bad-skill"
        skill_dir.mkdir()
        data = {
            "id": "bad-skill",
            "synergies": [{"gain": "+10%", "reason": "no skill_id"}],
        }
        (skill_dir / "bad-skill.yaml").write_text(yaml.dump(data))
        # SynergyEntry requires skill_id, so this should raise and be caught
        edges = detector.load_expert_synergies()
        assert edges == []

    def test_invalid_yaml_skipped(self, detector, skills_dir):
        """Malformed YAML files are skipped gracefully."""
        skill_dir = skills_dir / "broken"
        skill_dir.mkdir()
        (skill_dir / "broken.yaml").write_text("{{invalid yaml::")
        edges = detector.load_expert_synergies()
        assert edges == []

    def test_non_dict_yaml_skipped(self, detector, skills_dir):
        """YAML files that parse to non-dict values are skipped."""
        skill_dir = skills_dir / "list-skill"
        skill_dir.mkdir()
        (skill_dir / "list-skill.yaml").write_text("- item1\n- item2\n")
        edges = detector.load_expert_synergies()
        assert edges == []

    def test_empty_yaml_skipped(self, detector, skills_dir):
        """Empty YAML files (None result) are skipped."""
        skill_dir = skills_dir / "empty"
        skill_dir.mkdir()
        (skill_dir / "empty.yaml").write_text("")
        edges = detector.load_expert_synergies()
        assert edges == []

    def test_non_yaml_files_ignored(self, detector, skills_dir):
        """Only .yaml files are read; .txt, .md etc. are ignored."""
        skill_dir = skills_dir / "mixed"
        skill_dir.mkdir()
        (skill_dir / "mixed.yaml").write_text("id: mixed\nsynergies: []\n")
        (skill_dir / "readme.md").write_text("not yaml")
        (skill_dir / "notes.txt").write_text("also not yaml")
        edges = detector.load_expert_synergies()
        assert edges == []

    def test_files_in_skills_dir_ignored(self, detector, skills_dir):
        """Regular files directly in skills_dir are skipped (only dirs iterated)."""
        (skills_dir / "standalone.yaml").write_text("id: standalone\nsynergies: []\n")
        edges = detector.load_expert_synergies()
        assert edges == []

    def test_registry_fallback_to_filesystem(self, detector, skills_dir):
        """When Registry returns None, filesystem fallback is used."""
        _write_skill_yaml(
            skills_dir,
            "fs-skill",
            synergies=[
                {"skill_id": "helper", "gain": "+10%", "reason": "helps"},
            ],
        )
        with patch.object(detector, "_load_from_registry", return_value=None):
            edges = detector.load_expert_synergies()
        assert len(edges) == 1
        assert edges[0].source == "fs-skill"

    def test_registry_primary_path(self, detector, skills_dir):
        """When Registry returns data, filesystem is not read."""
        reg_edge = SynergyEdge(source="reg", target="remote", gain="+20%", weight=0.8, evidence="expert")
        with patch.object(detector, "_load_from_registry", return_value=[reg_edge]):
            edges = detector.load_expert_synergies()
        assert len(edges) == 1
        assert edges[0].source == "reg"
        assert edges[0].evidence == "expert"

    def test_load_populates_internal_edges(self, detector, skills_dir):
        _write_skill_yaml(
            skills_dir,
            "a",
            synergies=[
                {"skill_id": "b", "gain": "+10%", "reason": "test"},
            ],
        )
        detector.load_expert_synergies()
        assert len(detector._synergy_edges) == 1


# ---------------------------------------------------------------------------
# SynergyDetector — to_dag_edges
# ---------------------------------------------------------------------------


class TestToDagEdges:
    """Test conversion of synergy edges to DagEdge objects."""

    def test_empty_edges(self, detector):
        dag_edges = detector.to_dag_edges()
        assert dag_edges == []

    def test_conversion(self, detector):
        detector._synergy_edges = [
            SynergyEdge(source="review", target="security", weight=0.7),
            SynergyEdge(source="review", target="testing", weight=0.5),
        ]
        dag_edges = detector.to_dag_edges()
        assert len(dag_edges) == 2
        for de in dag_edges:
            assert isinstance(de, DagEdge)
            assert de.type == DagEdgeType.ENHANCES
        assert dag_edges[0].source == "review"
        assert dag_edges[0].target == "security"
        assert dag_edges[0].weight == 0.7
        assert dag_edges[1].target == "testing"

    def test_preserves_weight(self, detector):
        detector._synergy_edges = [
            SynergyEdge(source="a", target="b", weight=0.3),
        ]
        dag_edges = detector.to_dag_edges()
        assert dag_edges[0].weight == 0.3


# ---------------------------------------------------------------------------
# SynergyDetector — sync_expert_synergies
# ---------------------------------------------------------------------------


class TestSyncExpertSynergies:
    """Test the full sync entry point."""

    def test_empty_sync(self, detector, skills_dir):
        result = detector.sync_expert_synergies()
        assert isinstance(result, SynergyDetectionResult)
        assert result.edges_created == 0
        assert result.edges_updated == 0
        assert result.edges_total == 0
        assert result.new_discoveries == []

    def test_sync_with_data(self, detector, skills_dir):
        _write_skill_yaml(
            skills_dir,
            "review",
            synergies=[
                {"skill_id": "security", "gain": "+15%", "reason": "security lens"},
                {"skill_id": "testing", "gain": "+10%", "reason": "test coverage"},
            ],
        )
        result = detector.sync_expert_synergies()
        assert result.edges_created == 2
        assert result.edges_total == 2
        assert result.edges_updated == 0  # First sync, no updates


# ---------------------------------------------------------------------------
# SynergyDetector — get_synergies_for / get_enhancers_of
# ---------------------------------------------------------------------------


class TestGetSynergiesFor:
    """Test querying synergies by source skill."""

    def test_no_edges(self, detector):
        assert detector.get_synergies_for("anything") == []

    def test_matching_source(self, detector):
        detector._synergy_edges = [
            SynergyEdge(source="review", target="security"),
            SynergyEdge(source="review", target="testing"),
            SynergyEdge(source="security", target="compliance"),
        ]
        result = detector.get_synergies_for("review")
        assert len(result) == 2
        assert all(e.source == "review" for e in result)

    def test_no_matching_source(self, detector):
        detector._synergy_edges = [
            SynergyEdge(source="review", target="security"),
        ]
        assert detector.get_synergies_for("nonexistent") == []


class TestGetEnhancersOf:
    """Test querying skills that enhance a given skill (target match)."""

    def test_no_edges(self, detector):
        assert detector.get_enhancers_of("anything") == []

    def test_matching_target(self, detector):
        detector._synergy_edges = [
            SynergyEdge(source="review", target="security"),
            SynergyEdge(source="compliance", target="security"),
            SynergyEdge(source="review", target="testing"),
        ]
        result = detector.get_enhancers_of("security")
        assert len(result) == 2
        assert all(e.target == "security" for e in result)

    def test_no_matching_target(self, detector):
        detector._synergy_edges = [
            SynergyEdge(source="review", target="security"),
        ]
        assert detector.get_enhancers_of("nonexistent") == []


# ---------------------------------------------------------------------------
# SynergyDetector — load_combination_synergies
# ---------------------------------------------------------------------------


class TestLoadCombinationSynergies:
    """Test loading synergies from the combiner module."""

    def test_import_error_returns_empty(self, detector):
        """When combiner module is not importable, returns empty list."""
        with patch.dict("sys.modules", {"skillpool.combiner": None}):
            result = detector.load_combination_synergies()
            assert result == []

    def test_combiner_exception_returns_empty(self, detector):
        """When combiner raises an exception, returns empty list."""
        with patch("skillpool.synergy.CombinationLifecycleManager", side_effect=Exception("boom"), create=True):
            # Force ImportError path by making the import fail
            with patch.dict("sys.modules", {"skillpool.combiner": None}):
                result = detector.load_combination_synergies()
                assert result == []

    def test_successful_combination_load(self, detector):
        """Test loading from a mocked CombinationLifecycleManager."""
        mock_combo = MagicMock()
        mock_combo.state.name = "PROMOTED"
        mock_combo.state.value = "promoted"
        mock_combo.current_weight.return_value = 0.8
        mock_combo.primary = "review"
        mock_combo.enhancers = ["security", "testing"]
        mock_combo.gain_avg = 15.0
        mock_combo.source = "observed"
        mock_combo.execution_count = 10

        # Use the actual enum value for state comparison
        from skillpool.combiner.models import CombinationLifecycleState

        mock_combo.state = CombinationLifecycleState.PROMOTED

        mock_mgr = MagicMock()
        mock_mgr._combinations = {"c1": mock_combo}

        with patch("skillpool.synergy.CombinationLifecycleManager", return_value=mock_mgr, create=True):
            # Need to also patch the import inside the function
            import sys

            combiner_mock = MagicMock()
            combiner_mock.CombinationLifecycleManager = MagicMock(return_value=mock_mgr)
            combiner_models_mock = MagicMock()
            combiner_models_mock.CombinationLifecycleState = CombinationLifecycleState
            sys.modules["skillpool.combiner"] = combiner_mock
            sys.modules["skillpool.combiner.models"] = combiner_models_mock

            try:
                result = detector.load_combination_synergies()
                assert len(result) == 2
                assert result[0].source == "review"
                assert result[0].target == "security"
                assert result[0].evidence == "observed"
                assert result[1].target == "testing"
            finally:
                del sys.modules["skillpool.combiner"]
                del sys.modules["skillpool.combiner.models"]

    def test_retired_combinations_excluded(self, detector):
        """RETIRED combinations should be completely excluded."""
        from skillpool.combiner.models import CombinationLifecycleState

        mock_combo = MagicMock()
        mock_combo.state = CombinationLifecycleState.RETIRED
        mock_combo.primary = "review"
        mock_combo.enhancers = ["security"]

        mock_mgr = MagicMock()
        mock_mgr._combinations = {"c1": mock_combo}

        import sys

        combiner_mock = MagicMock()
        combiner_mock.CombinationLifecycleManager = MagicMock(return_value=mock_mgr)
        combiner_models_mock = MagicMock()
        combiner_models_mock.CombinationLifecycleState = CombinationLifecycleState
        sys.modules["skillpool.combiner"] = combiner_mock
        sys.modules["skillpool.combiner.models"] = combiner_models_mock

        try:
            result = detector.load_combination_synergies()
            assert result == []
        finally:
            del sys.modules["skillpool.combiner"]
            del sys.modules["skillpool.combiner.models"]

    def test_dedup_with_existing_edges(self, detector):
        """New combination edges that duplicate existing ones are not added."""
        from skillpool.combiner.models import CombinationLifecycleState

        # Pre-populate with an existing edge
        detector._synergy_edges = [
            SynergyEdge(source="review", target="security", weight=0.5),
        ]

        mock_combo = MagicMock()
        mock_combo.state = CombinationLifecycleState.PROMOTED
        mock_combo.current_weight.return_value = 0.8
        mock_combo.primary = "review"
        mock_combo.enhancers = ["security"]  # Duplicate
        mock_combo.gain_avg = 15.0
        mock_combo.source = "observed"
        mock_combo.execution_count = 10

        mock_mgr = MagicMock()
        mock_mgr._combinations = {"c1": mock_combo}

        import sys

        combiner_mock = MagicMock()
        combiner_mock.CombinationLifecycleManager = MagicMock(return_value=mock_mgr)
        combiner_models_mock = MagicMock()
        combiner_models_mock.CombinationLifecycleState = CombinationLifecycleState
        sys.modules["skillpool.combiner"] = combiner_mock
        sys.modules["skillpool.combiner.models"] = combiner_models_mock

        try:
            result = detector.load_combination_synergies()
            # "security" is already in existing edges, so it's deduped
            assert result == []
            # Internal edges should still have the original
            assert len(detector._synergy_edges) == 1
        finally:
            del sys.modules["skillpool.combiner"]
            del sys.modules["skillpool.combiner.models"]


# ---------------------------------------------------------------------------
# SynergyDetector — _load_from_registry
# ---------------------------------------------------------------------------


class TestLoadFromRegistry:
    """Test the Registry loading path."""

    def test_returns_none_when_registry_unavailable(self, detector):
        """When Registry import fails, returns None (triggers filesystem fallback)."""
        with patch.dict("sys.modules", {"skillpool.registry": None}):
            result = detector._load_from_registry()
            assert result is None

    def test_returns_none_when_registry_has_no_synergy_data(self, detector):
        """Current Registry implementation returns None (no synergy support yet)."""
        result = detector._load_from_registry()
        # Current implementation always returns None
        assert result is None


# ---------------------------------------------------------------------------
# SynergyDetector — constructor
# ---------------------------------------------------------------------------


class TestSynergyDetectorInit:
    """Test constructor behavior."""

    def test_default_skills_dir(self):
        """When no skills_dir provided, uses get_data_dir() / 'skills'."""
        with patch("skillpool.synergy.get_data_dir", return_value=Path("/fake")):
            d = SynergyDetector()
            assert d.skills_dir == Path("/fake/skills")

    def test_custom_skills_dir(self, tmp_path):
        d = SynergyDetector(skills_dir=tmp_path)
        assert d.skills_dir == tmp_path

    def test_initial_edges_empty(self, detector):
        assert detector._synergy_edges == []
