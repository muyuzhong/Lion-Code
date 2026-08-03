# 三阶段：继续拆分 Agent 运行时职责

## Goal

在不改变 Lion 对外行为的前提下，继续将 `lion_code/agent.py` 中边界清晰的运行时职责拆到独立模块，使主协调器逐步接近约 1200 行，并让每个职责拥有可独立验证的测试与回滚点。

## Confirmed Background

- `master` 与 `origin/master` 当前同步于 `ca27a21`；前两项切片已完成：`autonomy_runtime.py` 和 `session_memory_coordinator.py`。
- `agent.py` 已从 2397 行收敛至约 2070 行；全量测试基线为 `547 passed, 6 skipped`。
- 已知静态基线为 Ruff 218、format 146、mypy 105；本路线不以清理历史基线为目标。
- 工作区中 `docs/tui-migration-audit.md` 的删除和 `08-01-quality-baseline` 的未跟踪文件属于并行工作，不纳入本父任务的提交。

## Delivery Map

| 顺序 | 切片 | 状态 | 可验证结果 |
| --- | --- | --- | --- |
| S3 | `subagent_factory` | 已归档 | 子 Agent 与 Skill fork 的构造、工具筛选与懒导入边界独立 |
| S4 | `learning_runtime` | 规划中 | 已有特征测试覆盖的 `/learn` 运行时职责独立 |
| S5 | `agent_lifecycle` | 待创建 | `configure_api` 等生命周期配置集中且兼容 |
| S6 | `agent_runtime` | 待创建，最后实施 | Core 协调收敛，且不重新耦合前述职责 |

## Requirements

- R1：每个切片必须是独立的 Trellis 子任务，具有明确范围、设计、实施计划、验证记录和中文提交。
- R2：每次提取只移动一个职责；保留 `Agent` 的公共 API、现有命令/工具行为、权限边界、会话与 Core 历史不变量。
- R3：切片之间按 S3 → S4 → S5 → S6 顺序推进；后续切片必须以当前实现而非旧行号作为设计依据。
- R4：每个切片完成后记录 `agent.py` 行数、全量测试结果和相对静态基线的差异；不得把已有静态问题当成本切片引入的回归。
- R5：不修改或暂存并行工作树变更，尤其是质量基线任务和 TUI 审计文档删除。

## Acceptance Criteria

- [ ] AC1：S3 至 S6 均已完成、验证、提交并归档为独立子任务。
- [ ] AC2：每个切片均保持既有对外行为和兼容测试通过；没有以删测或放宽权限来换取收敛。
- [ ] AC3：最终 `agent.py` 的职责边界可由模块和窄协议解释，且行数朝约 1200 行目标显著收敛。
- [ ] AC4：最终全量测试、编译、导入边界、差异检查和 Trellis 校验均有记录；基线差异被如实报告。
- [ ] AC5：所有提交仅包含本路线任务文件、实现和必要测试/维护记录，不包含已知并行变更。

## Out of Scope

- 新增产品能力、改变模型/权限语义、重写 Core Harness 或清理历史 Ruff/format/mypy 基线。
- 质量基线任务、TUI `/skill` 接线，以及无关文档删除的处理。

## Planning Status

父任务只管理路线、子任务映射和最终集成验收；S3 已归档，S4 已依据最新代码完成规划，等待单独的实现批准。后续 S5-S6 仍在前一切片完成后基于最新代码创建，避免预先固化不再准确的设计。
