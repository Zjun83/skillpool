"""SkillPool Registry — JSONL-backed CRUD for skill metadata."""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class SkillEntry(BaseModel):
    """A single skill entry in the registry."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    quality_score: float = 0.0
    dimensions: dict[str, float] = Field(default_factory=dict)
    csdf_hash: str = ""
    registered_at: str = ""
    updated_at: str = ""
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Registry:
    """JSONL-backed skill registry with CRUD operations."""

    def __init__(self, registry_path: Path) -> None:
        self._path = registry_path
        self._ensure_file()

    def _ensure_file(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _read_all(self) -> list[SkillEntry]:
        entries: list[SkillEntry] = []
        if not self._path.exists():
            return entries
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entries.append(SkillEntry(**data))
                except (json.JSONDecodeError, Exception):
                    continue
        return entries

    def _write_all(self, entries: list[SkillEntry]) -> None:
        tmp_path = self._path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            for entry in entries:
                f.write(entry.model_dump_json() + "\n")
        tmp_path.replace(self._path)

    def register(self, entry: SkillEntry, force: bool = False) -> SkillEntry:
        entries = self._read_all()
        existing = self.get(entry.name)
        if existing is not None:
            if not force:
                raise ValueError(
                    f"Skill '{entry.name}' already registered. Use force=True to overwrite."
                )
            entries = [e for e in entries if e.name != entry.name]
        entry.registered_at = entry.registered_at or self._now()
        entry.updated_at = self._now()
        entries.append(entry)
        self._write_all(entries)
        return entry

    def get(self, name: str) -> SkillEntry | None:
        for entry in self._read_all():
            if entry.name == name:
                return entry
        return None

    def list_entries(
        self, min_score: float = 0.0, tags: list[str] | None = None
    ) -> list[SkillEntry]:
        entries = self._read_all()
        if min_score > 0:
            entries = [e for e in entries if e.quality_score >= min_score]
        if tags:
            tag_set = set(tags)
            entries = [e for e in entries if tag_set.intersection(e.tags)]
        return entries

    def update(self, name: str, updates: dict[str, Any]) -> SkillEntry | None:
        entries = self._read_all()
        found = False
        for i, entry in enumerate(entries):
            if entry.name == name:
                updated_data = entry.model_dump()
                updated_data.update(updates)
                updated_data["updated_at"] = self._now()
                entries[i] = SkillEntry(**updated_data)
                found = True
                break
        if not found:
            return None
        self._write_all(entries)
        return entries[[e.name for e in entries].index(name)]

    def delete(self, name: str) -> bool:
        entries = self._read_all()
        original_len = len(entries)
        entries = [e for e in entries if e.name != name]
        if len(entries) == original_len:
            return False
        self._write_all(entries)
        return True

    def count(self) -> int:
        return len(self._read_all())

    def iter_entries(self) -> Generator[SkillEntry, None, None]:
        if not self._path.exists():
            return
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    yield SkillEntry(**data)
                except (json.JSONDecodeError, Exception):
                    continue
