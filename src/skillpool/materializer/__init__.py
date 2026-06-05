"""
Materializer — CSDF→SKILL.md 实体化引擎

将 CSDF (Canonical Skill Definition Format) YAML 定义转化为
SKILL.md 运行时格式，供 Agent 在协作中消费。

核心流程:
  CSDF YAML → Mapper(14条规则) → Lifecycle Filter → Budget Cropper → SKILL.md
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from skillpool.materializer.models import (
    MaterializationResult,
    MaterializedSkill,
    CSDFDocument as CSDFDocument,
)
from skillpool.materializer.mapper import CSDFMapper
from skillpool.materializer.lifecycle_filter import LifecycleFilter
from skillpool.materializer.budget_cropper import BudgetCropper
from skillpool.profile import AgentCapabilityProfile


class Materializer:
    """CSDF → SKILL.md 实体化引擎主类。

    Usage:
        mat = Materializer(profile=CLAUDE_CODE_PROFILE)
        result = mat.materialize(csdf_path=Path("S05a-security-transport.yaml"))
        print(result.skill.markdown)
    """

    def __init__(
        self,
        profile: AgentCapabilityProfile,
        context_budget: int = 4096,
        strict_lifecycle: bool = True,
    ):
        self.profile = profile
        self.context_budget = context_budget
        self.mapper = CSDFMapper()
        self.lifecycle_filter = LifecycleFilter(strict=strict_lifecycle)
        self.budget_cropper = BudgetCropper(max_tokens=context_budget)

    def materialize(
        self,
        csdf_path: Optional[Path] = None,
        csdf_dict: Optional[dict] = None,
    ) -> MaterializationResult:
        """执行 CSDF → SKILL.md 实体化。

        Args:
            csdf_path: CSDF YAML 文件路径
            csdf_dict: CSDF 字典（与 csdf_path 二选一）

        Returns:
            MaterializationResult 包含结果状态和实体化后的 SKILL.md
        """
        # 1. 加载 CSDF
        csdf = self._load_csdf(csdf_path, csdf_dict)

        # 2. 能力匹配检查
        can_exec, reason = self.profile.can_execute({
            "required_capabilities": csdf.get("required_agent_capabilities", set()),
            "min_trust_level": csdf.get("min_trust_level", 0),
            "paradigm": csdf.get("paradigm"),
        })
        if not can_exec:
            return MaterializationResult(
                status="rejected",
                skill=None,
                errors=[f"capability mismatch: {reason}"],
            )

        # 3. 映射规则 (14 条)
        skill_md = self.mapper.map(csdf)

        # 4. Lifecycle 过滤
        skill_md = self.lifecycle_filter.filter(skill_md, csdf)

        # 5. Budget 裁剪
        skill_md = self.budget_cropper.crop(skill_md)

        # 6. 组装结果
        skill = MaterializedSkill(
            id=csdf.get("id", "unknown"),
            name=csdf.get("name", "unknown"),
            version=csdf.get("version", "0.0.0"),
            dimension=csdf.get("dimension", ""),
            markdown=skill_md,
            token_count=self.budget_cropper.estimate_tokens(skill_md),
        )

        return MaterializationResult(
            status="success",
            skill=skill,
            errors=[],
        )

    def materialize_batch(
        self,
        csdf_paths: list[Path],
    ) -> list[MaterializationResult]:
        """批量实体化多个 CSDF 文件。"""
        return [self.materialize(csdf_path=p) for p in csdf_paths]

    def _load_csdf(
        self,
        csdf_path: Optional[Path],
        csdf_dict: Optional[dict],
    ) -> dict:
        """加载 CSDF 文档，优先用 dict，否则从文件读取。"""
        if csdf_dict is not None:
            return csdf_dict
        if csdf_path is not None:
            import yaml
            return yaml.safe_load(csdf_path.read_text())
        raise ValueError("必须提供 csdf_path 或 csdf_dict")
