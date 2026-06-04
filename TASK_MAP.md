---
title: "任务执行地图"
version: "1.0"
generated_by: "scaffold-docs v1.0.0"
generated_at: "2026-05-30T20:09:17.76455600:00"
last_verified: "2026-05-30T20:09:17.76455600:00"
diataxis_type: "how-to"
audience: "dev+pm"
status: "active"
layout: "single"
auto_refresh: "false"
---

# 任务执行地图 (TASK_MAP)

## 总体完成度

| 类别 | 总数 | 已完成 | 进行中 | 待开始 |
|------|------|--------|--------|--------|
| — | — | — | — | — |

<!-- MANUAL START -->
> 填入实际任务完成度数据
<!-- MANUAL END -->

## P0 阻断项（立即处理）

| # | 任务 | 负责人 | 状态 | 阻塞原因 |
|---|------|--------|------|---------|
| — | — | — | — | — |

## P1 重要项（尽快处理）

| # | 任务 | 负责人 | 状态 | 截止 |
|---|------|--------|------|------|
| — | — | — | — | — |

<!-- MANUAL START -->
> 从 TASK_LIST_FULL.md / CHECKPOINT_CHECKLIST.md / PENDING_TASKS.md 合并数据
<!-- MANUAL END -->

## P2 改进项（计划排期）

| # | 任务 | 负责人 | 状态 |
|---|------|--------|------|
| — | — | — | — |

## 🔍 需确认项

| # | 问题 | 影响范围 | 验证方法 |
|---|------|---------|---------|
| — | — | — | — |

## BUG Collector 噪声文档处理状态

| 文件 | 处理方式 | 当前状态 |
|------|---------|---------|
| BUG_TRACKER.md | AGENTS.md铁律#4禁止读取 | noise(39个P2 ruff格式问题) |
| CHECKPOINT.md | AGENTS.md铁律#4禁止读取 | noise |
| collector_errors.jsonl | .gitignore排除，已在.gitignore | noise(已截断) |
| BUG Collector触发点 | 改为opt-in | conftest需--with-collector, pre-commit stages:[manual] |

## 如何更新此文档

1. 任务状态变更时手动更新对应行
2. 版本号手动递增 MINOR
3. `last_verified` 日期手动更新