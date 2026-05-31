# ADR-001: SkillPool 双 Agent 集成决策记录

> **日期**: 2026-05-29
> **状态**: 执行中
> **参与者**: User + Claude Code

## 背景

SkillPool V4.1 已部署完成（95% 覆盖率, 403 tests），但 registry 为空（0 skills）。Codex (51 custom skills) 和 OpenClaw (60 skills) 各自维护独立的 SKILL 体系，需要统一迁移到 SkillPool 实现：

- SKILL 单一来源（SkillPool registry）
- Gate 准入控制（质量分 ≥ 阈值）
- CSDF 标准化格式
- CLI 管"写"（注册/管理），MCP 管"读"（运行时查询）

## 反馈评估与取舍

### 采纳（5 条）

| # | 反馈 | 采纳理由 | 实施方式 |
|---|------|---------|---------|
| 1 | Phase 1 细分：先 registry 健康检查再批量注册 | registry 为空原因未确认，盲目写入有风险 | Phase 1A 硬重置+验证 → Phase 1B 批量注册 |
| 2 | CI/CD 门禁自动化：cron 巡检 | Gate 不应是一次性检查 | 每日 cron `skillpool-gate-cron` + JSON 报告 |
| 3 | Skill Evolution 闭环：evolution.json 分离 | 直接修改 SKILL.md 不可逆 | Gate 失败 → evolution.json(待验证) → 验证通过后合并+升版本 |
| 6 | GNU Parallel 替代 for 循环 | 错误隔离 + 并行加速 | `parallel -j 4`，失败记入 `/tmp/failed-skills.log` |
| 7 | 统一 triggers 字段 | 跨系统 SKILL 需标准化触发条件 | CSDF 转换时统一添加 triggers (keywords/context_patterns/priority) |

### 部分采纳（2 条）

| # | 反馈 | 采纳部分 | 不采纳部分 | 不采纳理由 |
|---|------|---------|-----------|-----------|
| 5 | 安全与权限管控 | 工具白名单 + 审计日志 | "安全技能库" | 当前无需求场景，投机性功能 (KP 0.2) |
| 8 | 文档引用增强 | 有依赖的 SKILL 添加 references | 无差别全添加 | 不为不可能场景添加字段 (KP 0.2) |

### 不采纳（1 条）

| # | 反馈 | 不采纳理由 |
|---|------|-----------|
| 4 | MCP 外部技能桥 + 主动发布索引 | 当前任务是双 Agent 集成，非构建公开技能市场。skillforge-mcp 标准化、让"其他 Agent 发现"是第二阶段产品方向，属投机性功能 (KP 0.2)。架构上预留 SkillBridgeMCP 类即可 |

## 执行方案

### Phase 1A: Registry 硬重置 + CSDF 标准化
- 备份 `~/.skillpool/` → `~/.skillpool.bak.YYYYMMDD/`
- 重建目录：skills/ logs/ materialization_state/ evolution/ audit/
- 验证 gate.json / registry.jsonl 可写
- CSDF 标准化：统一 triggers + references 字段

### Phase 1B: 批量注册 + 去重
- GNU Parallel `-j 4` 批量注册
- `--force` 覆盖 + name+version 去重
- 错误隔离：失败记入 `/tmp/failed-skills.log`

### Phase 2: Gate + Evolution + Cron
- `skillpool gate --all --format=json` → 报告
- 失败 SKILL → `evolution.json`（status: pending）
- Cron: 每日 06:00 Gate 巡检 → `~/.skillpool/logs/gate-report-*.json`

### Phase 3: Codex 接入
- Symlink `~/.codex/skills/<name>/` → `~/.skillpool/skills/<name>/`
- 确认 MCP Server 可用
- 审计日志：`~/.skillpool/logs/audit.jsonl`

### Phase 4: OpenClaw 接入 + 安全管控
- `~/.openclaw/openclaw.json` 添加 SkillPool MCP + 工具白名单
- Symlink SKILL 路径
- 审计日志开启

### Phase 5: 闭环验证
- `skillpool list-skills` 全量可发现性
- Codex + OpenClaw MCP 调用验证
- Gate 验证 + 端到端 SKILL 执行

## 关键参数

| 参数 | 值 | 来源 |
|------|-----|------|
| Gate min_quality_score | 0.6 | 方案设计 |
| Gate min_dimension_score | 0.5 | 方案设计 |
| Gate required_dimensions | completeness, accuracy | 方案设计 |
| Cron schedule | 每日 06:00 | 反馈#2 |
| Parallel jobs | 4 | 反馈#6 |
| Evolution status flow | pending → validated → merged | 反馈#3 |
| 12-dim-review VETO 阈值 | D3≥7.0, D5≥7.0, D7≥7.5, D11≥6.0 | CLAUDE.md Section 8.3 |

## 目录结构

```
/root/skillpool/
├── docs/
│   ├── decisions/
│   │   └── ADR-001-skillpool-integration.md    ← 本文件
│   ├── operations/
│   │   └── (Phase 执行日志归档)
│   └── integration/
│       ├── codex-integration.md                 ← Codex 接入配置
│       └── openclaw-integration.md              ← OpenClaw 接入配置
├── .skillpool/
│   ├── skills/                                  ← SKILL 存储（单一来源）
│   ├── logs/                                    ← 审计 + Gate 报告
│   ├── materialization_state/                   ← 物化状态
│   ├── evolution/                               ← Evolution 提案
│   ├── audit/                                   ← 审计记录
│   ├── registry.jsonl                           ← SKILL 注册表
│   └── gate.json                                ← Gate 配置
└── src/skillpool/                               ← 源码
```
