"""BudgetCropper — 按 token 预算裁剪 markdown 内容。

策略优先级（从低到高删除）：
1. Version History（最低优先级）
2. Checklist 的 medium 项
3. Checklist 的 low 项
4. Description（截断）
5. Header + Dimension + Weight + Veto + Schema（最高优先级，保留）
"""

from __future__ import annotations

import re


class BudgetCropper:
    """按 token 预算裁剪 markdown 内容。

    Args:
        max_tokens: 最大 token 数限制，默认 4096。
    """

    def __init__(self, max_tokens: int = 4096):
        self.max_tokens = max_tokens

    def crop(self, markdown: str) -> str:
        """裁剪 markdown 到 max_tokens 以内。"""
        if self.estimate_tokens(markdown) <= self.max_tokens:
            return markdown

        # 策略 1: 删除 Version History
        markdown = self._remove_section(markdown, "## Version History")
        if self.estimate_tokens(markdown) <= self.max_tokens:
            return markdown

        # 策略 2: 删除 Checklist 的 medium 项
        markdown = self._remove_checklist_items(markdown, "medium")
        if self.estimate_tokens(markdown) <= self.max_tokens:
            return markdown

        # 策略 3: 删除 Checklist 的 low 项
        markdown = self._remove_checklist_items(markdown, "low")
        if self.estimate_tokens(markdown) <= self.max_tokens:
            return markdown

        # 策略 4: 截断 Description
        markdown = self._truncate_description(markdown)
        if self.estimate_tokens(markdown) <= self.max_tokens:
            return markdown

        # 最后手段：硬截断
        return self._hard_truncate(markdown)

    def estimate_tokens(self, text: str) -> int:
        """估算 token 数。简单实现：len(text) // 4。"""
        return len(text) // 4

    def _remove_section(self, markdown: str, header_prefix: str) -> str:
        """删除指定 section（标题匹配：检查标题行是否包含 header_prefix）。"""
        lines = markdown.split("\n")
        result = []
        in_section = False
        section_level = 0

        for line in lines:
            header_match = re.match(r"^(#{1,6})\s+", line)
            if header_match:
                current_level = len(header_match.group(1))
                if in_section:
                    if current_level <= section_level:
                        in_section = False
                    else:
                        continue
                # Match section by checking if header text contains the prefix
                if header_prefix.lower() in line.lower():
                    in_section = True
                    section_level = current_level
                    continue
            if in_section:
                continue
            result.append(line)

        return "\n".join(result)

    def _remove_checklist_items(self, markdown: str, priority: str) -> str:
        """删除 Checklist 中指定优先级的项。"""
        lines = markdown.split("\n")
        result = []
        in_checklist = False
        checklist_level = 0

        for line in lines:
            header_match = re.match(r"^(#{1,6})\s+", line)
            if header_match:
                current_level = len(header_match.group(1))
                if in_checklist and current_level <= checklist_level:
                    in_checklist = False
                if "checklist" in line.lower() or "检查项" in line:
                    in_checklist = True
                    checklist_level = current_level
                result.append(line)
                continue

            if in_checklist:
                if re.match(r"^\s*[-*]\s+", line):
                    # Match [medium], [low], (medium), (low) formats
                    if re.search(rf"[\[(]{priority}[\])]", line, re.IGNORECASE):
                        continue
                    # Match "priority: medium" format
                    if re.search(rf"priority:\s*{priority}", line, re.IGNORECASE):
                        continue

            result.append(line)

        return "\n".join(result)

    def _truncate_description(self, markdown: str) -> str:
        """截断 Description 部分。"""
        lines = markdown.split("\n")
        result = []
        in_description = False
        description_level = 0
        description_lines = []

        for line in lines:
            header_match = re.match(r"^(#{1,6})\s+", line)
            if header_match:
                current_level = len(header_match.group(1))
                if in_description and current_level <= description_level:
                    truncated = self._truncate_lines(description_lines, 200)
                    result.extend(truncated)
                    in_description = False
                    description_lines = []
                if "Description" in line or "概述" in line or "简介" in line:
                    in_description = True
                    description_level = current_level
                    result.append(line)
                    continue
                result.append(line)
                continue

            if in_description:
                description_lines.append(line)
            else:
                result.append(line)

        if in_description and description_lines:
            truncated = self._truncate_lines(description_lines, 200)
            result.extend(truncated)

        return "\n".join(result)

    def _truncate_lines(self, lines: list, max_chars: int) -> list:
        """截断行列表到指定字符数。"""
        result = []
        total = 0
        for line in lines:
            if total + len(line) > max_chars:
                remaining = max_chars - total
                if remaining > 20:
                    result.append(line[:remaining] + "...")
                break
            result.append(line)
            total += len(line)
        return result

    def _hard_truncate(self, markdown: str) -> str:
        """硬截断到 max_tokens * 4 字符。"""
        max_chars = self.max_tokens * 4
        if len(markdown) <= max_chars:
            return markdown
        truncated = markdown[:max_chars]
        last_period = truncated.rfind(".")
        last_newline = truncated.rfind("\n")
        cut_point = max(last_period, last_newline)
        if cut_point > max_chars * 0.8:
            return truncated[: cut_point + 1] + "\n\n... (truncated)"
        return truncated + "\n\n... (truncated)"
