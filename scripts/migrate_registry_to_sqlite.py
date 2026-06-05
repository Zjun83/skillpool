#!/usr/bin/env python3
"""Migrate SkillPool registry from JSONL/JSON to SQLite.

Usage:
    python scripts/migrate_registry_to_sqlite.py [--source ~/.skillpool/registry.jsonl] [--target ~/.skillpool/registry.db]

Part of SkillPool — independent infrastructure, shared by all agents.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path


def migrate_jsonl(source: Path, target: Path) -> int:
    """Migrate from JSONL format to SQLite."""
    conn = sqlite3.connect(str(target))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS skills (skill_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        count = 0
        for line in source.read_text(encoding="utf-8").strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Extract or generate skill_id
            skill_id = record.get("skill_id") or record.get("id") or record.get("name", f"unknown-{count}")

            # Wrap in Registry-compatible format if not already
            if "metadata" not in record:
                record = {
                    "metadata": {
                        "skill_id": skill_id,
                        "name": record.get("name", skill_id),
                        "version": record.get("version", "0.0.0"),
                        "status": record.get("status", "draft"),
                        "description": record.get("description", ""),
                        "author": record.get("author", ""),
                        "created_at": record.get("registered_at", ""),
                        "updated_at": record.get("updated_at", ""),
                        "tags": record.get("tags", []),
                        "dependencies": record.get("dependencies", []),
                        "security": record.get("security", {}),
                        "quality_score": record.get("quality_score", 0.0),
                    },
                    "created_at": record.get("registered_at", datetime.now(UTC).isoformat()),
                    "updated_at": record.get("updated_at", datetime.now(UTC).isoformat()),
                    "evidence": record.get("evidence", []),
                    "audit_refs": record.get("audit_refs", []),
                }

            conn.execute(
                "INSERT OR REPLACE INTO skills (skill_id, data) VALUES (?, ?)",
                (skill_id, json.dumps(record, ensure_ascii=False)),
            )
            count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def migrate_json(source: Path, target: Path) -> int:
    """Migrate from JSON dict format to SQLite."""
    conn = sqlite3.connect(str(target))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS skills (skill_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        data = json.loads(source.read_text(encoding="utf-8"))
        count = 0
        for skill_id, sdata in data.items():
            # Wrap in Registry-compatible format if needed
            if "metadata" not in sdata:
                sdata = {
                    "metadata": {
                        "skill_id": skill_id,
                        "name": sdata.get("name", skill_id),
                        "version": sdata.get("version", "0.0.0"),
                        "status": sdata.get("status", "draft"),
                        "description": sdata.get("description", ""),
                        "author": sdata.get("author", ""),
                        "created_at": sdata.get("registered_at", ""),
                        "updated_at": sdata.get("updated_at", ""),
                        "tags": sdata.get("tags", []),
                        "dependencies": sdata.get("dependencies", []),
                        "security": sdata.get("security", {}),
                        "quality_score": sdata.get("quality_score", 0.0),
                    },
                    "created_at": sdata.get("registered_at", datetime.now(UTC).isoformat()),
                    "updated_at": sdata.get("updated_at", datetime.now(UTC).isoformat()),
                    "evidence": sdata.get("evidence", []),
                    "audit_refs": sdata.get("audit_refs", []),
                }
            conn.execute(
                "INSERT OR REPLACE INTO skills (skill_id, data) VALUES (?, ?)",
                (skill_id, json.dumps(sdata, ensure_ascii=False)),
            )
            count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate SkillPool registry to SQLite")
    parser.add_argument("--source", type=Path, default=Path.home() / ".skillpool" / "registry.jsonl")
    parser.add_argument("--target", type=Path, default=Path.home() / ".skillpool" / "registry.db")
    args = parser.parse_args()

    if not args.source.exists():
        print(f"Source file not found: {args.source}")
        sys.exit(1)

    # Backup source
    backup = args.source.with_suffix(args.source.suffix + ".bak")
    shutil.copy2(args.source, backup)
    print(f"Backup: {backup}")

    # Migrate
    suffix = args.source.suffix.lower()
    if suffix == ".jsonl":
        count = migrate_jsonl(args.source, args.target)
    else:
        count = migrate_json(args.source, args.target)

    # Verify
    conn = sqlite3.connect(str(args.target))
    db_count = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    conn.close()

    print(f"Migrated {count} records to {args.target}")
    print(f"SQLite contains {db_count} records")
    if count == db_count:
        print("Migration verified: record counts match")
    else:
        print(f"WARNING: count mismatch ({count} migrated vs {db_count} in DB)")
        sys.exit(1)


if __name__ == "__main__":
    main()
