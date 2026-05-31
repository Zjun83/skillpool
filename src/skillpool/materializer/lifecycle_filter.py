"""LifecycleFilter — 根据 Skill 生命周期状态过滤 markdown 内容。

根据 CSDF 中的 lifecycle_state 字段，对 markdown 内容添加状态标记、
降级警告或截断处理。
"""
from __future__ import annotations

from skillpool.lifecycle import SkillLifecycleState, parse_state


class LifecycleFilter:
    """根据 Skill 生命周期状态过滤内容。

    Args:
        strict: True 时，REJECTED 清空内容，ARCHIVED 截断内容。
    """

    def __init__(self, strict: bool = True):
        self.strict = strict

    def filter(self, markdown: str, csdf: dict) -> str:
        """过滤 markdown 内容。

        Args:
            markdown: 原始 markdown 文本。
            csdf: CSDF 字典，需包含 lifecycle_state 字段。

        Returns:
            过滤后的 markdown 文本。
        """
        state = self._resolve_state(csdf)
        return self._apply_filter(markdown, state)

    def _resolve_state(self, csdf: dict) -> SkillLifecycleState:
        """从 CSDF 解析生命周期状态，默认 ACTIVE。"""
        raw = csdf.get("lifecycle_state")
        if raw is None:
            return SkillLifecycleState.ACTIVE
        state = parse_state(str(raw))
        if state is None:
            return SkillLifecycleState.ACTIVE
        return state

    def _apply_filter(self, markdown: str, state: SkillLifecycleState) -> str:
        """根据状态应用过滤规则。"""
        if state == SkillLifecycleState.DRAFT:
            return self._prepend_warning(markdown, "[DRAFT] 开发中")
        elif state == SkillLifecycleState.PROPOSED:
            return self._prepend_warning(markdown, "[DRAFT] 开发中")
        elif state == SkillLifecycleState.UNDER_REVIEW:
            return self._prepend_warning(markdown, "[REVIEW] 审核中")
        elif state == SkillLifecycleState.APPROVED:
            return markdown
        elif state == SkillLifecycleState.ACTIVE:
            return markdown
        elif state == SkillLifecycleState.REJECTED:
            return self._handle_rejected(markdown)
        elif state == SkillLifecycleState.DEPRECATED:
            return self._handle_deprecated(markdown)
        elif state == SkillLifecycleState.ARCHIVED:
            return self._handle_archived(markdown)
        elif state == SkillLifecycleState.REMOVED:
            return ""
        return markdown

    def _prepend_warning(self, markdown: str, warning: str) -> str:
        """在 markdown 顶部添加警告。"""
        return f"> ⚠️ {warning}\n\n{markdown}"

    def _handle_rejected(self, markdown: str) -> str:
        """处理 REJECTED 状态。"""
        warning = "[REJECTED] 已否决"
        if self.strict:
            return f"> ⚠️ {warning}\n"
        return self._prepend_warning(markdown, warning)

    def _handle_deprecated(self, markdown: str) -> str:
        """处理 DEPRECATED 状态，添加替代建议。"""
        replacement = "请查看替代方案或联系维护者"
        warning = f"[DEPRECATED] 已弃用 — {replacement}"
        return self._prepend_warning(markdown, warning)

    def _handle_archived(self, markdown: str) -> str:
        """处理 ARCHIVED 状态。"""
        warning = "[ARCHIVED] 已归档"
        if self.strict:
            # 截断：只保留前 200 字符
            truncated = markdown[:200]
            if len(markdown) > 200:
                truncated += "\n\n... (内容已截断)"
            return f"> ⚠️ {warning}\n\n{truncated}"
        return self._prepend_warning(markdown, warning)
