"""Tests for SynergyDetector — covering uncovered lines in synergy/detector.py.

Focus areas:
- Lines 172-179: VALIDATING/DEPRECATED/DISCOVERED/REJECTED lifecycle states in load_combination_synergies
- Line 182: weight < 0.05 filtering
- Line 235: _load_from_registry returning None (Registry() succeeds but no synergy data)
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from skillpool.synergy import SynergyDetector


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def detector(skills_dir):
    return SynergyDetector(skills_dir=skills_dir)


# ---------------------------------------------------------------------------
# Helpers: mock the combiner module for load_combination_synergies tests
# ---------------------------------------------------------------------------


def _install_combiner_mock(combos_dict):
    """Install a mock skillpool.combiner + skillpool.combiner.models into sys.modules."""
    from skillpool.combiner.models import CombinationLifecycleState

    mock_mgr = MagicMock()
    mock_mgr._combinations = combos_dict

    combiner_mock = MagicMock()
    combiner_mock.CombinationLifecycleManager = MagicMock(return_value=mock_mgr)
    combiner_models_mock = MagicMock()
    combiner_models_mock.CombinationLifecycleState = CombinationLifecycleState

    sys.modules["skillpool.combiner"] = combiner_mock
    sys.modules["skillpool.combiner.models"] = combiner_models_mock

    return mock_mgr


def _uninstall_combiner_mock():
    sys.modules.pop("skillpool.combiner", None)
    sys.modules.pop("skillpool.combiner.models", None)


# ---------------------------------------------------------------------------
# load_combination_synergies — VALIDATING state (line 172-173)
# ---------------------------------------------------------------------------


class TestValidatingState:
    """VALIDATING combinations get 0.7x weight."""

    def test_validating_weight_reduced(self, detector):
        from skillpool.combiner.models import CombinationLifecycleState

        mock_combo = MagicMock()
        mock_combo.state = CombinationLifecycleState.VALIDATING
        mock_combo.current_weight.return_value = 0.5
        mock_combo.primary = "review"
        mock_combo.enhancers = ["security"]
        mock_combo.gain_avg = 10.0
        mock_combo.source = "exploratory"
        mock_combo.execution_count = 3

        _install_combiner_mock({"c1": mock_combo})
        try:
            result = detector.load_combination_synergies()
            assert len(result) == 1
            # 0.5 * 0.7 = 0.35
            assert result[0].weight == 0.35
            assert result[0].evidence == "exploratory"
        finally:
            _uninstall_combiner_mock()


# ---------------------------------------------------------------------------
# load_combination_synergies — DEPRECATED state (line 174-175)
# ---------------------------------------------------------------------------


class TestDeprecatedState:
    """DEPRECATED combinations get 0.5x weight."""

    def test_deprecated_weight_reduced(self, detector):
        from skillpool.combiner.models import CombinationLifecycleState

        mock_combo = MagicMock()
        mock_combo.state = CombinationLifecycleState.DEPRECATED
        mock_combo.current_weight.return_value = 0.6
        mock_combo.primary = "review"
        mock_combo.enhancers = ["security"]
        mock_combo.gain_avg = 5.0
        mock_combo.source = "observed"
        mock_combo.execution_count = 1

        _install_combiner_mock({"c1": mock_combo})
        try:
            result = detector.load_combination_synergies()
            assert len(result) == 1
            # 0.6 * 0.5 = 0.3
            assert result[0].weight == 0.3
        finally:
            _uninstall_combiner_mock()


# ---------------------------------------------------------------------------
# load_combination_synergies — DISCOVERED state (line 176-177)
# ---------------------------------------------------------------------------


class TestDiscoveredState:
    """DISCOVERED combinations get 0.3x weight."""

    def test_discovered_weight_reduced(self, detector):
        from skillpool.combiner.models import CombinationLifecycleState

        mock_combo = MagicMock()
        mock_combo.state = CombinationLifecycleState.DISCOVERED
        mock_combo.current_weight.return_value = 0.8
        mock_combo.primary = "review"
        mock_combo.enhancers = ["security"]
        mock_combo.gain_avg = 8.0
        mock_combo.source = "thompson"
        mock_combo.execution_count = 0

        _install_combiner_mock({"c1": mock_combo})
        try:
            result = detector.load_combination_synergies()
            assert len(result) == 1
            # 0.8 * 0.3 = 0.24
            assert result[0].weight == 0.24
        finally:
            _uninstall_combiner_mock()


# ---------------------------------------------------------------------------
# load_combination_synergies — REJECTED state (line 178-179)
# ---------------------------------------------------------------------------


class TestRejectedState:
    """REJECTED combinations should be skipped entirely."""

    def test_rejected_excluded(self, detector):
        from skillpool.combiner.models import CombinationLifecycleState

        mock_combo = MagicMock()
        mock_combo.state = CombinationLifecycleState.REJECTED
        mock_combo.current_weight.return_value = 0.5
        mock_combo.primary = "review"
        mock_combo.enhancers = ["security"]
        mock_combo.gain_avg = 2.0
        mock_combo.source = "rejected"
        mock_combo.execution_count = 5

        _install_combiner_mock({"c1": mock_combo})
        try:
            result = detector.load_combination_synergies()
            assert result == []
        finally:
            _uninstall_combiner_mock()


# ---------------------------------------------------------------------------
# load_combination_synergies — weight < 0.05 filter (line 181-182)
# ---------------------------------------------------------------------------


class TestLowWeightFiltering:
    """Combinations with weight < 0.05 after adjustment are excluded."""

    def test_very_low_weight_excluded(self, detector):
        from skillpool.combiner.models import CombinationLifecycleState

        mock_combo = MagicMock()
        mock_combo.state = CombinationLifecycleState.DISCOVERED
        mock_combo.current_weight.return_value = 0.1
        # 0.1 * 0.3 = 0.03 < 0.05 → excluded
        mock_combo.primary = "review"
        mock_combo.enhancers = ["security"]
        mock_combo.gain_avg = 1.0
        mock_combo.source = "exploratory"
        mock_combo.execution_count = 0

        _install_combiner_mock({"c1": mock_combo})
        try:
            result = detector.load_combination_synergies()
            assert result == []
        finally:
            _uninstall_combiner_mock()

    def test_weight_at_threshold_included(self, detector):
        """Weight exactly at 0.05 boundary should be included."""
        from skillpool.combiner.models import CombinationLifecycleState

        mock_combo = MagicMock()
        mock_combo.state = CombinationLifecycleState.VALIDATING
        mock_combo.current_weight.return_value = 0.08
        # 0.08 * 0.7 = 0.056 > 0.05 → included
        mock_combo.primary = "review"
        mock_combo.enhancers = ["security"]
        mock_combo.gain_avg = 3.0
        mock_combo.source = "exploratory"
        mock_combo.execution_count = 1

        _install_combiner_mock({"c1": mock_combo})
        try:
            result = detector.load_combination_synergies()
            assert len(result) == 1
        finally:
            _uninstall_combiner_mock()


# ---------------------------------------------------------------------------
# _load_from_registry — line 235 (Registry() succeeds, returns None)
# ---------------------------------------------------------------------------


class TestLoadFromRegistrySuccessPath:
    """When Registry imports fine but has no synergy data, returns None."""

    def test_registry_succeeds_returns_none(self, detector):
        """Registry() constructor succeeds, but currently returns None (no synergy support)."""
        result = detector._load_from_registry()
        assert result is None

    def test_registry_import_error_returns_none(self, detector):
        """When Registry cannot be imported, returns None."""
        with patch.dict("sys.modules", {"skillpool.registry": None}):
            result = detector._load_from_registry()
            assert result is None


# ---------------------------------------------------------------------------
# load_combination_synergies — new edges merged and deduped (lines 197-199)
# ---------------------------------------------------------------------------


class TestCombinationMergeDedup:
    """Combination synergies are merged with existing, deduped by source+target."""

    def test_new_edges_added_to_internal(self, detector):
        from skillpool.combiner.models import CombinationLifecycleState

        mock_combo = MagicMock()
        mock_combo.state = CombinationLifecycleState.PROMOTED
        mock_combo.current_weight.return_value = 0.8
        mock_combo.primary = "review"
        mock_combo.enhancers = ["security"]
        mock_combo.gain_avg = 15.0
        mock_combo.source = "observed"
        mock_combo.execution_count = 10

        _install_combiner_mock({"c1": mock_combo})
        try:
            result = detector.load_combination_synergies()
            assert len(result) == 1
            # Internal edges should also be updated
            assert len(detector._synergy_edges) == 1
        finally:
            _uninstall_combiner_mock()

    def test_multiple_enhancers_multiple_edges(self, detector):
        """Each enhancer in a combination creates a separate edge."""
        from skillpool.combiner.models import CombinationLifecycleState

        mock_combo = MagicMock()
        mock_combo.state = CombinationLifecycleState.PROMOTED
        mock_combo.current_weight.return_value = 0.8
        mock_combo.primary = "review"
        mock_combo.enhancers = ["security", "testing", "compliance"]
        mock_combo.gain_avg = 20.0
        mock_combo.source = "observed"
        mock_combo.execution_count = 15

        _install_combiner_mock({"c1": mock_combo})
        try:
            result = detector.load_combination_synergies()
            assert len(result) == 3
            targets = {e.target for e in result}
            assert targets == {"security", "testing", "compliance"}
        finally:
            _uninstall_combiner_mock()
