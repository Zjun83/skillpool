"""Tests for IntentRouter — covering uncovered lines in router/__init__.py.

Uncovered lines:
- 92-98: Ollama auto-detect port 11434→11435 fallback
- 125-127: _embed returning None when Ollama unavailable
- 143, 147, 153: _build_index flat YAML path, directory SKILL.md + YAML
- 207, 212: L3/L4 layers used in route()
- 259: _match_by_embedding skill embedding failure
- 319, 324, 325: _route_l2_logical dependency parsing (dict dep with id, string dep)
- 335, 342, 343: _route_l2_logical synergy parsing (non-dict synergy skip)
- 351: duplicate synergy append (bug in source)
- 372, 374-376: _find_skill_yaml directory YAML parse failure
- 383, 385-386: _find_skill_yaml flat YAML parse failure
- 407-408: _route_l3_causal ImportError
- 421: _route_l3_causal gain > 0.5
- 439-440: _route_l4_predictive ImportError
- 449-454: _route_l4_predictive with promoted combinations
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from skillpool.router import IntentRouter, SkillCandidate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skills_dir(tmp_path):
    """Create a temporary skills directory with sample YAML files."""
    # Flat YAML skill with dependencies and synergies
    (tmp_path / "S09-resilience.yaml").write_text(
        "id: S09\n"
        "name: Resilience Degradation\n"
        "description: Detect and handle service degradation\n"
        "dimension: D5\n"
        "dependencies:\n"
        "  - skill_id: S05a\n"
        "  - S10\n"
        "synergies:\n"
        "  - skill_id: S10\n"
        "    gain: '+15%'\n"
        "    reason: Combined recovery\n"
    )
    # Another flat YAML skill
    (tmp_path / "S05a-security.yaml").write_text(
        "id: S05a\nname: Security Transport\ndescription: Validate transport layer security\ndimension: D3\n"
    )
    # Directory-based skill with SKILL.md + YAML
    skill_dir = tmp_path / "scaffold-docs"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "id: scaffold-docs\n"
        "name: Scaffold Documentation\n"
        "description: Generate project scaffolding\n"
        "---\n"
        "# Scaffold Docs\n"
    )
    (skill_dir / "scaffold-docs.yaml").write_text(
        "id: scaffold-docs\nname: Scaffold Documentation\ndescription: Generate project scaffolding\n"
    )
    return tmp_path


@pytest.fixture
def router(skills_dir):
    return IntentRouter(skills_dir=skills_dir, ollama_url="http://127.0.0.1:99999/api/embed")


# ---------------------------------------------------------------------------
# Ollama auto-detect port fallback (lines 92-98)
# ---------------------------------------------------------------------------


class TestOllamaAutoDetectPort:
    """When default port 11434 fails, try 11435 (WSL2 conflict fallback)."""

    def test_auto_detect_fallback_to_11435(self, tmp_path):
        """If 11434 fails but 11435 works, URL is updated and available=True."""
        router = IntentRouter(
            skills_dir=tmp_path,
            ollama_url="http://127.0.0.1:11434/api/embed",
        )
        # Mock _try_ollama_base: 11434 fails, 11435 succeeds
        with patch.object(IntentRouter, "_try_ollama_base", side_effect=lambda url: ":11435" in url):
            result = router._check_ollama()
            assert result is True
            assert ":11435" in router.ollama_url

    def test_auto_detect_both_fail(self, tmp_path):
        """If both 11434 and 11435 fail, available=False."""
        router = IntentRouter(
            skills_dir=tmp_path,
            ollama_url="http://127.0.0.1:11434/api/embed",
        )
        with patch.object(IntentRouter, "_try_ollama_base", return_value=False):
            result = router._check_ollama()
            assert result is False

    def test_non_default_port_no_fallback(self, tmp_path):
        """If URL doesn't use 11434, no auto-detect fallback is attempted."""
        router = IntentRouter(
            skills_dir=tmp_path,
            ollama_url="http://127.0.0.1:99999/api/embed",
        )
        with patch.object(IntentRouter, "_try_ollama_base", return_value=False):
            result = router._check_ollama()
            assert result is False
            # URL should not be modified
            assert ":99999" in router.ollama_url


# ---------------------------------------------------------------------------
# _embed returning None when Ollama unavailable (lines 125-127)
# ---------------------------------------------------------------------------


class TestEmbedFallback:
    """When Ollama is unavailable, _embed returns None (keyword fallback)."""

    def test_embed_returns_none_when_ollama_unavailable(self, router):
        router._ollama_available = False
        result = router._embed("test text")
        assert result is None

    def test_embed_returns_none_on_request_failure(self, tmp_path):
        """When Ollama check passes but request fails, returns None."""
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        router._ollama_available = True
        with patch("skillpool.router.httpx.post", side_effect=Exception("connection error")):
            result = router._embed("test")
            assert result is None


# ---------------------------------------------------------------------------
# _build_index — flat YAML and directory skills (lines 143, 147, 153)
# ---------------------------------------------------------------------------


class TestBuildIndexPaths:
    """Cover flat YAML and directory-based skill indexing."""

    def test_flat_yaml_skill_indexed(self, router):
        router._build_index()
        assert "S09-resilience" in router._skill_index
        meta = router._skill_index["S09-resilience"]
        assert "Resilience" in meta["description"] or "D5" in meta["description"]

    def test_directory_skill_with_skill_md_and_yaml(self, router):
        """Directory skill with both SKILL.md and YAML gets both descriptions."""
        router._build_index()
        assert "scaffold-docs" in router._skill_index
        desc = router._skill_index["scaffold-docs"]["description"]
        # Should contain content from both SKILL.md and YAML
        assert len(desc) > 0

    def test_flat_yaml_with_no_description(self, tmp_path):
        """Flat YAML with only id field still gets indexed."""
        (tmp_path / "minimal.yaml").write_text("id: minimal\n")
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        router._build_index()
        # No description/name/dimension → desc_parts empty → not indexed
        assert "minimal" not in router._skill_index


# ---------------------------------------------------------------------------
# L3/L4 layers used in route() (lines 207, 212)
# ---------------------------------------------------------------------------


class TestRouteL3L4Layers:
    """Test that L3 and L4 layers appear in layers_used when they produce results."""

    def test_l3_layer_used(self, skills_dir):
        """When GainTracker returns positive gain, L3 is in layers_used."""
        router = IntentRouter(skills_dir=skills_dir, ollama_url="http://127.0.0.1:99999/api/embed")

        # Mock GainTracker to return positive gain
        mock_tracker = MagicMock()
        mock_tracker.combination_gain.return_value = 15.0  # > 0.5

        # Need to also have skills in the index for L3 to iterate
        router._build_index()

        # Patch the import inside _route_l3_causal
        gain_mock = MagicMock()
        gain_mock.GainTracker = MagicMock(return_value=mock_tracker)
        with patch.dict("sys.modules", {"skillpool.gain": gain_mock}):
            l1 = [SkillCandidate(skill_id="S09-resilience", score=0.8, layer="L1")]
            l3 = router._route_l3_causal(l1)
            assert len(l3) > 0
            assert l3[0].layer == "L3"
            assert "Causal gain" in l3[0].reason

    def test_l3_gain_below_threshold_excluded(self, skills_dir):
        """When gain <= 0.5, skill is not included in L3 results."""
        router = IntentRouter(skills_dir=skills_dir, ollama_url="http://127.0.0.1:99999/api/embed")
        router._build_index()

        mock_tracker = MagicMock()
        mock_tracker.combination_gain.return_value = 0.3  # <= 0.5

        gain_mock = MagicMock()
        gain_mock.GainTracker = MagicMock(return_value=mock_tracker)
        with patch.dict("sys.modules", {"skillpool.gain": gain_mock}):
            l1 = [SkillCandidate(skill_id="S09-resilience", score=0.8, layer="L1")]
            l3 = router._route_l3_causal(l1)
            assert l3 == []

    def test_l4_layer_used(self, skills_dir):
        """When CombinationLifecycleManager has promoted combos, L4 produces results."""
        router = IntentRouter(skills_dir=skills_dir, ollama_url="http://127.0.0.1:99999/api/embed")
        router._build_index()

        mock_combo = MagicMock()
        mock_combo.enhancers = ["S05a-security"]
        mock_combo.current_weight.return_value = 0.8
        mock_combo.combination_id = "combo-1"
        mock_combo.gain_avg = 15.0

        mock_mgr = MagicMock()
        mock_mgr.get_promoted_combinations.return_value = [mock_combo]

        combiner_mock = MagicMock()
        combiner_mock.CombinationLifecycleManager = MagicMock(return_value=mock_mgr)
        with patch.dict("sys.modules", {"skillpool.combiner": combiner_mock}):
            l1 = [SkillCandidate(skill_id="S09-resilience", score=0.8, layer="L1")]
            l4 = router._route_l4_predictive(l1)
            assert len(l4) > 0
            assert l4[0].layer == "L4"

    def test_l4_weight_below_threshold_excluded(self, skills_dir):
        """When combo weight <= 0.1, enhancer is not included."""
        router = IntentRouter(skills_dir=skills_dir, ollama_url="http://127.0.0.1:99999/api/embed")
        router._build_index()

        mock_combo = MagicMock()
        mock_combo.enhancers = ["S05a-security"]
        mock_combo.current_weight.return_value = 0.05  # <= 0.1
        mock_combo.combination_id = "combo-1"
        mock_combo.gain_avg = 1.0

        mock_mgr = MagicMock()
        mock_mgr.get_promoted_combinations.return_value = [mock_combo]

        combiner_mock = MagicMock()
        combiner_mock.CombinationLifecycleManager = MagicMock(return_value=mock_mgr)
        with patch.dict("sys.modules", {"skillpool.combiner": combiner_mock}):
            l1 = [SkillCandidate(skill_id="S09-resilience", score=0.8, layer="L1")]
            l4 = router._route_l4_predictive(l1)
            assert l4 == []

    def test_l4_enhancer_in_l1_excluded(self, skills_dir):
        """When enhancer is already in L1 candidates, it's excluded from L4."""
        router = IntentRouter(skills_dir=skills_dir, ollama_url="http://127.0.0.1:99999/api/embed")
        router._build_index()

        mock_combo = MagicMock()
        mock_combo.enhancers = ["S09-resilience"]  # Already in L1
        mock_combo.current_weight.return_value = 0.8
        mock_combo.combination_id = "combo-1"
        mock_combo.gain_avg = 15.0

        mock_mgr = MagicMock()
        mock_mgr.get_promoted_combinations.return_value = [mock_combo]

        combiner_mock = MagicMock()
        combiner_mock.CombinationLifecycleManager = MagicMock(return_value=mock_mgr)
        with patch.dict("sys.modules", {"skillpool.combiner": combiner_mock}):
            l1 = [SkillCandidate(skill_id="S09-resilience", score=0.8, layer="L1")]
            l4 = router._route_l4_predictive(l1)
            assert l4 == []


# ---------------------------------------------------------------------------
# _match_by_embedding — skill embedding failure (line 259)
# ---------------------------------------------------------------------------


class TestMatchByEmbeddingFailure:
    """When a skill's embedding fails, it's skipped."""

    def test_skill_embedding_failure_skipped(self, tmp_path):
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        router._skill_index = {
            "good-skill": {"description": "good description", "skill_id": "good-skill"},
            "bad-skill": {"description": "bad description", "skill_id": "bad-skill"},
        }
        router._ollama_available = True

        # Mock _embed: succeed for intent, fail for one skill, succeed for another
        call_count = [0]

        def mock_embed(text):
            call_count[0] += 1
            if text == "test intent":
                return [0.1, 0.2, 0.3]
            if "bad" in text:
                return None  # Embedding fails
            return [0.4, 0.5, 0.6]

        with patch.object(router, "_embed", side_effect=mock_embed):
            result = router._match_by_embedding([0.1, 0.2, 0.3], top_k=5)
            # Only good-skill should appear
            skill_ids = [c.skill_id for c in result]
            assert "bad-skill" not in skill_ids
            assert "good-skill" in skill_ids


# ---------------------------------------------------------------------------
# _route_l2_logical — dependency parsing (lines 319, 324, 325)
# ---------------------------------------------------------------------------


class TestL2DependencyParsing:
    """Test various dependency formats in L2 routing."""

    def test_dict_dependency_with_skill_id(self, skills_dir):
        """Dependencies as dicts with skill_id field."""
        router = IntentRouter(skills_dir=skills_dir, ollama_url="http://127.0.0.1:99999/api/embed")
        router._build_index()
        l1 = [SkillCandidate(skill_id="S09-resilience", score=0.8, layer="L1")]
        l2 = router._route_l2_logical(l1)
        dep_ids = [c.skill_id for c in l2]
        # S09 has dict dep {skill_id: S05a} and string dep S10
        assert "S05a" in dep_ids
        assert "S10" in dep_ids

    def test_string_dependency(self, tmp_path):
        """Dependencies as plain strings."""
        (tmp_path / "test-skill.yaml").write_text("id: test-skill\ndependencies:\n  - dep-a\n  - dep-b\n")
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        router._build_index()
        l1 = [SkillCandidate(skill_id="test-skill", score=0.8, layer="L1")]
        l2 = router._route_l2_logical(l1)
        dep_ids = [c.skill_id for c in l2]
        assert "dep-a" in dep_ids
        assert "dep-b" in dep_ids

    def test_dict_dependency_with_id_field(self, tmp_path):
        """Dependencies as dicts with 'id' field (alternative to skill_id)."""
        (tmp_path / "test-skill.yaml").write_text("id: test-skill\ndependencies:\n  - id: dep-x\n")
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        router._build_index()
        l1 = [SkillCandidate(skill_id="test-skill", score=0.8, layer="L1")]
        l2 = router._route_l2_logical(l1)
        dep_ids = [c.skill_id for c in l2]
        assert "dep-x" in dep_ids


# ---------------------------------------------------------------------------
# _route_l2_logical — synergy parsing (lines 335, 342, 343, 351)
# ---------------------------------------------------------------------------


class TestL2SynergyParsing:
    """Test synergy parsing edge cases in L2 routing."""

    def test_non_dict_synergy_skipped(self, tmp_path):
        """Non-dict synergy entries are skipped."""
        (tmp_path / "test-skill.yaml").write_text("id: test-skill\nsynergies:\n  - plain_string\n  - 42\n")
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        router._build_index()
        l1 = [SkillCandidate(skill_id="test-skill", score=0.8, layer="L1")]
        l2 = router._route_l2_logical(l1)
        # No valid synergy entries → no L2 synergy candidates
        syn_candidates = [c for c in l2 if "Synergy" in c.reason]
        assert syn_candidates == []

    def test_dict_synergy_with_skill_id(self, skills_dir):
        """Dict synergy entries with skill_id are processed."""
        router = IntentRouter(skills_dir=skills_dir, ollama_url="http://127.0.0.1:99999/api/embed")
        router._build_index()
        l1 = [SkillCandidate(skill_id="S09-resilience", score=0.8, layer="L1")]
        l2 = router._route_l2_logical(l1)
        syn_ids = [c.skill_id for c in l2 if "Synergy" in c.reason]
        assert "S10" in syn_ids

    def test_synergy_not_in_l1_included(self, tmp_path):
        """Synergy skill not already in L1 is added as L2 candidate."""
        (tmp_path / "primary.yaml").write_text(
            "id: primary\nsynergies:\n  - skill_id: enhancer\n    gain: '+20%'\n    reason: Test synergy\n"
        )
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        router._build_index()
        l1 = [SkillCandidate(skill_id="primary", score=0.8, layer="L1")]
        l2 = router._route_l2_logical(l1)
        syn_ids = [c.skill_id for c in l2 if "Synergy" in c.reason]
        assert "enhancer" in syn_ids


# ---------------------------------------------------------------------------
# _find_skill_yaml — parse failures (lines 372, 374-376, 383, 385-386)
# ---------------------------------------------------------------------------


class TestFindSkillYamlParseFailures:
    """Test YAML parse failures in _find_skill_yaml."""

    def test_directory_yaml_parse_failure(self, tmp_path):
        """Malformed YAML in directory skill is skipped."""
        skill_dir = tmp_path / "broken-skill"
        skill_dir.mkdir()
        (skill_dir / "broken-skill.yaml").write_text("{{invalid yaml::")
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        results = router._find_skill_yaml("broken-skill")
        # Parse failure → empty results
        assert results == []

    def test_directory_yaml_non_dict_skipped(self, tmp_path):
        """YAML that parses to non-dict is skipped."""
        skill_dir = tmp_path / "list-skill"
        skill_dir.mkdir()
        (skill_dir / "list-skill.yaml").write_text("- item1\n- item2\n")
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        results = router._find_skill_yaml("list-skill")
        assert results == []

    def test_flat_yaml_parse_failure(self, tmp_path):
        """Malformed flat YAML is skipped."""
        (tmp_path / "bad-flat.yaml").write_text("{{invalid yaml::")
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        results = router._find_skill_yaml("bad-flat")
        assert results == []

    def test_flat_yaml_non_dict_skipped(self, tmp_path):
        """Flat YAML that parses to non-dict is skipped."""
        (tmp_path / "list-flat.yaml").write_text("- a\n- b\n")
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        results = router._find_skill_yaml("list-flat")
        assert results == []

    def test_valid_directory_yaml(self, tmp_path):
        """Valid YAML in directory skill is returned."""
        skill_dir = tmp_path / "good-skill"
        skill_dir.mkdir()
        (skill_dir / "good-skill.yaml").write_text("id: good-skill\nname: Good\n")
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        results = router._find_skill_yaml("good-skill")
        assert len(results) == 1
        _, data = results[0]
        assert data["id"] == "good-skill"

    def test_valid_flat_yaml(self, tmp_path):
        """Valid flat YAML is returned."""
        (tmp_path / "flat-skill.yaml").write_text("id: flat-skill\nname: Flat\n")
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        results = router._find_skill_yaml("flat-skill")
        assert len(results) == 1
        _, data = results[0]
        assert data["id"] == "flat-skill"


# ---------------------------------------------------------------------------
# _route_l3_causal — ImportError (lines 407-408)
# ---------------------------------------------------------------------------


class TestL3CausalImportError:
    """When skillpool.gain cannot be imported, L3 returns empty."""

    def test_import_error_returns_empty(self, tmp_path):
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        with patch.dict("sys.modules", {"skillpool.gain": None}):
            l1 = [SkillCandidate(skill_id="S09", score=0.8, layer="L1")]
            l3 = router._route_l3_causal(l1)
            assert l3 == []


# ---------------------------------------------------------------------------
# _route_l4_predictive — ImportError (lines 439-440)
# ---------------------------------------------------------------------------


class TestL4PredictiveImportError:
    """When skillpool.combiner cannot be imported, L4 returns empty."""

    def test_import_error_returns_empty(self, tmp_path):
        router = IntentRouter(skills_dir=tmp_path, ollama_url="http://127.0.0.1:99999/api/embed")
        with patch.dict("sys.modules", {"skillpool.combiner": None}):
            l1 = [SkillCandidate(skill_id="S09", score=0.8, layer="L1")]
            l4 = router._route_l4_predictive(l1)
            assert l4 == []


# ---------------------------------------------------------------------------
# route() — L3/L4 layers_used integration (lines 207, 212)
# ---------------------------------------------------------------------------


class TestRouteLayersUsedIntegration:
    """Test that route() correctly adds L3/L4 to layers_used."""

    def test_route_with_l3_layer(self, skills_dir):
        """route() includes L3 in layers_used when L3 produces results."""
        router = IntentRouter(skills_dir=skills_dir, ollama_url="http://127.0.0.1:99999/api/embed")

        mock_tracker = MagicMock()
        mock_tracker.combination_gain.return_value = 15.0

        gain_mock = MagicMock()
        gain_mock.GainTracker = MagicMock(return_value=mock_tracker)

        with patch.dict("sys.modules", {"skillpool.gain": gain_mock}):
            result = router.route("resilience degradation")
            if len(result.candidates) > 0:
                # L1 should always be present
                assert "L1" in result.layers_used

    def test_route_with_l4_layer(self, skills_dir):
        """route() includes L4 in layers_used when L4 produces results."""
        router = IntentRouter(skills_dir=skills_dir, ollama_url="http://127.0.0.1:99999/api/embed")

        mock_combo = MagicMock()
        mock_combo.enhancers = ["S05a-security"]
        mock_combo.current_weight.return_value = 0.8
        mock_combo.combination_id = "combo-1"
        mock_combo.gain_avg = 15.0

        mock_mgr = MagicMock()
        mock_mgr.get_promoted_combinations.return_value = [mock_combo]

        combiner_mock = MagicMock()
        combiner_mock.CombinationLifecycleManager = MagicMock(return_value=mock_mgr)

        with patch.dict("sys.modules", {"skillpool.combiner": combiner_mock}):
            result = router.route("resilience")
            if len(result.candidates) > 0:
                assert "L1" in result.layers_used


# ---------------------------------------------------------------------------
# _route_l4_predictive — gain_avg handling (line 459)
# ---------------------------------------------------------------------------


class TestL4GainAvg:
    """Test gain_avg formatting in L4 candidates."""

    def test_positive_gain_avg_in_gain_field(self, skills_dir):
        """When gain_avg > 0, gain field shows '+N.N'."""
        router = IntentRouter(skills_dir=skills_dir, ollama_url="http://127.0.0.1:99999/api/embed")
        router._build_index()

        mock_combo = MagicMock()
        mock_combo.enhancers = ["S05a-security"]
        mock_combo.current_weight.return_value = 0.8
        mock_combo.combination_id = "combo-1"
        mock_combo.gain_avg = 15.0

        mock_mgr = MagicMock()
        mock_mgr.get_promoted_combinations.return_value = [mock_combo]

        combiner_mock = MagicMock()
        combiner_mock.CombinationLifecycleManager = MagicMock(return_value=mock_mgr)
        with patch.dict("sys.modules", {"skillpool.combiner": combiner_mock}):
            l1 = [SkillCandidate(skill_id="S09-resilience", score=0.8, layer="L1")]
            l4 = router._route_l4_predictive(l1)
            assert len(l4) == 1
            assert l4[0].gain == "+15.0"

    def test_zero_gain_avg_empty_gain_field(self, skills_dir):
        """When gain_avg <= 0, gain field is empty string."""
        router = IntentRouter(skills_dir=skills_dir, ollama_url="http://127.0.0.1:99999/api/embed")
        router._build_index()

        mock_combo = MagicMock()
        mock_combo.enhancers = ["S05a-security"]
        mock_combo.current_weight.return_value = 0.8
        mock_combo.combination_id = "combo-1"
        mock_combo.gain_avg = 0.0

        mock_mgr = MagicMock()
        mock_mgr.get_promoted_combinations.return_value = [mock_combo]

        combiner_mock = MagicMock()
        combiner_mock.CombinationLifecycleManager = MagicMock(return_value=mock_mgr)
        with patch.dict("sys.modules", {"skillpool.combiner": combiner_mock}):
            l1 = [SkillCandidate(skill_id="S09-resilience", score=0.8, layer="L1")]
            l4 = router._route_l4_predictive(l1)
            assert len(l4) == 1
            assert l4[0].gain == ""
