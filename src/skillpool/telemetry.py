"""
TelemetryBridge — 反向反馈通道，将运行时信号传回 SkillPool。

3 个通道:
  1. hook  — Claude Code / Codex hook 事件（PreToolUse, PostToolUse, Stop 等）
  2. mcp   — MCP tool call（由 mcp_server.py 暴露 telemetry_report 工具）
  3. log_file — 文件轮询（兼容无 hook/MCP 的环境）
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Optional, Callable

from pydantic import BaseModel, Field


class TelemetryChannel(StrEnum):
    HOOK = "hook"
    MCP = "mcp"
    LOG_FILE = "log_file"


class TelemetryEvent(BaseModel):
    """单条遥测事件。"""
    event_type: str
    skill_id: str
    channel: TelemetryChannel = TelemetryChannel.LOG_FILE
    payload: dict = {}
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trace_id: str = ""


class TelemetryBridge:
    """反向反馈通道 — 从运行时向 SkillPool 传递遥测信号。

    Usage:
        bridge = TelemetryBridge(log_dir=Path("~/.skillpool/telemetry"))
        bridge.emit("skill_used", skill_id="S05a", channel="hook")
        bridge.emit("skill_error", skill_id="S10", channel="mcp", payload={"error": "timeout"})
    """

    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir or Path.home() / ".skillpool" / "telemetry"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._hooks: list[Callable] = []

    def emit(
        self,
        event_type: str,
        skill_id: str,
        channel: TelemetryChannel | str = TelemetryChannel.LOG_FILE,
        payload: Optional[dict] = None,
        trace_id: str = "",
    ) -> TelemetryEvent:
        """发射一条遥测事件。同时写入 log_file 并调用已注册的 hook。"""
        ch = TelemetryChannel(channel) if isinstance(channel, str) else channel
        event = TelemetryEvent(
            event_type=event_type,
            skill_id=skill_id,
            channel=ch,
            payload=payload or {},
            trace_id=trace_id,
        )

        # 始终写入 log_file
        self._write_to_log(event)

        # 调用注册的 hook
        for hook_fn in self._hooks:
            try:
                hook_fn(event)
            except Exception:
                pass  # hook 失败不阻断主流程

        return event

    def register_hook(self, fn: Callable) -> None:
        """注册一个 hook 回调，每次 emit 时调用。"""
        self._hooks.append(fn)

    def read_events(
        self,
        skill_id: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[float] = None,
    ) -> list[TelemetryEvent]:
        """从 log_file 读取历史事件。"""
        events = []
        log_file = self.log_dir / f"telemetry-{datetime.now().strftime('%Y%m%d')}.jsonl"
        if not log_file.exists():
            return events

        for line in log_file.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                event = TelemetryEvent(**data)
                if skill_id and event.skill_id != skill_id:
                    continue
                if event_type and event.event_type != event_type:
                    continue
                if since:
                    evt_ts = datetime.fromisoformat(event.timestamp).timestamp()
                    if evt_ts < since:
                        continue
                events.append(event)
            except (json.JSONDecodeError, Exception):
                continue

        return events

    def _write_to_log(self, event: TelemetryEvent) -> None:
        """追加写入当日 JSONL 文件。"""
        log_file = self.log_dir / f"telemetry-{datetime.now().strftime('%Y%m%d')}.jsonl"
        with open(log_file, "a") as f:
            f.write(event.model_dump_json() + "\n")
