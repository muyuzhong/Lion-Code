# 项目约定

## 适用范围、授权与完成标准

- 本文件适用于当前仓库；全局规则继续生效，子目录规则仅补充其目录范围内的约束。当前用户明确要求优先于文件中的默认流程；系统与平台指令仍按其优先级执行。Skill 和工作流不能自行扩大用户授权。
- 解释、诊断、审查、计划和建议默认只读，不自动授权修复。用户明确要求修改时，完成范围内的修改、适度验证和结果交付，不仅停留在计划或等待再次授权。
- 已授权且范围明确的日常工作自主推进。仅在缺失信息会实质改变结果、范围或风险，或下一步超出授权时询问；已回答的问题和已给出的授权不重复询问。可合理推断的小选择说明假设后继续。
- 发现范围外问题时记录证据与建议，不顺带修复。出现阻塞时继续可独立完成的已授权工作，最终说明具体阻塞、已完成内容和所需输入，不把未验证结果报告为成功。
- 保留已有未提交改动，不覆盖、回退或纳入无关修改。部署、发布、对外发送消息、凭据访问或处理、重要数据删除须有对应的明确授权；普通修改或流程完成不包含这些权限。

## 核心原则与防过度设计

1. **最小实现与禁止顺带重构**：维护任务优先局部修改现有实现，不为未来假设提前设计，不顺便重构无关代码。用户明确要求重设计、重写或打破兼容时，按该范围解决问题，不以局部修改限制已授权目标。
2. **严禁过度抽象**：默认拒绝新增 Manager、Factory、Registry、Adapter、Strategy、Resolver、Coordinator、通用 Config 系统、Plugin/Hook 机制或新抽象基类/Protocol。仅在已有 2 个以上真实使用场景且无法修改现有代码解决时才允许提取。
3. **彻底删除与零兼容包袱**：在本次已授权的替换或删除范围内，过时实现直接删除，不留仅用于旧实现的 fallback、migration 或兼容层。不据此主动删除范围外实现、改变未授权的公开接口或删除用户数据；确需扩大范围时先说明影响并询问。
4. **优先复用**：优先使用项目已有依赖和成熟库，不重复实现已有能力。

## 修改范围与注释规范

- **修改范围**：严格限制在任务直接所需代码，不主动格式化、重命名或重构无关代码，不主动改变公开接口。
- **意图表达**：优先通过命名、类型和函数拆分表达意图；公共接口文档注释描述契约、边界、副作用与异常。
- **注释原则**：注释仅记录设计原因、业务规则、不变量与安全约束，不逐行解释代码。临时方案标记 `TODO(issue): 原因与完成条件`。源码注释统一使用中文，标识符与技术术语保留英文。

## 最小验证原则

- **默认最小验证**：运行与本次修改直接相关的 targeted tests 和必要的局部静态检查，并检查 `git diff --check`。纯文档或规则修改检查内容、引用及 diff 即可，不为此运行代码测试。相关检查通过且无未解决风险时停止扩大验证，不提前停止交付。
- **验证范围**：禁止默认运行全量 test suite、全项目 lint、完整 mypy、coverage 或 radon/vulture 等全局扫描。Skill 中的“项目检查”“完整检查”默认指本次全部受影响范围，不自动指整个仓库；新增函数本身不构成新增测试的理由，测试应验证真实行为、回归或边界。
- **完整门禁触发条件**：仅在用户明确要求、准备提交 PR/merge、修改 CI/构建/测试基础设施、或修改核心公共接口时执行全量质量门禁。
- **失败处置**：优先定位根因，与当前修改无关的已有失败不顺手修复，修复后仅重跑受影响测试。

## 架构边界与修改约束

- **修改前阅读**：修改 Kernel、Runtime、Context、Provider、Tool 等核心边界前，先阅读对应的 `.trellis/spec/` 和 `docs/architecture/` 文档，理解现有 ownership 与依赖方向。
- **保持单向边界**：优先保持现有边界，不为了“解耦”机械增加层或接口；业务逻辑严禁反向依赖组合层或具体基础设施实现。
- **真值来源**：架构约束以 `tests/architecture/`、`.trellis/spec/backend/`、`docs/architecture/`、`_boundaries.py` 及 import-linter 为准。代码与文档冲突时，结合当前实现与架构测试判断，不因代码存在就认定其符合约束。只读任务报告冲突；实施任务同步修正与本次改动直接相关的文档，无法确定的架构取舍先说明证据再询问。

## Git 与 PR 规范

- **Git 授权**：修改文件不自动授权 commit、push 或 PR 操作。仅在用户明确要求或当前任务已建立对应授权流程时执行；merge 或 auto-merge 必须获得对该具体 PR 的明确授权，CI 通过或“继续”不代表合并授权。不擅自 force-push 或 rebase。
- **原子提交**：获准提交时，每个独立改动单次提交，Commit message 用中文描述明确目的；提交前检查 `git diff`，仅暂存本任务改动，不提交无意义 CRLF 变化。未获提交授权时，交付已验证的工作区修改即可，不以提交作为任务完成前提。
- **独立 PR**：一个 PR 只解决一个独立问题或完成一个职责迁移，保证可独立理解与回滚；过大 PR 按行为边界拆分，不混入无关清理。

## Trellis 与 Skill 的适用条件

- **默认按需使用**：日常工作以本文件和相关架构规范为准，不自动进入 Trellis。仅在用户明确调用 Trellis Skill、要求创建/继续 Trellis 任务，或接受本次任务使用 Trellis 的建议后进入正式流程；已有任务文件或复杂度本身不构成启用授权。
- **保留知识，关闭自动编排**：保留 `.trellis/spec/`、任务与研究资料；Codex 不默认注入启动、每轮阶段及编辑前的 Trellis 流程。明确使用 Trellis 子 agent 时保留上下文注入和原有模型路由。归档与日志默认不自动提交，仅在对应工作获准时执行。

- 下方受管理区提供入口，不要求每次任务遍历 `.trellis/`。按任务读取相关规则和明确引用的材料；不因初始化流程读取无关会话记录、日志、缓存或凭据。
- 范围明确的小修改可直接完成，不以创建 Trellis 任务、PRD、研究笔记或归档作为完成前提。用户选择不创建任务后，本次不再询问。创建任务须先取得同意；复杂工作需要持久计划时说明原因，但不把已经明确授权的实施重新解释为仅获计划授权。
- 正式进入 Trellis 的任务按对应阶段加载 Skill。外部模型路由和已选择的执行模式保持不变；多模型、子 agent 和上下文清单仅适用于对应流程，不自动扩展到解释、只读检查或未进入 Trellis 的小修改。
- 审查模式只报告问题；实施后的检查可修复本任务范围内的问题，遵循上方最小验证和失败处置规则。Spec 更新仅记录本任务产生的有效新约束，不为满足流程而制造文档改动。
- 本节是项目对通用工作流的适用范围约束，不能覆盖更高优先级的运行时注入。若注入仍要求额外确认或强制流程，应指出具体来源及冲突；修改本文件不会自动更新 `.trellis/workflow.md`、Skills 或注入模板。

<!-- TRELLIS:START -->

# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.
<!-- TRELLIS:END -->
