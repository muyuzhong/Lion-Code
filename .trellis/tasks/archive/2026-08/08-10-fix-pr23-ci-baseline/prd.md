# 修复 PR 23 CI 基线门禁

## Goal

诊断并修复 PR #23 的 Quality gates (baseline) (3.12.13) GitHub Actions 失败，保持现有状态所有权迁移行为不变。

## Requirements

- 只修复 GitHub Actions 中 Radon/Vulture 既有指纹因源码行号漂移产生的误报。
- 保持 Radon 高复杂度项数量 12、Vulture 高置信候选数量 5 不增加。
- 不修改状态所有权产品代码、测试行为、覆盖率阈值或质量门禁实现。
- 基线只更新 CI 日志确认发生漂移的既有条目，不扩大 allowlist。

## Acceptance Criteria

- [x] 本地 Radon 基线检查通过，数量仍为 12。
- [x] 本地 Vulture 基线检查通过，数量仍为 5。
- [x] 任务范围 `git diff --check` 通过。
- [x] 中文提交并推送到 PR #23 的当前分支。
- [x] GitHub Actions 的 `Quality gates (baseline) (3.12.13)` 重新运行并通过。

## Notes

- 失败日志：Radon 12/12、Vulture 5/5，但 `__main__.py`、`core/loop.py`、`providers/stream.py` 的旧指纹行号变化。
- 测试 628 passed、7 skipped、20 subtests；branch coverage 58.88% >= 58.33%，changed-lines coverage 95.98% >= 80%。
- 修复提交：`b25ea2c`；通过的 Actions run：`31324469250`。
