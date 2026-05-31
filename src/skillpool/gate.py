"""
GateManager — Skill 执行门禁 + ComplexityAssessor。

GateManager 根据 ComplexityAssessor 的评估结果决定是否放行 Skill 执行。
复杂度评估维度：context_size, dependency_depth, trust_requirement, veto_risk
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional

from skillpool.profile import AgentCapabilityProfile
from skillpool.telemetry import TelemetryBridge


class GateDecision(StrEnum):
    ALLOW = "allow"
    GUARD = "guard"       # 允许但需要额外监督
    DENY = "deny"         # 拒绝执行
    ESCALATE = "escalate" # 需要人工审批


@dataclass
class ComplexityScore:
    """复杂度评分结果。"""
    total: float = 0.0
    context_size: float = 0.0
    dependency_depth: float = 0.0
    trust_requirement: float = 0.0
    veto_risk: float = 0.0

    @property
    def level(self) -> str:
        """复杂度等级: low / medium / high / critical"""
        if self.total < 0.3:
            return "low"
        elif self.total < 0.6:
            return "medium"
        elif self.total < 0.8:
            return "high"
        return "critical"


class ComplexityAssessor:
    """评估 Skill 执行复杂度。

    4 个维度，每维度 0-1 分，加权汇总：
    - context_size (w=0.25): CSDF checklist 条目数 / 20
    - dependency_depth (w=0.25): skill_graph 依赖深度 / 5
    - trust_requirement (w=0.25): min_trust_level / 3
    - veto_risk (w=0.25): 有 veto_rule → 0.8, 否则 0.1
    """

    def __init__(
        self,
        weights: Optional[dict[str, float]] = None,
    ):
        self.weights = weights or {
            "context_size": 0.25,
            "dependency_depth": 0.25,
            "trust_requirement": 0.25,
            "veto_risk": 0.25,
        }

    def assess(self, csdf: dict) -> ComplexityScore:
        """评估 CSDF 的执行复杂度。"""
        ctx = min(len(csdf.get("checklist", [])) / 20.0, 1.0)
        deps = csdf.get("dependency_depth", 0)
        dep_score = min(deps / 5.0, 1.0)
        trust = min(csdf.get("min_trust_level", 0) / 3.0, 1.0)
        veto = 0.8 if csdf.get("veto_rule") else 0.1

        total = (
            ctx * self.weights["context_size"]
            + dep_score * self.weights["dependency_depth"]
            + trust * self.weights["trust_requirement"]
            + veto * self.weights["veto_risk"]
        )

        return ComplexityScore(
            total=total,
            context_size=ctx,
            dependency_depth=dep_score,
            trust_requirement=trust,
            veto_risk=veto,
        )


@dataclass
class GateResult:
    """门禁决策结果。"""
    decision: GateDecision
    reason: str = ""
    complexity: Optional[ComplexityScore] = None
    conditions: list[str] = field(default_factory=list)


class GateManager:
    """Skill 执行门禁管理器。

    根据复杂度和能力匹配做执行决策：
    - low complexity + capability match → ALLOW
    - medium complexity → GUARD（允许但记录遥测）
    - high complexity → ESCALATE
    - critical / capability mismatch → DENY
    - veto_risk > 0.5 → ESCALATE

    Usage:
        gm = GateManager(profile=CLAUDE_CODE_PROFILE, telemetry=bridge)
        result = gm.check(csdf)
        if result.decision == GateDecision.ALLOW:
            # 执行 skill
    """

    def __init__(
        self,
        profile: AgentCapabilityProfile,
        telemetry: Optional[TelemetryBridge] = None,
        assessor: Optional[ComplexityAssessor] = None,
    ):
        self.profile = profile
        self.telemetry = telemetry
        self.assessor = assessor or ComplexityAssessor()

    def check(self, csdf: dict) -> GateResult:
        """对 CSDF 做门禁检查，返回决策。"""
        # 1. 能力匹配
        can_exec, reason = self.profile.can_execute({
            "required_capabilities": csdf.get("required_agent_capabilities", set()),
            "min_trust_level": csdf.get("min_trust_level", 0),
            "paradigm": csdf.get("paradigm"),
        })

        if not can_exec:
            result = GateResult(
                decision=GateDecision.DENY,
                reason=f"capability mismatch: {reason}",
            )
            self._emit_gate_event(csdf, result)
            return result

        # 2. 复杂度评估
        complexity = self.assessor.assess(csdf)

        # 3. 决策逻辑
        if complexity.veto_risk > 0.5 and complexity.total >= 0.6:
            decision = GateDecision.ESCALATE
            reason = f"veto risk + high complexity ({complexity.level})"
            conditions = ["require_human_approval"]
        elif complexity.level == "critical":
            decision = GateDecision.DENY
            reason = f"critical complexity ({complexity.total:.2f})"
            conditions = []
        elif complexity.level == "high":
            decision = GateDecision.ESCALATE
            reason = f"high complexity ({complexity.total:.2f})"
            conditions = ["require_human_approval"]
        elif complexity.level == "medium":
            decision = GateDecision.GUARD
            reason = f"medium complexity ({complexity.total:.2f})"
            conditions = ["log_telemetry", "monitor_execution"]
        else:
            decision = GateDecision.ALLOW
            reason = f"low complexity ({complexity.total:.2f})"
            conditions = []

        result = GateResult(
            decision=decision,
            reason=reason,
            complexity=complexity,
            conditions=conditions,
        )

        self._emit_gate_event(csdf, result)
        return result

    def _emit_gate_event(self, csdf: dict, result: GateResult) -> None:
        """发射门禁遥测事件。"""
        if self.telemetry:
            self.telemetry.emit(
                event_type="gate_check",
                skill_id=csdf.get("id", "unknown"),
                channel="hook",
                payload={
                    "decision": str(result.decision),
                    "reason": result.reason,
                    "complexity": result.complexity.level if result.complexity else None,
                },
            )
