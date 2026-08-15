# PR6 MetaAgent Bare Extraction — Design

## 1. Boundary decision

采用一个新的薄 `MetaAgent` facade 和 `build_meta_agent()`，复用现有唯一的 Kernel loop、Harness runtime、tool runtime、session runtime、context、usage 与 provider ownership。不会复制 `Agent`、`AgentRuntimeCoordinator`、`run_agent_loop` 或 SessionRecorder。

Full Product `Agent` 仍通过 `PRODUCT_CAPABILITIES` 选择高级能力；MetaAgent 固定传空 capability 集合，调用方不能通过 facade 回接 Feature。

## 2. Real PR chain state

| Stage | Real result on master | PR6 consequence |
|---|---|---|
| PR0 | 四层 contract 与 10 类 Kernel event contract 已合并 | 复用事件类型，只补真实 compaction 发射 |
| PR1 | Core turn/session 删除 Memory 编排，先合入 PR0 分支 | 不恢复 Memory lifecycle |
| PR2 | 没有独立 PR；`ProviderManager -> MemoryQuerySink` 仍在 | PR6 删除此 bare-path 泄漏 |
| PR3 | Kernel 删除 Plan 特判 | 不恢复 Plan context reset |
| PR4 | Permission 删除 Plan/Autonomy 产品模式 | Coding test 只使用 generic permission mode |
| PR5 | empty registry 与 capability-gated Feature constructors 已建立 | PR6 增加可运行 facade、最强负向测试和剩余 helper 门控 |

## 3. Construction flow

```text
build_meta_agent(provider, tools)
  -> explicit ToolRegistry(register only supplied tools)
  -> AgentConfig(neutral prompt, generic permission/budget)
  -> AgentDependencies(direct provider, session/context seams, empty hooks)
  -> build_agent_composition(capabilities=frozenset())
  -> empty CapabilityRegistry + CapabilityRuntime
  -> ToolRuntime + middleware + ContextManager
  -> AgentRuntimeCoordinator + AgentHarness
  -> MetaAgent(generic references only)
```

`MetaAgent` 不保存 `AgentComposition`，只保存 runtime coordinator、provider manager、session repository/state、usage 与 budget 所需引用。这样 facade 表面与持有图都没有 Feature-specific 字段。

## 4. Provider ownership and unfinished PR2

删除：

- `ProviderTextQueryService` 从 `provider_manager.py` 的 import。
- `MemoryQuerySink` protocol、ProviderManager `memory` 参数与 `_memory` 字段。
- provider replacement transaction 中 `ProviderTextQueryService` 构造和 sink 更新。
- composition 的 `DeferredMemoryQuerySink` / `MemoryQuerySinkAdapter` 及 bind。

保持：Provider 构造先成功、runtime 原位替换、model 更新、context compactor 更新、model-limit cache invalidation、recorder 记录、旧 provider 延迟关闭的事务顺序。

直接传入的 provider 通过 `AgentDependencies.provider` 进入 provider graph；runtime readiness 由“已有 provider 对象或 credential config 有效”判断，不注入假 API key。

## 5. Bare helper gating

以下对象只在其消费者 capability 被选择时创建：

- `SubagentStatusSink`：SubAgent/Skill/Memory 路径。
- `NoticeSinkAdapter`：Memory/Autonomy 路径。
- `ToolEnvironment`：MCP/SubAgent/Skill/Memory/Dream 或调用方显式注入路径。

Bare MetaAgent 不创建上述对象；通用 `NoticeController`、`ConfirmationController`、Permission、ToolRegistry/Runtime、Session、Usage/Budget 仍属于 Harness。

## 6. Event flow

现有 model lifecycle 继续作为 `MessageUpdateEvent.assistant_message_event` 向订阅者暴露；不复制 provider event stream。

为 Harness 增加一个最小公共 `emit(event)`，内部仍调用同一 listener list。Runtime 在 compaction 真正开始前 emit started，成功后 emit completed；取消时 emit completed(aborted=True) 后继续传播取消。manual/overflow 调用显式传 reason，自动压缩使用 threshold。

不新增事件队列、重放、topic、priority、过滤器或 Supervisor 对象。

## 7. Facade surface

公开 generic API：

- execution: `run`, `chat`, `prompt`, `continue_`, `cancel`, `close`
- conversation: `messages`, `conversation`, `subscribe`, `steer`, `follow_up`
- context/session: `compact`, `session_id`, `new_session`, `restore`
- provider: `provider`, `model`, `configure_provider`, thinking getters/setters
- accounting: `usage`, `budget`

禁止任何含 Feature 名称的 public member。Facade 不提供 capability registration API；MetaAgent 永远是 zero-extension build。

## 8. Test design

1. Zero-tool smoke：脚本 Provider 返回文本，断言 canonical roles 与 provider tools==[].
2. Coding integration：测试层显式选择 `read_file/write_file/edit_file/list_files/grep_search/run_shell`，fake model 请求 `read_file`，断言 tool result 回到第二次 provider call 并得到 final response。
3. Strong negative：patch composition 中八类 Feature constructor/factory 为 raise；同一 MetaAgent 完成文本轮、工具轮、manual compact、new/restore、异步 cancellation 与 close。
4. Event assertions：收集 turn/model/tool/compaction/cancel 事件，不访问 Agent 私有对象。
5. Surface/AST gate：检查 MetaAgent public API 与 generic path import/name，不扫描 Product/Capability 实现目录。
6. ProviderManager tests：删除 Memory fake，保留 provider/context/recorder transaction assertions。

## 9. Compatibility, rollout and rollback

项目明确不保留向后兼容。`MemoryQuerySink` 是未完成 ownership migration 的内部端口，直接删除，不留 alias/deprecation/fallback。

唯一有意延期的行为是 Full Product 在 provider replacement 后刷新 Memory query service；下一阶段 Feature Re-home 重新以 capability-owned 方式接回。PR6 不创建临时 hook。

单 PR、无新依赖。回滚点为 PR6 中文提交；回滚后恢复 PR5 状态，不影响 PR0–PR5 merge commits。

