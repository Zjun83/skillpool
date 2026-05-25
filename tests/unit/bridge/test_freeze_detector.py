"""Tests for SkillPool Freeze Detector."""

import time
from pathlib import Path

import pytest

from skillpool.bridge.freeze_detector import FreezeDetector, FreezeStatus


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "state"


@pytest.fixture
def detector(state_dir: Path) -> FreezeDetector:
    return FreezeDetector(state_dir, stale_threshold=1)


class TestFreezeDetector:
    def test_heartbeat_creates_file(self, detector: FreezeDetector, state_dir: Path):
        detector.heartbeat("op-1")
        hb_file = state_dir / "freeze_state" / "heartbeats" / "op-1.json"
        assert hb_file.exists()

    def test_complete_operation_removes_heartbeat(self, detector: FreezeDetector):
        detector.heartbeat("op-1")
        detector.complete_operation("op-1")
        report = detector.check()
        assert report.status == FreezeStatus.HEALTHY

    def test_check_healthy_when_no_operations(self, detector: FreezeDetector):
        report = detector.check()
        assert report.status == FreezeStatus.HEALTHY

    def test_check_frozen_after_stale_threshold(self, detector: FreezeDetector):
        detector.heartbeat("op-1")
        time.sleep(1.5)  # exceed stale_threshold=1
        report = detector.check()
        assert report.status == FreezeStatus.FROZEN
        assert "op-1" in report.frozen_operations

    def test_recover_frozen_operation(self, detector: FreezeDetector):
        detector.heartbeat("op-1")
        time.sleep(1.5)
        result = detector.recover("op-1")
        assert result is True
        report = detector.check()
        assert report.status == FreezeStatus.HEALTHY

    def test_recover_nonexistent_returns_false(self, detector: FreezeDetector):
        result = detector.recover("ghost-op")
        assert result is False

    def test_recover_all(self, detector: FreezeDetector):
        detector.heartbeat("op-1")
        detector.heartbeat("op-2")
        recovered = detector.recover_all()
        assert len(recovered) == 2

    def test_list_active_operations(self, detector: FreezeDetector):
        detector.heartbeat("op-1")
        detector.heartbeat("op-2")
        ops = detector.list_active_operations()
        assert len(ops) == 2
        names = {o["operation_id"] for o in ops}
        assert names == {"op-1", "op-2"}

    def test_freeze_report_timestamp(self, detector: FreezeDetector):
        report = detector.check()
        assert report.timestamp != ""
