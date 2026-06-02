"""Tests for IntentRouter — intent-to-skill routing with L1-L4 layers."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from skillpool.router import IntentRouter, SkillCandidate, RoutingResult


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def skills_dir(tmp_path):
    """Create a temporary skills directory with sample YAML files."""
    # Flat YAML skill
    (tmp_path / "S09-resilience-degradation.yaml").write_text(
        "id: S09\n"
        "name: Resilience Degradation\n"
        "description: Detect and handle service degradation with graceful fallbacks\n"
        "dimension: D5\n"
        "version: 1.0.0\n"
        "dependencies:\n"
        "  - skill_id: S05a\n"
        "synergies:\n"
        "  - skill_id: S10\n"
        "    gain: '+15%'\n"
        "    reason: Combined recovery\n"
    )
    # Another flat YAML skill
    (tmp_path / "S05a-security-transport.yaml").write_text(
        "id: S05a\n"
        "name: Security Transport\n"
        "description: Validate transport layer security and encryption standards\n"
        "dimension: D3\n"
        "version: 1.0.0\n"
    )
    # Directory-based skill
    skill_dir = tmp_path / "scaffold-docs"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "id: scaffold-docs\n"
        "name: Scaffold Documentation\n"
        "description: Generate project scaffolding and documentation templates\n"
        "---\n"
        "# Scaffold Docs\n"
    )
    return tmp_path


@pytest.fixture
def router(skills_dir):
    """IntentRouter pointed at the temp skills directory."""
    return IntentRouter(skills_dir=skills_dir, ollama_url="http://127.0.0.1:99999/api/embed")


# ============================================================
# SkillCandidate & RoutingResult Models
# ============================================================

class TestSkillCandidateModel:
    def test_valid_candidate(self):
        c = SkillCandidate(skill_id="S09", score=0.8, layer="L1")
        assert c.skill_id == "S09"
        assert c.score == 0.8
        assert c.reason == ""
        assert c.gain == ""

    def test_candidate_with_gain(self):
        c = SkillCandidate(skill_id="S10", score=0.6, layer="L2", gain="+15%")
        assert c.gain == "+15%"

    def test_score_bounds(self):
        c = SkillCandidate(skill_id="S", score=0.0, layer="L1")
        assert c.score == 0.0
        c = SkillCandidate(skill_id="S", score=1.0, layer="L1")
        assert c.score == 1.0

    def test_invalid_score_raises(self):
        with pytest.raises(Exception):
            SkillCandidate(skill_id="S", score=1.5, layer="L1")


class TestRoutingResultModel:
    def test_default_result(self):
        r = RoutingResult(intent="test")
        assert r.intent == "test"
        assert r.candidates == []
        assert r.primary is None
        assert r.enhancers == []
        assert r.layers_used == []

    def test_result_with_candidates(self):
        c1 = SkillCandidate(skill_id="S09", score=0.9, layer="L1")
        c2 = SkillCandidate(skill_id="S05a", score=0.5, layer="L1")
        r = RoutingResult(intent="review", candidates=[c1, c2], primary=c1, enhancers=[c2])
        assert r.primary.skill_id == "S09"
        assert len(r.enhancers) == 1


# ============================================================
# Index Building
# ============================================================

class TestBuildIndex:
    def test_build_index_discovers_flat_yaml(self, router):
        router._build_index()
        assert "S09-resilience-degradation" in router._skill_index

    def test_build_index_discovers_directory_skill(self, router):
        router._build_index()
        assert "scaffold-docs" in router._skill_index

    def test_build_index_idempotent(self, router):
        router._build_index()
        first_count = len(router._skill_index)
        router._build_index()  # Should not rebuild
        assert len(router._skill_index) == first_count

    def test_build_index_empty_dir(self, tmp_path):
        empty_dir = tmp_path / "empty_skills"
        empty_dir.mkdir()
        r = IntentRouter(skills_dir=empty_dir, ollama_url="http://127.0.0.1:99999/api/embed")
        r._build_index()
        assert r._skill_index == {}

    def test_build_index_nonexistent_dir(self, tmp_path):
        r = IntentRouter(skills_dir=tmp_path / "no_such_dir", ollama_url="http://127.0.0.1:99999/api/embed")
        r._build_index()
        assert r._skill_index == {}


# ============================================================
# YAML Metadata Extraction
# ============================================================

class TestExtractYamlMetadata:
    def test_extract_from_valid_yaml(self, tmp_path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(
            "name: My Skill\n"
            "description: A test skill\n"
            "dimension: D5\n"
        )
        parts = IntentRouter._extract_yaml_metadata(yaml_file)
        assert any("My Skill" in p for p in parts)
        assert any("dimension:D5" in p for p in parts)

    def test_extract_from_malformed_yaml(self, tmp_path):
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text(": invalid: yaml: {{{")
        parts = IntentRouter._extract_yaml_metadata(yaml_file)
        assert isinstance(parts, list)

    def test_extract_from_empty_yaml(self, tmp_path):
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")
        parts = IntentRouter._extract_yaml_metadata(yaml_file)
        assert parts == []


# ============================================================
# Keyword Matching (L1 fallback)
# ============================================================

class TestKeywordMatching:
    def test_keyword_match_with_overlap(self, router):
        router._build_index()
        candidates = router._match_by_keyword("resilience degradation fallback", top_k=5)
        # Should find S09 based on keyword overlap
        assert len(candidates) > 0
        assert any("S09" in c.skill_id for c in candidates)

    def test_keyword_match_skill_id_in_intent(self, router):
        router._build_index()
        candidates = router._match_by_keyword("I need S09-resilience-degradation for my project", top_k=5)
        # Skill ID appearing in intent should boost score
        s09_candidates = [c for c in candidates if "S09" in c.skill_id]
        assert len(s09_candidates) > 0
        assert s09_candidates[0].score >= 0.7

    def test_keyword_match_dimension_boost(self, router):
        router._build_index()
        candidates = router._match_by_keyword("d5 dimension check", top_k=5)
        # Skills with dimension:D5 in description should get a boost
        assert len(candidates) > 0

    def test_keyword_match_no_results(self, router):
        router._build_index()
        candidates = router._match_by_keyword("xyzzyplugh nothing matches", top_k=5)
        # May return 0 or low-score results
        assert isinstance(candidates, list)

    def test_keyword_match_empty_index(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        r = IntentRouter(skills_dir=empty_dir, ollama_url="http://127.0.0.1:99999/api/embed")
        r._build_index()
        candidates = r._match_by_keyword("anything", top_k=5)
        assert candidates == []


# ============================================================
# Route Method (End-to-End)
# ============================================================

class TestRoute:
    def test_route_returns_routing_result(self, router):
        result = router.route("I need resilience handling")
        assert isinstance(result, RoutingResult)
        assert result.intent == "I need resilience handling"

    def test_route_with_empty_index(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        r = IntentRouter(skills_dir=empty_dir, ollama_url="http://127.0.0.1:99999/api/embed")
        result = r.route("anything")
        assert result.candidates == []
        assert result.primary is None

    def test_route_sets_primary_and_enhancers(self, router):
        result = router.route("security and resilience", top_k=3)
        # If candidates found, primary should be set
        if result.candidates:
            assert result.primary is not None
            assert result.primary.skill_id == result.candidates[0].skill_id

    def test_route_deduplicates_candidates(self, router):
        result = router.route("resilience degradation", top_k=10)
        # No duplicate skill_ids
        ids = [c.skill_id for c in result.candidates]
        assert len(ids) == len(set(ids))

    def test_route_top_k_limits_candidates(self, router):
        result = router.route("resilience", top_k=1)
        assert len(result.candidates) <= 1

    def test_route_l1_layer_always_used(self, router):
        result = router.route("resilience")
        assert "L1" in result.layers_used


# ============================================================
# Cosine Similarity
# ============================================================

class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert IntentRouter._cosine_similarity(a, b) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert IntentRouter._cosine_similarity(a, b) == pytest.approx(0.0)

    def test_zero_vector(self):
        a = [0.0, 0.0]
        b = [1.0, 0.0]
        assert IntentRouter._cosine_similarity(a, b) == 0.0

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert IntentRouter._cosine_similarity(a, b) == pytest.approx(-1.0)


# ============================================================
# L2 Logical Routing (Dependencies & Synergies)
# ============================================================

class TestL2LogicalRouting:
    def test_l2_adds_dependencies(self, router):
        router._build_index()
        l1 = [SkillCandidate(skill_id="S09-resilience-degradation", score=0.8, layer="L1")]
        l2 = router._route_l2_logical(l1)
        # S09 has dependency on S05a
        dep_ids = [c.skill_id for c in l2]
        assert "S05a" in dep_ids

    def test_l2_adds_synergies(self, router):
        router._build_index()
        l1 = [SkillCandidate(skill_id="S09-resilience-degradation", score=0.8, layer="L1")]
        l2 = router._route_l2_logical(l1)
        syn_ids = [c.skill_id for c in l2]
        assert "S10" in syn_ids

    def test_l2_empty_l1_returns_empty(self, router):
        router._build_index()
        l2 = router._route_l2_logical([])
        assert l2 == []

    def test_l2_dependency_score_scaled(self, router):
        router._build_index()
        l1 = [SkillCandidate(skill_id="S09-resilience-degradation", score=0.8, layer="L1")]
        l2 = router._route_l2_logical(l1)
        # Dependency score should be 0.8 * 0.7 = 0.56
        dep = [c for c in l2 if c.skill_id == "S05a"]
        if dep:
            assert dep[0].score == pytest.approx(0.56, abs=0.01)

    def test_l2_unknown_skill_returns_empty(self, router):
        router._build_index()
        l1 = [SkillCandidate(skill_id="NONEXISTENT", score=0.8, layer="L1")]
        l2 = router._route_l2_logical(l1)
        assert l2 == []


# ============================================================
# Ollama Check
# ============================================================

class TestOllamaCheck:
    def test_ollama_unavailable_returns_false(self, router):
        # Using a port that's definitely not listening
        result = router._check_ollama()
        assert result is False

    def test_ollama_check_caches_result(self, router):
        router._check_ollama()
        first = router._ollama_available
        router._check_ollama()
        assert router._ollama_available == first

    def test_try_ollama_base_unreachable(self):
        assert IntentRouter._try_ollama_base("http://127.0.0.1:99999") is False


# ============================================================
# Find Skill YAML
# ============================================================

class TestFindSkillYaml:
    def test_find_flat_yaml(self, router):
        router._build_index()
        results = router._find_skill_yaml("S09-resilience-degradation")
        assert len(results) >= 1
        # Should return (Path, dict) tuples
        for path, data in results:
            assert isinstance(data, dict)

    def test_find_directory_skill(self, router):
        router._build_index()
        results = router._find_skill_yaml("scaffold-docs")
        # Directory-based skill may not have YAML files
        assert isinstance(results, list)

    def test_find_nonexistent_skill(self, router):
        results = router._find_skill_yaml("NO_SUCH_SKILL")
        assert results == []
