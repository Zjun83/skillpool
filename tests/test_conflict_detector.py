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
