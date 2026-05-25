"""Tests for SkillPool Maintenance Cron."""

from pathlib import Path

import pytest

from skillpool.bridge.maintenance import MaintenanceCron, MaintenanceResult


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "state"


@pytest.fixture
def cron(state_dir: Path) -> MaintenanceCron:
    return MaintenanceCron(state_dir, stale_threshold=1)


class TestMaintenanceResult:
    def test_result_creation(self):
        result = MaintenanceResult()
        assert result.timestamp != ""
        assert result.tasks_run == []
        assert result.errors == []


class TestMaintenanceCron:
    def test_run_all_completes(self, cron: MaintenanceCron):
        result = cron.run_all()
        assert "wal_compact" in result.tasks_run
        assert "freeze_check" in result.tasks_run
        assert "state_cleanup" in result.tasks_run

    def test_run_all_saves_report(self, cron: MaintenanceCron, state_dir: Path):
        cron.run_all()
        reports = list((state_dir / "maintenance_reports").glob("maintenance_*.json"))
        assert len(reports) == 1

    def test_run_all_wal_compact(self, cron: MaintenanceCron, state_dir: Path):
        from skillpool.bridge.wal_manager import WALEntryType, WALManager

        wal = WALManager(state_dir / "wal")
        wal.append(WALEntryType.REGISTER, "skill-a")
        result = cron.run_all()
        assert result.wal_compacted >= 0

    def test_get_last_report_none_initially(self, cron: MaintenanceCron):
        report = cron.get_last_report()
        assert report is None

    def test_get_last_report_after_run(self, cron: MaintenanceCron):
        cron.run_all()
        report = cron.get_last_report()
        assert report is not None
        assert "tasks_run" in report

    def test_get_health_summary(self, cron: MaintenanceCron):
        summary = cron.get_health_summary()
        assert "wal" in summary
        assert "freeze_status" in summary

    def test_cleanup_temp_files(self, cron: MaintenanceCron, state_dir: Path):
        tmp_file = state_dir / "test.tmp"
        tmp_file.write_text("stale")
        import os
        import time

        # Set mtime to 2 hours ago
        old_time = time.time() - 7200
        os.utime(tmp_file, (old_time, old_time))
        cron._cleanup_temp_files()
        assert not tmp_file.exists()

    def test_report_retention_limit(self, cron: MaintenanceCron, state_dir: Path):
        for _ in range(12):
            cron.run_all()
        reports = list((state_dir / "maintenance_reports").glob("maintenance_*.json"))
        assert len(reports) <= 10
