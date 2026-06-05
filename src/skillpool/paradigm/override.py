"""
EmergencyOverride — 紧急降权协议。

当检测到安全事件、资源耗尽或不可恢复错误时，
EmergencyOverride 可以紧急降权 Agent 的 trust_level，
或完全禁止特定 Skill 的执行。

降权协议:
  1. 检测触发条件（安全事件/资源耗尽/不可恢复错误）
  2. 评估降权级别（trust_level 降低幅度）
  3. 执行降权（修改 gate_file + 通知 TelemetryBridge）
  4. 记录降权事件（审计日志）
  5. 恢复机制（手动或超时后自动恢复）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Optional

from skillpool.config import get_data_dir
from skillpool.telemetry import TelemetryBridge

logger = logging.getLogger(__name__)


class OverrideTrigger(StrEnum):
    SECURITY_EVENT = "security_event"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    UNRECOVERABLE_ERROR = "unrecoverable_error"
    MANUAL = "manual"


class OverrideLevel(StrEnum):
    WARN = "warn"  # 降低 trust_level 1 级
    DEGRADE = "degrade"  # 降低 trust_level 2 级
    QUARANTINE = "quarantine"  # trust_level → 0，禁止执行
    KILL = "kill"  # 完全禁止，需要人工恢复


@dataclass
class OverrideEvent:
    """降权事件记录。"""

    trigger: OverrideTrigger
    level: OverrideLevel
    target_skill: str = ""
    target_agent: str = ""
    original_trust: int = 3
    new_trust: int = 0
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None  # None = 需人工恢复


@dataclass
class GateFile:
    """Gate file — 单个 Skill 的门禁状态文件。

    格式:
    {
      "skill_id": "S05a",
      "trust_level": 3,
      "blocked": false,
      "override_history": [...]
    }
    """

    skill_id: str
    trust_level: int = 3
    blocked: bool = False
    override_history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "trust_level": self.trust_level,
            "blocked": self.blocked,
            "override_history": self.override_history,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GateFile:
        return cls(
            skill_id=data.get("skill_id", ""),
            trust_level=data.get("trust_level", 3),
            blocked=data.get("blocked", False),
            override_history=data.get("override_history", []),
        )


class EmergencyOverride:
    """紧急降权管理器。

    Usage:
        eo = EmergencyOverride(telemetry=bridge, gate_dir=Path("~/.skillpool/gates"))
        event = eo.override(
            trigger="security_event",
            level="quarantine",
            target_skill="S05a",
            reason="SQL injection detected",
        )
        # 检查是否被降权
        is_blocked = eo.is_blocked("S05a")
        # 恢复
        eo.restore("S05a")
    """

    def __init__(
        self,
        telemetry: Optional[TelemetryBridge] = None,
        gate_dir: Optional[Path] = None,
    ):
        self.telemetry = telemetry
        self.gate_dir = gate_dir or get_data_dir() / "gates"
        self.gate_dir.mkdir(parents=True, exist_ok=True)
        self._overrides: dict[str, OverrideEvent] = {}  # skill_id → latest event

    def override(
        self,
        trigger: OverrideTrigger | str,
        level: OverrideLevel | str,
        target_skill: str,
        target_agent: str = "",
        reason: str = "",
        current_trust: int = 3,
        ttl_seconds: Optional[int] = None,
    ) -> OverrideEvent:
        """执行紧急降权。

        Args:
            trigger: 触发原因
            level: 降权级别
            target_skill: 目标 Skill ID
            target_agent: 目标 Agent 名称
            reason: 降权原因描述
            current_trust: 当前 trust_level
            ttl_seconds: 自动恢复时间（None = 需人工恢复）
        """
        trig = OverrideTrigger(trigger) if isinstance(trigger, str) else trigger
        lvl = OverrideLevel(level) if isinstance(level, str) else level

        # 计算新的 trust_level
        new_trust = self._compute_new_trust(current_trust, lvl)

        # 计算过期时间
        expires_at = None
        if ttl_seconds:
            from datetime import timedelta

            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()

        event = OverrideEvent(
            trigger=trig,
            level=lvl,
            target_skill=target_skill,
            target_agent=target_agent,
            original_trust=current_trust,
            new_trust=new_trust,
            reason=reason,
            expires_at=expires_at,
        )

        # 更新 gate file — 只有 KILL 设 blocked=True, QUARANTINE 只降 trust
        blocked = lvl == OverrideLevel.KILL
        self._update_gate_file(target_skill, new_trust, blocked, event)

        # 记录
        self._overrides[target_skill] = event

        # 发射遥测
        if self.telemetry:
            self.telemetry.emit(
                event_type="emergency_override",
                skill_id=target_skill,
                channel="hook",
                payload={
                    "trigger": str(trig),
                    "level": str(lvl),
                    "new_trust": new_trust,
                    "reason": reason,
                },
            )

        return event

    def is_blocked(self, skill_id: str) -> bool:
        """检查 Skill 是否被降权/禁止。"""
        gate = self._read_gate_file(skill_id)
        if gate:
            return gate.blocked or gate.trust_level == 0
        return False

    def get_trust_level(self, skill_id: str) -> int:
        """获取 Skill 当前 trust_level（可能已被降权）。"""
        gate = self._read_gate_file(skill_id)
        if gate:
            return gate.trust_level
        return 3  # 默认

    def restore(self, skill_id: str, trust_level: int = 3) -> bool:
        """恢复 Skill 的 trust_level。"""
        gate = self._read_gate_file(skill_id)
        if not gate:
            return False

        gate.trust_level = trust_level
        gate.blocked = False
        self._write_gate_file(gate)

        # 清除内存记录
        self._overrides.pop(skill_id, None)

        # 发射遥测
        if self.telemetry:
            self.telemetry.emit(
                event_type="override_restored",
                skill_id=skill_id,
                channel="hook",
                payload={"restored_trust": trust_level},
            )

        return True

    def check_expired(self) -> list[str]:
        """检查并自动恢复过期的降权。返回恢复的 skill_id 列表。"""
        now = datetime.now(timezone.utc)
        restored = []

        for skill_id, event in list(self._overrides.items()):
            if event.expires_at:
                expires = datetime.fromisoformat(event.expires_at)
                if now >= expires:
                    self.restore(skill_id, event.original_trust)
                    restored.append(skill_id)

        return restored

    def _compute_new_trust(self, current: int, level: OverrideLevel) -> int:
        """根据降权级别计算新的 trust_level。"""
        if level == OverrideLevel.WARN:
            return max(current - 1, 0)
        elif level == OverrideLevel.DEGRADE:
            return max(current - 2, 0)
        elif level == OverrideLevel.QUARANTINE:
            return 0
        elif level == OverrideLevel.KILL:
            return 0
        return current

    def _update_gate_file(self, skill_id: str, trust: int, blocked: bool, event: OverrideEvent) -> None:
        """更新 gate file。"""
        gate = self._read_gate_file(skill_id) or GateFile(skill_id=skill_id)
        gate.trust_level = trust
        gate.blocked = blocked
        gate.override_history.append(
            {
                "trigger": str(event.trigger),
                "level": str(event.level),
                "new_trust": event.new_trust,
                "reason": event.reason,
                "timestamp": event.timestamp,
            }
        )
        self._write_gate_file(gate)

    def _read_gate_file(self, skill_id: str) -> Optional[GateFile]:
        """读取 gate file。"""
        path = self.gate_dir / f"{skill_id}.json"
        if path.exists():
            try:
                return GateFile.from_dict(json.loads(path.read_text()))
            except Exception as e:
                logger.warning("Failed to read gate file for %s: %s", skill_id, e)
        return None

    def _write_gate_file(self, gate: GateFile) -> None:
        """写入 gate file。"""
        path = self.gate_dir / f"{gate.skill_id}.json"
        path.write_text(json.dumps(gate.to_dict(), indent=2, ensure_ascii=False))
