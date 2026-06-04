---
title: "代码地图"
version: "1.0"
generated_by: "scaffold-docs v1.0.0"
generated_at: "2026-05-30T20:09:17.76455600:00"
last_verified: "2026-05-30T20:09:17.76455600:00"
diataxis_type: "reference"
audience: "dev"
status: "active"
layout: "single"
auto_refresh: "true"
---

# 代码地图 (CODE_MAP)

> 使用说明: 本文件由 `scripts/gen-code-map.sh` 自动生成基础表格，人工补充模糊区。
> 生成命令: `scripts/gen-code-map.sh src/ docs/`

## 模块索引表

| 模块 | 文件 | 行数 | 职责 | 关键符号 | 依赖 |
|------|------|------|------|---------|------|
| — | — | — | — | — | — |

<!-- MANUAL START -->
> 运行 `scripts/gen-code-map.sh src/ docs/` 自动填充模块索引表
> 人工补充：关键符号、依赖关系、职责说明
<!-- MANUAL END -->

## 跨模块依赖图

<!-- MANUAL START -->
> 手动绘制或用工具生成依赖图。建议 Mermaid graph TD 格式。
<!-- MANUAL END -->

## 基础设施脚本索引

| 脚本 | 路径 | 功能 |
|------|------|------|
| health-check | scripts/health-check.sh | 环境健康检查 |
| gen-code-map | scripts/gen-code-map.sh | 代码地图生成（rg+jq / Python fallback） |
| check-doc-staleness | scripts/check-doc-staleness.sh | 文档过时检测（三层） |
| refresh-all-docs | scripts/refresh-all-docs.sh | 全量文档刷新 |
| validate-links | scripts/validate-links.sh | 内部链接验证 |

## 已知模糊区

| 区域 | 说明 | 置信度 |
|------|------|--------|
| — | — | — |

<!-- MANUAL START -->
> 标注不确定的模块职责、缺失的依赖关系等
<!-- MANUAL END -->