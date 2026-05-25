"""Tests for SkillPool WAL Manager."""

from pathlib import Path

import pytest

from skillpool.bridge.wal_manager import WALEntry, WALEntryType, WALManager


@pytest.fixture
def wal_dir(tmp_path: Path) -> Path:
    return tmp_path / "wal"


@pytest.fixture
def wal(wal_dir: Path) -> WALManager:
    return WALManager(wal_dir)


class TestWALEntry:
    def test_entry_creation(self):
        entry = WALEntry(entry_type=WALEntryType.REGISTER, skill_name="test")
        assert entry.skill_name == "test"
        assert entry.entry_type == WALEntryType.REGISTER
        assert entry.timestamp != ""

    def test_entry_with_data(self):
        entry = WALEntry(
            entry_type=WALEntryType.UPDATE,
            skill_name="test",
            data={"quality_score": 0.9},
        )
        assert entry.data["quality_score"] == 0.9


class TestWALManager:
    def test_append_creates_wal_file(self, wal: WALManager, wal_dir: Path):
        wal.append(WALEntryType.REGISTER, "skill-a")
        assert (wal_dir / "wal.jsonl").exists()

    def test_append_and_read(self, wal: WALManager):
        wal.append(WALEntryType.REGISTER, "skill-a")
        wal.append(WALEntryType.UPDATE, "skill-b", {"score": 0.5})
        entries = wal.read_uncommitted()
        assert len(entries) == 2
        assert entries[0].skill_name == "skill-a"
        assert entries[1].entry_type == WALEntryType.UPDATE

    def test_checkpoint_clears_uncommitted(self, wal: WALManager):
        wal.append(WALEntryType.REGISTER, "skill-a")
        wal.checkpoint()
        entries = wal.read_uncommitted()
        assert len(entries) == 0

    def test_recover_returns_uncommitted(self, wal: WALManager):
        wal.append(WALEntryType.REGISTER, "skill-a")
        wal.append(WALEntryType.DELETE, "skill-b")
        recovered = wal.recover()
        assert len(recovered) == 2

    def test_recover_empty_after_checkpoint(self, wal: WALManager):
        wal.append(WALEntryType.REGISTER, "skill-a")
        wal.checkpoint()
        recovered = wal.recover()
        assert len(recovered) == 0

    def test_get_stats(self, wal: WALManager):
        wal.append(WALEntryType.REGISTER, "skill-a")
        stats = wal.get_stats()
        assert stats["uncommitted_count"] == 1
        assert "wal_file_size_bytes" in stats

    def test_compact_removes_nothing_when_all_uncommitted(self, wal: WALManager):
        wal.append(WALEntryType.REGISTER, "skill-a")
        removed = wal.compact()
        assert removed == 0

    def test_txn_id_unique(self, wal: WALManager):
        e1 = wal.append(WALEntryType.REGISTER, "a")
        e2 = wal.append(WALEntryType.REGISTER, "b")
        assert e1.txn_id != e2.txn_id

    def test_read_uncommitted_empty_on_new_wal(self, wal: WALManager):
        assert wal.read_uncommitted() == []
