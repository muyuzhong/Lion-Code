# 项目级 Session Memory 设计

## Status

本文件是规划设计，不是实现状态说明。当前任务保持 planning，产品代码、测试和运行时规格均未被本规划改动。

## 已核实的现状

- lion_code/memory.py 的 _project_hash 直接对 Path.cwd() 求哈希，因此同一 Git 项目的子目录会被识别为不同 Memory 根。
- lion_code/prompt.py 中 ProjectContextFile 的注释同时提到 CLAUDE.md 和 AGENTS.md，但实际 load_claude_md 只向上读取 CLAUDE.md。
- lion_code/agent.py 的 chat 顺序是准备会话、压缩、启动 MemoryCoordinator 预取、进入 Core。_prepare_core_context 会在每次 Provider 调用时 collect_ready，因此当前轮的预取可能在工具循环第二次调用时才进入上下文。
- lion_code/memory_runtime/injector.py 已经以深拷贝投影方式避免污染 Harness 与 JSONL，但只有一类 MemoryOverlay，且其预算可跳过任何 Overlay。
- lion_code/session_runtime 负责 append-only JSONL 会话；它是完整对话历史，不适合承载跨对话短期工作状态。
- lion_code/dream.py 只显式整合 Memory 文件和最近 JSONL，会话中没有受限的 Session Memory 候选输入。

## 边界与不变量

1. Canonical history 只包含真实用户、助手和工具消息。三层记忆只能在 Provider 投影中出现。
2. Session JSONL 与 Session Memory 分离：前者可完整恢复、压缩和审计；后者只保存项目当前工作状态。
3. 项目指令和 Session Memory 不依赖语义召回；Auto Memory 才是按当前问题选择性的异步召回。
4. 一次 chat 从开始到所有工具循环结束使用同一个 OverlaySnapshot。异步结果只能供下一用户轮使用。
5. 确定性工具证据的优先级高于模型概括；模型输出不能删除、伪造或把临时事实升级为长期知识。
6. 项目指令是只读不可信内容，永远不进入 system prompt，也没有任何自动写回路径。

## 项目身份

新增 lion_code/project_identity.py，提供不可变的 ProjectIdentity：

- root：Git 命令 git -C cwd rev-parse --show-toplevel 返回的当前 worktree 根；命令失败或 cwd 不在 Git 内时使用 cwd.resolve()。
- key：对 root 的 realpath/normcase 字符串计算 SHA-256 的短键。Windows 的大小写与长路径前缀须在输入哈希前规范化。
- is_git：仅用于诊断和测试，不参与业务分支。

Auto Memory 的 get_memory_dir(identity=None) 使用 identity.key。Session Memory 位于同一项目目录下的 session-memory.json。新写入始终使用规范项目目录；第一版不会移动或删除旧 cwd-hash 目录。

Git 的 --show-toplevel 针对每个 worktree 返回其工作树根，因此两个 worktree 的状态天然隔离。当前产品没有运行中切换 cwd 的入口；打开另一项目会构造新 Agent 并重新建立 ProjectIdentity，不能复用上一个实例的三层上下文。

## 项目记忆加载

保留 prompt.py 的 ProjectContextFile 作为公开视图，并把加载逻辑改为显式的项目边界加载器：

1. 由 ProjectIdentity.root 枚举到当前 cwd 的目录链，根目录在前、cwd 在后。
2. 每个目录按 CLAUDE.md、AGENTS.md 的顺序读取；同目录 AGENTS.md 因后置而优先。
3. 复用现有安全的 include 解析和读取失败降级，记录实际加载文件路径，永不写入。
4. 将所有项目文件拼为一个 project Overlay；文件标题保留绝对或相对路径，便于模型区分来源和层级。

更深目录的规则比项目根更具体，因此后置。AGENTS.md 只在与同目录 CLAUDE.md 冲突时优先；这避免根目录 AGENTS.md 意外压过子目录的专用规则。

## Session Memory 数据和存储

新增单一轻量模块 lion_code/session_memory.py，而不建立产品侧任务树。其 JSON schema 版本为 1，字段为：

| 字段 | 含义 |
| --- | --- |
| projectRoot | 用于人工诊断的规范项目根 |
| currentGoal | 当前总体目标 |
| activeTask | 当前活跃任务的简短文本 |
| completed | 已完成事项摘要 |
| pending | 待完成事项 |
| decisions | 已做决策及理由 |
| blockers | 当前阻塞和证据 |
| relevantFiles | 已读或已改、仍相关的路径 |
| verification | 测试、lint、编译等验证状态 |
| previousHandoff | 上一 Session 可继续的交接摘要 |
| nextStep | 当前最小下一步 |
| updatedAt | 最后写入时间 |

Repository 使用 session-memory.json 的原子临时文件替换。损坏或无法解析的已有文件必须报告明确错误且不覆盖；调用层仅保留只读快照并提示用户处理，不能将空状态回写为数据丢失。

完成 task 时只将 activeTask 的收敛结果移入 completed 并清空当前 task 指针；不会创建任务图、依赖、阶段或子任务对象。

## 三层 Overlay 与优先级

扩展 MemoryOverlay 的来源标签，而保持既有三参数构造兼容。MemoryContextInjector 接受一个本轮 OverlaySnapshot，并固定输出：

1. project：AGENTS.md 和 CLAUDE.md 的只读项目记忆；
2. session：当前项目 Session Memory 的格式化快照；
3. auto：MemoryCoordinator 已完成的语义召回结果。

project 和 session 是 required Overlay：在各自的来源大小上限内无条件进入投影；auto 才受活跃数量、单次字节和剩余 token 预算裁剪。格式化块要显式标示来源和顺序。注入仍通过 ContextManager 的深拷贝投影，并保留未配对 tool call/result 时不注入的安全规则。

来源大小上限必须在读取 Session Memory 和项目文件时确定并给出截断标记，而不是让 Injector 静默跳过 required Overlay。这样既保证两层存在，又保留 Provider 上下文的硬安全边界。

## 每轮编排

Agent.chat 在通过会话准备和压缩检查后执行以下固定步骤：

1. 读取当前项目的 Session Memory，定位 activeTask 和 previousHandoff。
2. 收集上一用户轮已经完成的 Auto Memory 预取。
3. 启动当前用户输入的 Auto Memory 异步预取，但不等待它。
4. 将项目 Overlay、刚读取的 Session Memory 和步骤 2 中的 Auto Memory 组成不可变 OverlaySnapshot。
5. 运行 Core prompt 和同轮 continue_ 工具循环；_prepare_core_context 只使用该快照，不再调用 collect_ready。
6. 在 chat 的 finally 路径从该轮 canonical 消息提取证据，合并语义补充，并原子保存新的 Session Memory。

因此首个模型调用与同轮工具后的后续模型调用看到同一快照；当前轮异步预取若稍后完成，只在下一用户轮步骤 2 被纳入。

clear_history 只替换 JSONL session id、Harness 和 Auto Memory 的会话级预取状态；它重新读取但不删除 Session Memory。restore_core_session 重放 JSONL 后也重新加载当前 ProjectIdentity 的项目指令和 Session Memory，绝不从旧 JSONL 的 cwd 反向借用其他项目状态。

## 每轮状态更新与确定性证据

从本轮新增的 canonical 消息配对 AssistantMessage.tool_calls 和 ToolResultMessage：

- 成功的 write_file/edit_file：从 file_path 写入 relevantFiles。
- read_file：从 file_path 写入相关文件，不等同于已修改。
- run_shell：只有命令看起来是测试、lint、类型检查或编译时才写入 verification；以 ToolResult 的错误、Command failed (exit code ...) 或 timeout 文本判定结果。
- 任意失败工具：写入带工具名和压缩结果的 blocker 证据。
- 不从 shell 文本猜测文件修改，避免把不可靠输出写成事实。

随后向当前 Provider 的无工具 side query 发送用户输入、最终助手回复、受限的工具证据和旧状态，要求返回严格 JSON patch。该 patch 只能补充 currentGoal、activeTask、completed、pending、decisions、blockers、previousHandoff、nextStep；不得修改确定性文件和验证字段。解析失败、超时或 Provider 不可用时仍保存确定性更新，且不阻断用户回复。

## 任务和手动交接命令

最小命令统一为：

| 命令 | 行为 |
| --- | --- |
| /task | 显示 activeTask、currentGoal、nextStep |
| /task switch <text> | 切换 activeTask，并保留旧 task 的完成或待办摘要 |
| /task done | 结束 activeTask，归档短期结果并准备长期候选 |
| /session-memory | 显示当前项目的完整 Session Memory |
| /handoff | 以当前状态生成并保存 previousHandoff |
| /dream | 使用现有 Dream 流程，同时提供受限的 Session Memory 长期候选 |

application/commands.py 只解析同步意图；LionCodingSession 提供实际状态操作；TUI app.py 和 __main__.py 各自异步分发并显示结果。命令不改 JSONL transcript。

## Auto Memory 与 Dream 候选边界

memory.py、提示文本和 Dream prompt 统一将长期层称为 Auto Memory。project 类型的说明改为长期、经验证的项目决策及原因。

候选提取是纯函数，输入为已结束 task 或当前 Session Memory。允许：

- 稳定 user 偏好；
- 明确 feedback；
- 已验证的架构决策和原因；
- 可复用失败经验，且包含已发生的失败与改正；
- 外部 reference 指针。

拒绝 currentGoal、activeTask、completed/pending 进度、临时失败、relevantFiles、verification 原文、previousHandoff 和 nextStep。Dream 只能将通过这一过滤器的候选作为不可信证据，再沿用现有 DreamPlan 校验写入 Auto Memory 目录；没有路径能写 AGENTS.md。

## 失败与恢复

- Git 查询失败：退回规范 cwd，不阻断会话。
- 项目指令读取失败：跳过该文件，不写入或替换其他文件。
- Session Memory 损坏：显示错误，禁止自动覆盖，仍可运行但不以空状态覆盖原文件。
- Auto Memory 预取失败或取消：不影响主模型；结果延后或丢弃。
- 语义 patch 失败：保留确定性事实，继续保存轻量状态。
- required Overlay 与 Provider 窗口冲突：在来源读取时按记录的安全上限截断并标注，不将其悄悄降为可选 Auto Memory。

## 规格更新时机

实现且测试通过后，更新 .trellis/spec/backend/runtime-boundaries.md，补充三层 Overlay、Session JSONL/Session Memory 分离和每轮快照不变量。规划阶段不修改该运行时事实规格。
