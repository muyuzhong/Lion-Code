"""Agent Runtime 物理边界。

四个 Runtime Owner 加独立状态 Owner：

- ``agent`` -- AgentRuntime：只编排一次 Agent operation 的调用顺序；
- ``conversation`` -- ConversationRuntime：AgentHarness、canonical 活跃消息、
  live Provider/model 与 run 捕获的唯一 Owner；
- ``session`` -- SessionRuntime：会话身份、JSONL 仓库与 Recorder 生命周期；
- ``context`` -- ContextRuntime：Context 派生服务与压缩状态；
- ``provider`` -- ProviderController：ProviderState 与 Provider 配置命令；
- ``execution`` / ``session_identity`` -- 取消令牌与会话标识。

这些模块不向上依赖 Composition/Application/TUI。
"""
