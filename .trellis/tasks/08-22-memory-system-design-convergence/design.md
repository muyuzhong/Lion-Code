# Lion Memory — 收敛技术设计

## 1. 决策

Lion 不需要四个记忆平台，也不应把四类内容删成两个平面。推荐模型是：

```text
一个 Memory Capability
  ├─ scope = long_term     跨项目、用户级
  │    ├─ kind = definition  记住“是什么”
  │    └─ kind = behavior    记住“怎么做”
  └─ scope = project       当前项目隔离
       ├─ kind = definition  记住“这个项目是什么”
       └─ kind = behavior    记住“在这个项目怎么做”
```

四个象限是产品语义；一个 Capability、一个 repository 实现、同一组工具和两份作用域文件是工程实现。收敛的是基础设施数量，不是记忆能力。

## 2. 对上一版取舍的纠正

上一版把 `AGENTS.md`、`.trellis/spec/` 和 Skill 合并成 “Project Knowledge”，只为历史经验增加 Project Lessons。这个选择优化了组件数量、污染风险和实现成本，但代价是：

1. Trellis 被错误算进 Lion 产品边界；
2. Skill 被错误当成行为记忆；
3. AGENTS 被错误当成项目定义记忆；
4. 长期定义和长期行为没有产品内承载者；
5. 项目行为被压扁成单一 lesson 文本，失去触发条件与行动契约；
6. Lion 的记忆能力依赖产品外机制才能完整。

因此上一版不是合理的产品收敛。合理取舍是保留 `长期/项目 × 定义/行为` 四个语义象限，同时删除四套平台、重复运行时和自动维护链。

## 3. 第一性原理

### 3.1 记忆必须解决的最小问题

一个新会话需要复用当前上下文没有携带、但用户明确希望跨会话保留的信息。信息只有两个正交维度：

- **适用范围**：对所有项目都成立，还是只对当前项目成立；
- **使用方式**：描述世界/用户/项目，还是规定遇到条件后如何行动。

作用域决定隔离和存储位置，语义类型决定数据结构和召回后的使用方式。原设计的 Repo、Coding、Preference、Procedure 是内容标签，不能稳定地充当存储边界：一条 preference 可能是定义，也可能是行为；一条 procedure 也可能只适用于某个项目。

### 3.2 四个象限

| 作用域 | 定义：是什么 | 行为：怎么做 |
| --- | --- | --- |
| 长期 | 用户稳定偏好、工作环境、跨项目事实。例如“用户主要在 Windows/PowerShell 工作”。 | 跨项目协作与工程动作。例如“修改脏工作树时只暂存任务拥有的文件”。 |
| 项目 | 当前仓库架构、所有权、决策、关键命令。例如“ToolRuntime 是唯一工具执行路径”。 | 当前项目触发式规则、已验证失败模式和回归动作。例如“修改 Kernel 后先运行架构门禁”。 |

### 3.3 权威性

Memory 是跨会话的历史上下文，不是最高优先级指令。发生冲突时按当前证据处理：

```text
当前系统/开发者/用户指令、当前源码与测试、当前 AGENTS
    > Memory
```

记忆冲突后必须显式更新或删除，不能用“更新时间较新”“命中次数较多”或“向量更相似”自动判真。

## 4. 非 Memory 边界

| 能力/数据 | 定位 | 与 Memory 的关系 |
| --- | --- | --- |
| AGENTS.md | 当前项目的权威 Agent 指令 | 可作为验证记忆的当前证据；不是 Memory store。 |
| Skill | 可执行、可分发的能力和提示包 | 行为记忆可提示用户另行沉淀为 Skill，但不自动晋升，也不由 Memory 读取。 |
| Trellis | 用户开发 Agent 时使用的外部流程管理工具 | 完全不进入 Lion Memory 的对象图、存储、检索或测试契约。 |
| canonical Session | 当前会话事件与重放事实 | 记录召回工具结果；不是跨会话记忆源。 |
| Compaction | 会话上下文有界投影 | 不读写 Memory store。 |
| Supervisor Checkpoint | 长任务执行恢复 | 不包含记忆内容。 |
| Plan | 当前任务状态 | 不镜像到 Memory。 |

## 5. 目标架构

```text
FullProfile
  -> MemoryCapability
       -> MemoryPromptLayer       只说明何时召回及可信度，不注入记忆内容
       -> recall_memory           只读；同时检索两个作用域
       -> remember_definition     需确认
       -> remember_behavior       需确认
       -> forget_memory           需确认
       -> MemoryRepository        一个具体实现，不设单实现 Protocol
            -> ~/.lion-code/memory/long-term.json
            -> ~/.lion-code/projects/<project-key>/memory.json

四类工具调用 -> 现有 ToolRuntime -> 现有权限/审计/ToolResult
召回结果 -> ordinary Session observation
```

Memory 不进入 Agent Runtime、MetaAgent、Application/TUI facade、PlanRuntime、ContextRuntime 或 Session schema。`AgentComposition` 不暴露 repository 作为 service locator。

## 6. 数据契约

两个文件使用同一文档结构；文件位置隐含 scope，条目不重复保存 scope：

```json
{
  "definitions": [
    {
      "key": "primary-shell",
      "statement": "用户主要使用 Windows PowerShell。",
      "evidence": ["用户明确说明"]
    }
  ],
  "behaviors": [
    {
      "key": "dirty-worktree-staging",
      "trigger": "工作树包含与当前任务无关的改动",
      "instruction": "只暂存并提交当前任务拥有的路径。",
      "evidence": ["用户明确说明"],
      "paths": ["lion_code/"]
    }
  ]
}
```

### Definition

- `key`：作用域内稳定、可读的唯一键；
- `statement`：一个可验证的“是什么”陈述；
- `evidence`：至少一条用户决定、当前源码、测试、命令结果或提交引用；
- `paths`：仅项目记忆可选，用于限定相关项目路径。

### Behavior

- `key`：作用域内稳定、可读的唯一键；
- `trigger`：可以判断的适用条件；
- `instruction`：条件成立时要执行的动作；
- `evidence`：至少一条来源；
- `paths`：仅项目记忆可选。

MVP 不保存 `version`、时间戳、状态、置信度、使用次数、最后命中时间、归档副本、superseded 链或向量。定义和行为使用不同写入工具，避免一个带大量互斥可选字段的万能 schema。

## 7. 存储与所有权

- `MemoryRepository` 属于 `capabilities/memory/`，由一个实例管理长期和当前项目两份文件。
- 长期文件位于用户级 app data；项目文件复用 `ProjectIdentity` 与 `project_storage_dir(identity)`，不写入仓库。
- 文件缺失表示该作用域为空，召回不创建文件。
- 每次写入完整严格校验、写临时文件、flush/fsync 后 `os.replace`。
- 非法 UTF-8、畸形 JSON、未知字段、重复 key 或越界内容直接报错；记住/忘记不得用空状态覆盖损坏文件。
- 同一 scope、同一 kind、同一 key 做原子替换；definition 与 behavior 可以使用相同 key，因为它们表达不同契约。
- `forget_memory(scope, kind, key)` 物理删除目标条目。它不改写已经包含旧召回结果的 append-only Session；历史会话删除是另一个需用户授权的操作。
- 没有迁移、兼容读取或 fallback。未来契约变化另行评审。

## 8. 召回

`recall_memory(query, paths=())` 一次检索两个 scope，并按四个象限分组返回。它只做有界、确定性扫描：

1. key 或项目 path 精确匹配优先；
2. query 中不同的 case-folded 词在 statement/trigger/instruction/key/path 中的命中数；
3. scope 固定顺序、kind 固定顺序、key 升序作为稳定 tie-break。

结果总数和总字符数使用固定上限；超限时返回明确 omission marker。空查询只列出各象限的 key，不展开正文。没有可配置权重、BM25、embedding、recency、use-count 写回或二次 LLM 调用。

`MemoryPromptLayer` 只告诉模型：新任务在大范围探索前调用一次召回；当前证据优先；使用行为前检查 trigger；未命中是正常结果。它不包含或隐藏注入实际记忆内容。MVP 接受模型可能漏调工具的可观测风险；在有真实漏召回数据前，不为此扩大 ContextLayer 的用户文本权限或增加 turn hook。

## 9. 写入与遗忘

- `remember_definition(scope, key, statement, evidence, paths=())` 明确写入定义。
- `remember_behavior(scope, key, trigger, instruction, evidence, paths=())` 明确写入行为。
- `forget_memory(scope, kind, key)` 明确删除一条记忆。
- 三个 mutation 工具均设置 `requires_confirmation=True`；`recall_memory` 是只读、可并发工具。
- 长期 scope 拒绝 `paths`；项目 scope 的 path 必须规范化为项目相对路径且不得越界。
- 活跃模型只在事实或行为已被当前证据验证、且预期跨会话复用时提出写入。一次性进度、当前目标、原始会话摘要、秘密、瞬时失败、未验证猜测不允许写入。
- 不自动从 Session、AGENTS、Skill 或 Trellis 抽取；不在任务结束时调用后台模型。
- Memory 不自动修改 AGENTS，也不自动生成 Skill。将成熟行为正式化为二者是独立、显式、可评审的产品外动作。

## 10. Composition 边界

`FullProfile` 默认选择新的 Memory Capability；CodingProfile 与 MinimalProfile 不变，调用方仍可通过现有 `extension_specs` 显式添加能力。

如 composition 需要内建选择名，使用不会恢复旧契约的新名字，例如 `_CAP_USER_PROJECT_MEMORY`。不得恢复 `_CAP_MEMORY`、`SessionMemoryCoordinator`、`MemoryQuerySink`、ProjectionLayer、Dream、Learning 或 provider-side memory query service。

Capability 只贡献四个工具和一个 PromptLayer，不贡献 ContextLayer、SessionParticipant 或 Runtime owner。

## 11. 错误与安全矩阵

| 条件 | 结果 |
| --- | --- |
| 两个文件都不存在 | 召回返回空，不创建文件。 |
| 其中一个文件损坏 | 明确指出损坏 scope；拒绝覆盖；另一个 scope 不被修改。 |
| 长期写入携带 paths | 参数错误，无文件变化。 |
| 项目 path 越界 | 参数错误，无文件变化。 |
| 空查询 | 只列四个象限的 key。 |
| 没有匹配 | 返回正常空结果，继续检查当前上下文。 |
| 超过预算 | 按稳定顺序截断并显示 omission marker。 |
| 同 key、同 kind 写入 | 原子替换。 |
| 不同记忆互相冲突 | 同时显示，检查当前证据后显式更新或删除。 |
| 当前代码/AGENTS 与记忆冲突 | 当前证据胜出，记忆不能覆盖其行为。 |
| 用户拒绝 mutation 确认 | 不修改文件，返回现有 permission-denied 结果。 |
| 恢复历史 Session | transcript 中旧召回仍在；下一次 recall 读取当前 Memory store。 |

## 12. 删除与延后

| 原设计元素 | 决策 | 理由 |
| --- | --- | --- |
| Repo/Coding/Preference/Procedure 四套平台 | 删除平台划分，保留内容语义 | scope × kind 更正交；不需要四套基础设施。 |
| Markdown + JSONL + SQLite 三重存储 | 删除 | 两份作用域 JSON 已能满足当前规模和隔离需求。 |
| FTS5/BM25/向量/加权评分 | 延后 | 先用可解释扫描；有实际召回失败再升级。 |
| Task-start Hook / Agent Wrapper | 删除 | 模型已有 query 和工具；PromptLayer 足以形成可观测 MVP。 |
| Task-end 后台 LLM | 删除 | 污染面大且产生第二写者；显式写入可审计。 |
| 语义去重阈值 | 删除 | exact key 替换即可；相似不等于相同。 |
| use_count / last_used_at | 删除 | 召回应只读，避免隐藏写入。 |
| 定时衰减 / 周期 consolidation | 延后 | 只有测得噪声增长后才有需求。 |
| 自动写 AGENTS / 自动生成 Skill | 删除 | 改变权威指令或能力包必须独立评审。 |
| CLI/TUI viewer、配置权重、cron | 延后 | 四个模型工具是 MVP 控制面。 |

## 13. 回滚

- 取消注册 Capability 即可停止新召回和写入，不改变 Session、Compaction、Checkpoint、Plan 或 Runtime schema。
- 两份 JSON 是可恢复的用户数据；回滚代码不自动删除，删除需单独授权。
- 新设计不迁移旧 Memory 数据，也不保留旧 API；当前产品没有需要兼容的生产契约。
