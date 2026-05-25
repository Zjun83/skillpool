"""SkillPool Maintenance Cron — Periodic maintenance tasks for registry health."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .freeze_detector import FreezeDetector
from .wal_manager import WALManager


class MaintenanceResult(BaseModel):
    """Result of a maintenance run."""

    tasks_run: list[str] = []
    wal_compacted: int = 0
    frozen_recovered: list[str] = []
    errors: list[str] = []
    timestamp: str = ""

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if not self.timestamp:
            object.__setattr__(self, "timestamp", datetime.now(timezone.utc).isoformat())


class MaintenanceCron:
    """Periodic maintenance tasks for SkillPool registry health.

    Tasks:
    - WAL compaction: remove committed WAL entries
    - Freeze recovery: recover frozen operations
    - State cleanup: remove stale temporary files
    - Health report: generate system health summary
    """

    def __init__(self, state_dir: Path, stale_threshold: int = 300) -> None:
        self._state_dir = state_dir
        self._wal_dir = state_dir / "wal"
        self._wal_manager = WALManager(self._wal_dir)
        self._freeze_detector = FreezeDetector(state_dir, stale_threshold=stale_threshold)
        self._report_dir = state_dir / "maintenance_reports"
        self._report_dir.mkdir(parents=True, exist_ok=True)

    def run_all(self) -> MaintenanceResult:
        """Run all maintenance tasks."""
        result = MaintenanceResult()
        result.tasks_run.append("wal_compact")
        try:
            result.wal_compacted = self._wal_manager.compact()
        except Exception as e:
            result.errors.append(f"wal_compact: {e}")

        result.tasks_run.append("freeze_check")
        try:
            report = self._freeze_detector.check()
            if report.frozen_operations:
                result.frozen_recovered = self._freeze_detector.recover_all()
                result.tasks_run.append("freeze_recovery")
        except Exception as e:
            result.errors.append(f"freeze_check: {e}")

        result.tasks_run.append("state_cleanup")
        try:
            self._cleanup_temp_files()
        except Exception as e:
            result.errors.append(f"state_cleanup: {e}")

        self._save_report(result)
        return result

    def _cleanup_temp_files(self) -> int:
        """Remove stale .tmp files older than 1 hour."""
        removed = 0
        cutoff = datetime.now(timezone.utc).timestamp() - 3600
        for tmp_file in self._state_dir.rglob("*.tmp"):
            try:
                if tmp_file.stat().st_mtime < cutoff:
                    tmp_file.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    def _save_report(self, result: MaintenanceResult) -> None:
        """Save maintenance report to disk."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_path = self._report_dir / f"maintenance_{ts}.json"
        report_path.write_text(result.model_dump_json(), encoding="utf-8")
        # Keep only last 10 reports
        reports = sorted(self._report_dir.glob("maintenance_*.json"))
        for old in reports[:-10]:
            old.unlink()

    def get_last_report(self) -> dict[str, Any] | None:
        """Get the most recent maintenance report."""
        reports = sorted(self._report_dir.glob("maintenance_*.json"))
        if not reports:
            return None
        try:
            return json.loads(reports[-1].read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return None

    def get_health_summary(self) -> dict[str, Any]:
        """Generate a health summary of the SkillPool system."""
        wal_stats = self._wal_manager.get_stats()
        freeze_report = self._freeze_detector.check()
        last_report = self.get_last_report()
        return {
            "wal": wal_stats,
            "freeze_status": freeze_report.status.value,
            "frozen_operations": freeze_report.frozen_operations,
            "last_maintenance": last_report,
        }
