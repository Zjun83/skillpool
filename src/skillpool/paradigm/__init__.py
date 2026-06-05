"""
ParadigmRegistry — 4D 范式 Skill 注册 + 查询。

4 个 4D 范式:
  - DocsDD: 文档驱动开发（需求→规格→验收）
  - SDD: 规格驱动设计（接口→架构→评审）
  - BDD: 行为驱动开发（场景→测试→实现）
  - TDD: 测试驱动开发（红→绿→重构）

每个范式注册为 CSDF 文档，ParadigmRegistry 负责存储和查询。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Optional

import yaml


class Paradigm(StrEnum):
    DOCS_DD = "docsdd"
    SDD = "sdd"
    BDD = "bdd"
    TDD = "tdd"


# 4 个范式的 CSDF 定义
PARADigm_CSDFS: dict[Paradigm, dict] = {
    Paradigm.DOCS_DD: {
        "id": "paradigm-docsdd",
        "name": "DocsDD — 文档驱动开发",
        "version": "1.0.0",
        "dimension": "D11",
        "paradigm": "docsdd",
        "weight": 0.2,
        "description": "文档先行：需求文档 → 规格文档 → 验收标准",
        "checklist": [
            {"item": "需求文档完整", "priority": "high"},
            {"item": "规格文档对齐需求", "priority": "high"},
            {"item": "验收标准可量化", "priority": "medium"},
        ],
        "required_agent_capabilities": {"file_system"},
        "min_trust_level": 1,
        "lifecycle_state": "ACTIVE",
        "input_schema": {
            "type": "object",
            "properties": {
                "requirements": {"type": "string", "description": "需求描述"},
                "scope": {"type": "string", "description": "范围定义"},
            },
        },
        "output_schema": {
            "required": {"doc": "文档路径", "acceptance": "验收标准"},
        },
    },
    Paradigm.SDD: {
        "id": "paradigm-sdd",
        "name": "SDD — 规格驱动设计",
        "version": "1.0.0",
        "dimension": "D11",
        "paradigm": "sdd",
        "weight": 0.2,
        "description": "规格先行：接口定义 → 架构设计 → 同行评审",
        "checklist": [
            {"item": "接口定义明确", "priority": "high"},
            {"item": "架构图更新", "priority": "high"},
            {"item": "同行评审通过", "priority": "medium"},
        ],
        "required_agent_capabilities": {"file_system", "python"},
        "min_trust_level": 2,
        "lifecycle_state": "ACTIVE",
        "input_schema": {
            "type": "object",
            "properties": {
                "spec": {"type": "string", "description": "规格文档路径"},
                "interfaces": {"type": "array", "description": "接口列表"},
            },
        },
        "output_schema": {
            "required": {"design_doc": "设计文档", "interfaces": "接口定义"},
        },
    },
    Paradigm.BDD: {
        "id": "paradigm-bdd",
        "name": "BDD — 行为驱动开发",
        "version": "1.0.0",
        "dimension": "D7",
        "paradigm": "bdd",
        "weight": 0.3,
        "description": "行为先行：场景定义 → 测试用例 → 实现",
        "checklist": [
            {"item": "场景覆盖完整", "priority": "high"},
            {"item": "测试用例可执行", "priority": "high"},
            {"item": "Given-When-Then 格式", "priority": "medium"},
        ],
        "required_agent_capabilities": {"bash", "file_system", "python"},
        "min_trust_level": 2,
        "lifecycle_state": "ACTIVE",
        "input_schema": {
            "type": "object",
            "properties": {
                "scenarios": {"type": "array", "description": "BDD 场景列表"},
                "feature": {"type": "string", "description": "Feature 名称"},
            },
        },
        "output_schema": {
            "required": {"test_file": "测试文件路径", "coverage": "覆盖率"},
        },
    },
    Paradigm.TDD: {
        "id": "paradigm-tdd",
        "name": "TDD — 测试驱动开发",
        "version": "1.0.0",
        "dimension": "D7",
        "paradigm": "tdd",
        "weight": 0.3,
        "description": "测试先行：红（写失败测试）→ 绿（最小实现）→ 重构",
        "checklist": [
            {"item": "测试先于实现", "priority": "high"},
            {"item": "红→绿→重构循环", "priority": "high"},
            {"item": "覆盖率 ≥ 90%", "priority": "medium"},
        ],
        "required_agent_capabilities": {"bash", "file_system", "python"},
        "min_trust_level": 2,
        "lifecycle_state": "ACTIVE",
        "input_schema": {
            "type": "object",
            "properties": {
                "test_spec": {"type": "string", "description": "测试规格"},
                "target": {"type": "string", "description": "目标模块"},
            },
        },
        "output_schema": {
            "required": {"test_file": "测试文件", "impl_file": "实现文件"},
        },
    },
}


@dataclass
class ParadigmEntry:
    """注册表中的一条范式记录。"""
    paradigm: Paradigm
    csdf: dict
    registered_at: str = ""
    gate_file: Optional[str] = None


class OverrideLevel(StrEnum):
    """Emergency override severity levels."""
    WARN = "WARN"
    DEGRADE = "DEGRADE"
    QUARANTINE = "QUARANTINE"
    KILL = "KILL"


@dataclass
class EmergencyOverride:
    """An emergency override applied to a paradigm or skill."""
    level: OverrideLevel
    target: str  # paradigm name or skill_id
    reason: str
    applied_at: str = ""
    revoked: bool = False


class ParadigmRegistry:
    """4D 范式注册表 — 存储、查询、校验。

    Usage:
        registry = ParadigmRegistry()
        registry.register_defaults()
        entry = registry.get(Paradigm.TDD)
        all_entries = registry.list_all()
    """

    def __init__(self, persist_dir: Optional[Path] = None):
        self._entries: dict[Paradigm, ParadigmEntry] = {}
        self.persist_dir = persist_dir
        self._overrides: list[EmergencyOverride] = []

    def register(self, paradigm: Paradigm, csdf: dict) -> ParadigmEntry:
        """注册一个范式 CSDF。"""
        from datetime import datetime, timezone
        entry = ParadigmEntry(
            paradigm=paradigm,
            csdf=csdf,
            registered_at=datetime.now(timezone.utc).isoformat(),
        )
        self._entries[paradigm] = entry
        if self.persist_dir:
            self._save_to_disk(entry)
        return entry

    def register_defaults(self) -> None:
        """注册 4 个默认 4D 范式。"""
        for p, csdf in PARADigm_CSDFS.items():
            self.register(p, csdf)

    def get(self, paradigm: Paradigm) -> Optional[ParadigmEntry]:
        """查询指定范式。"""
        return self._entries.get(paradigm)

    def get_by_name(self, name: str) -> Optional[ParadigmEntry]:
        """按名称查询范式（大小写不敏感）。"""
        name_lower = name.lower()
        for p, entry in self._entries.items():
            if p.value == name_lower or name_lower in entry.csdf.get("name", "").lower():
                return entry
        return None

    def list_all(self) -> list[ParadigmEntry]:
        """列出所有已注册范式。"""
        return list(self._entries.values())

    def unregister(self, paradigm: Paradigm) -> bool:
        """注销一个范式。"""
        if paradigm in self._entries:
            del self._entries[paradigm]
            return True
        return False

    def validate(self, paradigm: Paradigm) -> list[str]:
        """校验范式 CSDF 完整性，返回错误列表。"""
        entry = self._entries.get(paradigm)
        if not entry:
            return [f"paradigm {paradigm} not registered"]

        errors = []
        csdf = entry.csdf
        required_fields = ["id", "name", "version", "dimension", "paradigm", "checklist"]
        for f in required_fields:
            if f not in csdf or not csdf[f]:
                errors.append(f"missing or empty field: {f}")

        checklist = csdf.get("checklist", [])
        if checklist:
            for i, item in enumerate(checklist):
                if not item.get("item") and not item.get("description"):
                    errors.append(f"checklist[{i}] missing item/description")
                if not item.get("priority") and not item.get("severity"):
                    errors.append(f"checklist[{i}] missing priority/severity")

        return errors

    def apply_override(self, level: OverrideLevel, target: str, reason: str) -> EmergencyOverride:
        """Apply an emergency override to a paradigm or skill.

        WARN: Log warning, continue operation.
        DEGRADE: Reduce functionality (e.g., skip non-critical checks).
        QUARANTINE: Isolate the target from active processing.
        KILL: Immediately stop all operations for the target.
        """
        from datetime import datetime, timezone
        override = EmergencyOverride(
            level=level,
            target=target,
            reason=reason,
            applied_at=datetime.now(timezone.utc).isoformat(),
        )
        self._overrides.append(override)

        # For QUARANTINE/KILL, unregister the paradigm if it matches
        if level in (OverrideLevel.QUARANTINE, OverrideLevel.KILL):
            for p in list(self._entries.keys()):
                if p.value == target.lower():
                    self._entries[p].csdf["lifecycle_state"] = "QUARANTINED" if level == OverrideLevel.QUARANTINE else "KILLED"

        return override

    def revoke_override(self, target: str) -> bool:
        """Revoke the most recent active override for a target."""
        for override in reversed(self._overrides):
            if override.target == target and not override.revoked:
                override.revoked = True
                # Restore lifecycle state if paradigm exists
                for p, entry in self._entries.items():
                    if p.value == target.lower() and entry.csdf.get("lifecycle_state") in ("QUARANTINED", "KILLED"):
                        entry.csdf["lifecycle_state"] = "ACTIVE"
                return True
        return False

    def get_active_overrides(self) -> list[EmergencyOverride]:
        """Get all active (non-revoked) overrides."""
        return [o for o in self._overrides if not o.revoked]

    def get_override_level(self, target: str) -> Optional[OverrideLevel]:
        """Get the highest active override level for a target."""
        active = [o for o in self._overrides if o.target == target and not o.revoked]
        if not active:
            return None
        # Priority: KILL > QUARANTINE > DEGRADE > WARN
        priority = {OverrideLevel.KILL: 4, OverrideLevel.QUARANTINE: 3, OverrideLevel.DEGRADE: 2, OverrideLevel.WARN: 1}
        return max(active, key=lambda o: priority[o.level]).level

    def _save_to_disk(self, entry: ParadigmEntry) -> None:
        """持久化到 YAML 文件。"""
        if not self.persist_dir:
            return
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        path = self.persist_dir / f"{entry.paradigm.value}.yaml"
        path.write_text(yaml.dump(entry.csdf, default_flow_style=False, allow_unicode=True))
