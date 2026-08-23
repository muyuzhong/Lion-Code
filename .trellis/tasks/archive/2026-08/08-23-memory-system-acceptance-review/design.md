# Memory 验收审查方法

## 1. 审查对象

```text
用户最终方案 6c9fddd
        │  contract diff
        ▼
master 实现与测试（锁定 SHA）
        │  ownership / data-flow / behavior
        ▼
定向复现与 findings
```

归档 parent/child PRD 只说明实施路径为何产生当前代码。若它与 `6c9fddd` 冲突，报告同时记录“实现忠于旧 PRD”和“偏离最新产品决策”，不能用前者抵消后者。

## 2. 审查维度

| 维度 | 核心问题 | 主要证据 |
| --- | --- | --- |
| Contract | 最终一期要求是否存在、是否增加了明确后置内容 | `6c9fddd` artifacts、归档 PRDs、current code |
| Ownership | 谁拥有持久状态、query、Session 与 composition | CodeGraph 调用路径、架构测试、spec |
| Persistence | schema/事务/版本/索引/隔离/治理是否安全 | `store.py`、临时 DB 复现、store tests |
| Permission | 模型能否绕过用户确认改变 pinned 或物理删除 | tool capabilities、Permission middleware、tool tests |
| Recall | query 是否正确、低噪声、有界、纯读取 | context manager、query layer、negative tests |
| Continuity | 新 Session 是否按需知道任务，而非复制旧上下文 | task model/tools、handoff flow、integration tests |
| Complexity | 每个新 SPI/table/state/PR 是否由最终一期需求要求 | contract matrix、blast radius、删除思考实验 |
| Tests | 测试是否覆盖真实负向数据流而非实现自证 | test source、focused pytest、mutation thought test |

## 3. 严重级别

- **P0**：可导致不可恢复的数据破坏、明显安全边界突破或普遍无法启动。
- **P1**：核心用户目标缺失、状态所有权破坏、确认可被绕过、稳定出现错误/噪声记忆。
- **P2**：重要边界或边缘行为错误、范围漂移带来显著维护成本、关键负向测试缺失。
- **P3**：局部可维护性、诊断或文档问题，对当前行为影响较小。

纯粹“与最新方案不同”不自动等于 P1；根据用户影响、数据风险和后续修改成本定级。多个同根因表现合并为一个 finding。

## 4. 证据流程

1. 锁定 `origin/master` SHA，确认 dirty worktree 只含审查前已存在的未跟踪任务目录。
2. 从 `6c9fddd` 提取最终 Requirement/Acceptance 清单，与归档 parent/child artifacts 建立差异表。
3. 使用 CodeGraph 先追踪当前 Memory、QueryContext、FullProfile、ToolRuntime、Session handoff 和 prompt loader 的真实调用路径。
4. 阅读命中符号的当前源码与直接测试；不依据旧行号或 PR diff 对当前 master 下结论。
5. 对 persistence、permission、query 和 Session 交互构造最小临时目录/SQLite 复现；不读写用户真实 `~/.lion-code/memory.sqlite3`。
6. 运行 Memory 相关定向测试；只有结论需要时才扩展测试范围。
7. 将 contract matrix、commands 和 findings 写入 `research/acceptance-report.md`，再复核所有 P0–P2 file:line。
8. 最终确认没有产品文件变化，只提交/保留本审查任务产物。

## 5. Findings 格式

```text
[P1] 简短标题
影响：用户可观察后果。
触发：最小前置条件。
证据：current file:line + test/command。
根因：真正的状态/数据流错误。
基线：违反的最终 requirement，或说明它是 scope drift。
测试缺口：为何现有测试没有阻止。
```

报告先列 findings，再列 contract matrix、验证结果和 residual risks。若同一根因同时造成设计漂移和 bug，只保留一个 finding 并在影响中解释两者。

## 6. 安全与回滚

审查命令只在临时目录和内存/临时 SQLite 上运行，不调用真实 Provider、不写用户 Memory DB、不执行 destructive Git 命令。唯一持久输出是本任务目录；删除该目录即可完整回滚审查产物，不影响产品。
