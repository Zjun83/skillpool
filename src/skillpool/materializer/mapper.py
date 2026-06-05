"""
CSDF Mapper — 14 条 CSDF→SKILL.md 映射规则引擎

规则列表:
  R01: id → skill_id
  R02: name → title
  R03: version → version 标注
  R04: dimension → dimension 标签
  R05: weight → weight 标注
  R06: veto_rule → veto 警告块
  R07: description → 概述段落
  R08: checklist → 检查项表格
  R09: input_schema → 输入规范块
  R10: output_schema → 输出规范块
  R11: version_history → 变更日志
  R12: required_agent_capabilities → 前置条件块
  R13: min_trust_level → 信任等级要求
  R14: paradigm → 范式标签
"""

from __future__ import annotations

from typing import Callable


class CSDFMapper:
    """CSDF → Markdown 映射引擎，应用 14 条规则。"""

    def __init__(self):
        self._rules: list[Callable] = [
            self._r01_skill_id,
            self._r02_title,
            self._r03_version,
            self._r04_dimension,
            self._r05_weight,
            self._r06_veto,
            self._r07_description,
            self._r08_checklist,
            self._r09_input_schema,
            self._r10_output_schema,
            self._r11_version_history,
            self._r12_capabilities,
            self._r13_trust_level,
            self._r14_paradigm,
        ]

    def map(self, csdf: dict) -> str:
        """应用全部 14 条映射规则，生成 SKILL.md markdown。"""
        sections = []
        for rule in self._rules:
            section = rule(csdf)
            if section:
                sections.append(section)
        return "\n\n".join(sections) + "\n"

    # ---- 14 条规则实现 ----

    def _r01_skill_id(self, csdf: dict) -> str:
        sid = csdf.get("id", "")
        return f"# {sid}" if sid else ""

    def _r02_title(self, csdf: dict) -> str:
        name = csdf.get("name", "")
        return f"## {name}" if name else ""

    def _r03_version(self, csdf: dict) -> str:
        ver = csdf.get("version", "")
        return f"**Version**: {ver}" if ver else ""

    def _r04_dimension(self, csdf: dict) -> str:
        dim = csdf.get("dimension", "")
        return f"**Dimension**: {dim}" if dim else ""

    def _r05_weight(self, csdf: dict) -> str:
        w = csdf.get("weight")
        if w is not None:
            return f"**Weight**: {w}"
        return ""

    def _r06_veto(self, csdf: dict) -> str:
        veto = csdf.get("veto_rule")
        if veto:
            return f"> ⚠️ **VETO**: {veto}"
        return ""

    def _r07_description(self, csdf: dict) -> str:
        desc = csdf.get("description", "").strip()
        return desc if desc else ""

    def _r08_checklist(self, csdf: dict) -> str:
        items = csdf.get("checklist", [])
        if not items:
            return ""
        lines = ["### Checklist", ""]
        for item in items:
            # Support both {id, description, severity} and {item, priority} formats
            desc = item.get("description") or item.get("item", "")
            iid = item.get("id", "")
            sev = item.get("severity") or item.get("priority", "")
            if iid:
                lines.append(f"- [{iid}] {desc} ({sev})")
            else:
                lines.append(f"- {desc} [{sev}]")
        return "\n".join(lines)

    def _r09_input_schema(self, csdf: dict) -> str:
        schema = csdf.get("input_schema", {})
        if not schema:
            return ""
        return self._format_schema("Input", schema)

    def _r10_output_schema(self, csdf: dict) -> str:
        schema = csdf.get("output_schema", {})
        if not schema:
            return ""
        return self._format_schema("Output", schema)

    def _r11_version_history(self, csdf: dict) -> str:
        history = csdf.get("version_history", [])
        if not history:
            return ""
        lines = ["### Version History", ""]
        for entry in history:
            ver = entry.get("version", "?")
            date = entry.get("date", "?")
            changes = entry.get("changes", [])
            lines.append(f"**{ver}** ({date})")
            for c in changes:
                if isinstance(c, str):
                    lines.append(f"  - {c}")
                else:
                    lines.append(f"  - {c}")
        return "\n".join(lines)

    def _r12_capabilities(self, csdf: dict) -> str:
        caps = csdf.get("required_agent_capabilities", set())
        if isinstance(caps, (list, tuple)):
            caps = set(caps)
        if not caps:
            return ""
        return f"**Required Capabilities**: {', '.join(sorted(caps))}"

    def _r13_trust_level(self, csdf: dict) -> str:
        tl = csdf.get("min_trust_level", 0)
        if tl > 0:
            return f"**Min Trust Level**: {tl}"
        return ""

    def _r14_paradigm(self, csdf: dict) -> str:
        p = csdf.get("paradigm")
        if p:
            return f"**Paradigm**: {p}"
        return ""

    # ---- 辅助 ----

    def _format_schema(self, label: str, schema: dict) -> str:
        """将 input/output schema 格式化为 markdown。"""
        lines = [f"### {label} Schema", ""]
        # Support both {required/optional} and JSON Schema {type/properties} formats
        if "properties" in schema:
            props = schema.get("properties", {})
            for key, val in props.items():
                typ = val.get("type", "?")
                desc = val.get("description", "")
                lines.append(f"- `{key}` ({typ}): {desc}")
        else:
            for section in ["required", "optional"]:
                items = schema.get(section, {})
                if items:
                    lines.append(f"**{section.title()}:**")
                    if isinstance(items, dict):
                        for key, desc in items.items():
                            lines.append(f"- `{key}`: {desc}")
                    elif isinstance(items, list):
                        for item in items:
                            lines.append(f"- {item}")
        return "\n".join(lines)
