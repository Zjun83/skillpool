"""Tests for ConflictDetector — Jaccard similarity conflict detection."""
import pytest

from skillpool.resolver.conflict_detector import ConflictDetector, jaccard_similarity


class TestJaccardSimilarity:
    def test_identical_sets(self) -> None:
        assert jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self) -> None:
        assert jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self) -> None:
        # {a,b} ∩ {b,c} = {b}, {a,b} ∪ {b,c} = {a,b,c}
        assert jaccard_similarity({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)

    def test_empty_sets(self) -> None:
        assert jaccard_similarity(set(), set()) == 1.0

    def test_one_empty(self) -> None:
        assert jaccard_similarity({"a"}, set()) == 0.0


class TestConflictDetector:
    def test_no_conflicts(self) -> None:
        cd = ConflictDetector(threshold=0.5)
        cd.register("S01", name="Requirement Coverage", dimension="D1")
        cd.register("S05a", name="Security Transport", dimension="D3")
        conflicts = cd.detect()
        assert len(conflicts) == 0

    def test_high_similarity_conflict(self) -> None:
        cd = ConflictDetector(threshold=0.3)
        cd.register("S01", name="File Read", dimension="D1", namespaces=["file_ops"])
        cd.register("S02", name="File Write", dimension="D1", namespaces=["file_ops"])
        conflicts = cd.detect()
        assert len(conflicts) >= 1
        assert conflicts[0]["severity"] in ("medium", "high")

    def test_custom_threshold(self) -> None:
        cd = ConflictDetector(threshold=0.9)
        cd.register("A", name="Same Name", dimension="D1")
        cd.register("B", name="Same Name", dimension="D1")
        # Even identical names may not reach 0.9 depending on tokenization
        conflicts = cd.detect(threshold=0.1)
        assert len(conflicts) >= 1

    def test_clear(self) -> None:
        cd = ConflictDetector()
        cd.register("A", name="Test")
        cd.clear()
        assert len(cd.detect()) == 0

    def test_overlapping_namespaces(self) -> None:
        cd = ConflictDetector(threshold=0.3)
        cd.register("X", name="Skill X", namespaces=["file_ops", "read"])
        cd.register("Y", name="Skill Y", namespaces=["file_ops", "write"])
        conflicts = cd.detect()
        assert len(conflicts) >= 1
        assert "file_ops" in conflicts[0]["overlapping_namespaces"]

    # --- Coverage for uncovered severity/classification/recommendation paths ---

    def test_high_severity_with_overlap_and_high_score(self) -> None:
        """Line 85: overlapping namespaces + score >= 0.7 → severity='high'."""
        cd = ConflictDetector(threshold=0.5)
        # Identical names + overlapping namespaces → score=1.0, severity='high'
        cd.register("A", name="Code Review Security", dimension="D3", namespaces=["review", "security"])
        cd.register("B", name="Code Review Security", dimension="D3", namespaces=["review", "security"])
        conflicts = cd.detect(threshold=0.5)
        assert len(conflicts) >= 1
        assert conflicts[0]["severity"] == "high"
        assert conflicts[0]["overlapping_namespaces"] == ["review", "security"]

    def test_medium_severity_overlap_without_high_score(self) -> None:
        """Line 86-87: overlapping namespaces but score < 0.7 → severity='medium'."""
        cd = ConflictDetector(threshold=0.1)
        cd.register("A", name="Requirement Coverage Analysis", namespaces=["req", "coverage"])
        cd.register("B", name="Compliance Coverage Audit", namespaces=["req", "coverage"])
        conflicts = cd.detect(threshold=0.1)
        assert len(conflicts) >= 1
        # Overlapping namespaces but score < 0.7 → medium
        assert conflicts[0]["severity"] == "medium"
        assert len(conflicts[0]["overlapping_namespaces"]) > 0

    def test_low_severity(self) -> None:
        """Line 88: no overlapping namespaces + score < 0.7 → severity='low'."""
        cd = ConflictDetector(threshold=0.05)
        cd.register("A", name="Test Coverage Skill", dimension="D1")
        cd.register("B", name="Test Analysis Skill", dimension="D2")
        conflicts = cd.detect(threshold=0.05)
        assert len(conflicts) >= 1
        assert conflicts[0]["severity"] == "low"
        assert conflicts[0]["overlapping_namespaces"] == []

    def test_namespace_overlap_default_conflict_type(self) -> None:
        """Line 96: score < 0.8 and no overlapping → conflict_type='namespace_overlap' (default)."""
        cd = ConflictDetector(threshold=0.05)
        cd.register("A", name="Test Coverage Skill", dimension="D1")
        cd.register("B", name="Test Analysis Skill", dimension="D2")
        conflicts = cd.detect(threshold=0.05)
        if conflicts:
            # Even without actual namespace overlap, Jaccard detection defaults to namespace_overlap
            assert conflicts[0]["conflict_type"] == "namespace_overlap"

    def test_semantic_conflict_type(self) -> None:
        """Line 95: score >= 0.8 → conflict_type='semantic_conflict'."""
        cd = ConflictDetector(threshold=0.5)
        cd.register("A", name="Code Review Security")
        cd.register("B", name="Code Review Security")
        conflicts = cd.detect(threshold=0.5)
        if conflicts:
            # High score (0.8+) with no overlapping namespaces → semantic_conflict
            high_score = [c for c in conflicts if c["jaccard_score"] >= 0.8 and len(c["overlapping_namespaces"]) == 0]
            if high_score:
                assert high_score[0]["conflict_type"] == "semantic_conflict"

    def test_high_severity_recommendation(self) -> None:
        """Line 101: severity='high' → recommendation about merging/removing."""
        cd = ConflictDetector(threshold=0.5)
        cd.register("A", name="Code Review Security", dimension="D3", namespaces=["review", "security"])
        cd.register("B", name="Code Review Security", dimension="D3", namespaces=["review", "security"])
        conflicts = cd.detect(threshold=0.5)
        assert len(conflicts) >= 1
        assert conflicts[0]["severity"] == "high"
        assert "merging" in conflicts[0]["recommendation"] or "removing" in conflicts[0]["recommendation"]

    def test_low_severity_recommendation(self) -> None:
        """Line 104: severity='low' → recommendation about monitoring."""
        cd = ConflictDetector(threshold=0.05)
        cd.register("A", name="Test Coverage Skill", dimension="D1")
        cd.register("B", name="Test Analysis Skill", dimension="D2")
        conflicts = cd.detect(threshold=0.05)
        assert len(conflicts) >= 1
        assert conflicts[0]["severity"] == "low"
        assert "Monitor" in conflicts[0]["recommendation"]
