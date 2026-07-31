<div align="center">

# Lion Code

**一个强调执行可控、长会话效率与经验复用的轻量级 Python Coding Agent**

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-2ea44f.svg)](LICENSE)
[![Tests: 518 passed](https://img.shields.io/badge/Tests-518%20passed-22c55e.svg)](tests/)
[![Code: 43K lines Python](https://img.shields.io/badge/Code-43K%20lines%20Python-8B5CF6.svg)](lion_code/)
[![Status: Active](https://img.shields.io/badge/Status-Active%20Development-f59e0b.svg)](#路线图)

[快速开始](#快速开始) · [架构](#架构) · [安全模型](#1-fail-closed-工具执行边界) · [上下文管理](#2-多级上下文管理) · [评测](#可复现评测) · [路线图](#路线图)

</div>

---

## 为什么做 Lion Code

大多数 Coding Agent 示例在"模型调用工具，工具返回结果"这一步就结束了。真正影响长任务可靠性的，往往是之后的问题：

- **工具怎样安全执行**——如何阻止模型执行 `rm -rf` 或未经审查就推送到生产环境？
- **上下文怎样持续工作**——50+ 次工具调用后，如何避免上下文窗口爆炸，同时保护前缀缓存不被破坏？
- **经验怎样被再次使用**——辛苦排查出的问题，如何在下一次会话、下一位同事遇到时自动生效？
- **这些机制到底有没有用**——如何用数据说话，而不是凭感觉？

Lion Code 就是我对这些问题的回答。它是一个**可读、可验证的 Agent 运行时**（~43K 行 Python，518 条测试），用较少的依赖实现了上述所有关键机制，并为每项重要结论保留了源码、测试或 Benchmark 证据。

> **项目背景：** 本项目从 [Hugging Face Tau](https://github.com/huggingface/tau) 的通用运行时出发，以"源码吸收 + 本地演化"方式引入其核心循环（`tau_agent`），并在其上独立构建了安全模型、上下文管理管线、会话持久层和评测框架。Core 循环、规范消息类型和 Provider 抽象源自上游；工具执行运行时、Hook 系统、Memory 架构、TUI、上下文管理和 Benchmark 套件为原创工作。

---

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│                     CLI / Textual TUI                        │
│              lion-code [prompt] | --repl | --resume          │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                   LionCodingSession                          │
│          (application/session.py)                            │
│   事件桥接: Agent ↔ TUI · 命令注册 · Skill 发现              │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                        Agent                                 │
│                    (agent.py, ~94 KB)                         │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Core Runtime (core/)                     │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │  Loop    │  │ Harness  │  │ Canonical Messages│   │   │
│  │  │ (async   │  │ (配置,   │  │ (AgentMessage,    │   │   │
│  │  │  gen)    │  │  事件)   │  │  ToolResult...)   │   │   │
│  │  └──────────┘  └──────────┘  └──────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │                                  │
│  ┌────────────────────────▼────────────────────────────┐     │
│  │              统一工具路由                             │     │
│  │  ┌────────┐ ┌─────┐ ┌────────┐ ┌────────────────┐  │     │
│  │  │ 内置   │ │ MCP │ │ Skill  │ │Sub-agent/Plan  │  │     │
│  │  │(文件,  │ │     │ │        │ │  内部工具      │  │     │
│  │  │ Shell, │ │     │ │        │ │                │  │     │
│  │  │ 搜索)  │ │     │ │        │ │                │  │     │
│  │  └────────┘ └─────┘ └────────┘ └────────────────┘  │     │
│  └─────────────────────────────────────────────────────┘     │
│                           │                                  │
│  ┌────────────────────────▼────────────────────────────┐     │
│  │           上下文管理管线                              │     │
│  │  落盘 → 预算 → 裁剪(缓存感知) → 清理 →              │     │
│  │  摘要(85% 水位)                                      │     │
│  └─────────────────────────────────────────────────────┘     │
│                           │                                  │
│  ┌────────────────────────▼────────────────────────────┐     │
│  │         Providers (纯 httpx，零 SDK 依赖)            │     │
│  │  Anthropic API  ·  OpenAI-compatible  ·  Fake       │     │
│  └─────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
```

每次工具调用按以下顺序执行：

1. **权限门控**——静态规则或 Auto 分类器先决定 `allow` / `confirm` / `deny`
2. **人工确认**——敏感操作等待用户批准（`--yolo` 可跳过）
3. **PreToolUse Hook**——用户/项目级命令 Hook，任何异常均 fail-closed
4. **工具分发**——内置工具 / MCP / Skill / Sub-agent / 内部工具统一路由
5. **结果持久化**——大结果（>30 KB）先完整落盘，上下文只保留路径和预览
6. **上下文预算**——管线在下一轮模型调用前裁剪老化结果

---

## 技术深度解析

### 1. Fail-Closed 工具执行边界

权限系统是分层的——没有单一机制拥有最终决定权。六种模式提供渐进控制：

| 模式 | CLI 参数 | 行为 |
|------|----------|------|
| **Default** | *(默认)* | 只读操作走快路径，敏感操作按规则确认或拒绝 |
| **Plan** | `--plan` | 只读分析并生成计划，不直接修改项目 |
| **Accept Edits** | `--accept-edits` | 自动批准文件编辑，危险 Shell 仍需确认 |
| **Don't Ask** | `--dont-ask` | 自动拒绝所有需要人工确认的操作，适合非交互环境 |
| **Auto** | `--auto` | 由两阶段 LLM 分类器判断操作 *(实验能力)* |
| **Yolo** | `--yolo` | 跳过人工确认，仅建议在隔离环境中使用 |

这些模式与四层防御叠加：

| 层级 | 机制 | 故障模式 |
|------|------|----------|
| 权限模式 | 按工具的静态规则 + 模式分类器 | 未知工具 → 拒绝 |
| 人工门控 | `confirm` 操作需用户批准 | 超时 → 拒绝 |
| PreToolUse Hook | 任意命令行程序 | 崩溃 / 超时 / 非零退出 / 非法 JSON → **fail-closed** |
| 信任注册 | 项目 Hook 指纹（配置哈希 + 文件内容哈希 + 项目根目录） | 指纹不匹配 → 重新确认，`--yolo` 下也不例外 |

Hook 以子进程方式运行，仅继承最小环境（`PATH`、`HOME`、`SYSTEMROOT`）。API 密钥（`ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、`GITHUB_TOKEN`）和云凭证前缀（`AWS_*`、`AZURE_*`、`GOOGLE_*`）被**禁止**传入子进程。每个 Hook 从 stdin 接收 UTF-8 JSON，必须在可配置的超时时间内通过 stdout 返回 `{"action": "allow"}` 或 `{"action": "deny", "reason": "..."}`。

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "id": "block-force-push",
        "matcher": "run_shell",
        "command": ["python", ".claude/hooks/pre_shell.py"],
        "timeout_ms": 5000,
        "pass_env": ["POLICY_CONFIG_PATH"]
      }
    ]
  }
}
```

用户级 Hook 默认可信。项目级 Hook 首次匹配时必须由用户确认——即使使用 `--yolo` 也不会自动获得信任。信任记录保存在 `~/.lion-code/trusted-hooks.json`，使用复合指纹：**规范化项目根目录 + Hook ID + 完整配置哈希 + 所引用项目脚本内容的哈希**。任一组件变化，原信任记录不再匹配。

```json
{"action": "allow"}
```

```json
{"action": "deny", "reason": "当前项目禁止直接推送到主分支"}
```

需要管道或重定向的 Hook 可以显式启用 Shell 模式，信任确认时会显示额外风险警告：

```json
{
  "id": "legacy-policy",
  "matcher": "run_shell",
  "shell": true,
  "command": "python check.py | jq ."
}
```

**关键不变量：**Hook 返回 `allow` 不能绕过权限拒绝。权限门控始终最先执行。Hook 故障（崩溃、超时、畸形输出）是**基础设施故障**，不是策略拒绝——Agent 被告知"Hook 系统故障"，而非"你的操作被策略拒绝"。Hook 链以结构化结果记录每个已执行 Hook 的耗时与终态（`allow` / `deny` / `error`）。

### 2. 多级上下文管理

上下文不是在即将溢出时才做一次摘要，而是逐级处理不同来源的浪费：

| 阶段 | 触发条件 | 行为 | 缓存感知？ |
|------|----------|------|:---:|
| **大结果持久化** | 结果 > 30 KB | 全文落盘 → `~/.lion-code/tool-results/`；上下文保留路径 + 前 200 行预览 | — |
| **动态预算** | 利用率 > 50% | 限制单个工具结果长度，保留首尾信息 | — |
| **陈旧结果裁剪** | 利用率 > 60% | 将旧结果替换为占位符 `[result truncated]` | ✓ |
| **空闲清理** | 距上次 API 调用 > 5 分钟 | 清理更早的工具结果，保留最近 3 项 | ✓ |
| **全量摘要** | 利用率 > 85% | 用模型摘要历史，保留继续任务所需的决策、路径和状态 | — |

**缓存热度感知**是其中的核心洞察。当 Provider 的前缀缓存仍然温热（上次 API 调用 < 5 分钟前），系统会延迟裁剪旧结果——即使超过 60% 阈值——直到利用率达到 75% 的覆盖水位。这避免了改写缓存前缀，用少量 Token 缓冲换取显著更高的缓存命中率。

```python
# context/manager.py —— 缓存感知的裁剪决策
def _should_snip(self, state: ContextRuntimeState) -> bool:
    if state.utilization < self.policy.snip_start_ratio:
        return False
    # 缓存仍热 且 未超过热缓存覆盖水位？保留旧前缀。
    return not (
        self._cache_is_hot(state)
        and state.utilization < self.policy.hot_cache_override_ratio
    )
```

摘要系统使用**同一模型 Provider** 进行压缩——不依赖外部 LLM。摘要提示词保留具体决策、文件路径、命令、故障和剩余工作，而非生成泛化的 tl;dr。

### 3. Provider 无关的核心循环

Core Runtime 是一个**单一异步生成器**（`core/loop.py` 中的 `run_agent_loop`），驱动整个工具使用周期。它完全 Provider 无关——同一循环同时适配 Anthropic、OpenAI-compatible 和测试用 Fake Provider：

```python
async def run_agent_loop(
    *,
    provider: ModelProvider,
    model: str,
    system: str,
    messages: list[AgentMessage],
    tools: list[AgentTool],
    get_system: GetSystem | None = None,          # 每轮动态系统提示
    get_tools: GetTools | None = None,             # 每轮动态工具解析
    prepare_context: PrepareContext | None = None,  # 上下文投影钩子
    signal: CancellationToken | None = None,
    get_steering_messages: Callable | None = None,  # 运行中 steer
    get_follow_up_messages: Callable | None = None, # 本轮结束 follow-up
    ...
) -> AsyncIterator[AgentEvent]:
```

三个动态钩子实现了每轮自适应，无需重建运行时：

- **`get_system()`**——允许 Plan 模式、Skill 激活和工具变更更新系统提示
- **`get_tools()`**——动态发现的 MCP 工具、延迟激活的 Skill、按 Sub-agent 的工具集视图
- **`prepare_context(messages)`**——裁剪、预算、注入 Memory Overlay 到投影上下文

并行工具执行将相邻的并行能力工具分组为并发批次，串行工具则作为屏障：

```python
def _tool_call_batches(calls, tools):
    """将相邻并行调用分组；串行工具作为屏障。"""
    batches, parallel_batch = [], []
    for call in calls:
        tool = tools.get(call.name)
        if tool is not None and tool.execution_mode == "parallel":
            parallel_batch.append(call)
        else:
            if parallel_batch:
                batches.append(parallel_batch)
                parallel_batch = []
            batches.append([call])
    if parallel_batch:
        batches.append(parallel_batch)
    return batches
```

### 4. 会话持久化与崩溃恢复

会话使用 **JSONL** 格式（每行一个 JSON 对象），选择 JSONL 而非 JSON 就是为了崩溃恢复——会话结束时的不完整写入最多丢失不完整的最后一行，而非整个文件：

```python
# session/storage.py —— 追加 + fsync，清掉崩溃残留半行
async def _append_entry(self, entry: dict) -> None:
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
```

旧 JSON 会话透明发现与迁移——源文件永不修改，只读不写。

### 5. Memory 架构与隔离式整合

Memory 系统在三个层级运行：

| 层级 | 作用域 | 触发方式 | 写入权限 |
|------|--------|----------|:---:|
| **Session** | 当前对话 | 自动（JSONL） | Agent |
| **Memory** | 按项目的持久事实 | `/dream` 命令 | 隔离只读 Agent → 计划 → 主进程校验 |
| **Skill** | 可复用工作流 / 流程 | `/learn` 命令 | Meta-Skill 分析 → 用户确认 |

`/dream` 命令使用一个**隔离式 Agent**，该 Agent：
- 仅有**只读**文件和搜索权限
- **不能**写文件、执行 Shell、调用 MCP 或启动其他 Agent
- 输出结构化 JSON 计划：`{created: [...], updated: [...], deleted: [...]}`
- 主进程随后校验文件名、Memory 类型、内容大小和运行前快照，再集中写入并重建索引

这种设计阻止了模型直接操作 Memory 文件系统，同时仍能自动整合重复信息、清理过期条目。

### 6. Textual TUI 与实时流式渲染

TUI 基于 [Textual](https://textual.textualize.io/) 构建，是一个完整的终端应用程序，而非一个带样式的 REPL：

```
┌─────────────────────────────────────────────────────────┐
│  Lion Code — claude-sonnet-5 · 会话: abc123              │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  🤖 我来分析代码结构...                                  │
│                                                         │
│  ┌─ read_file (src/auth.py) ───────────────────────┐   │
│  │  [1] import jwt                                  │   │
│  │  [2] def verify_token(token): ...                │   │
│  │  [120 行 · 4.2 KB]                               │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─ run_shell (pytest tests/auth/ -q) ─────────────┐   │
│  │  3 passed, 1 failed                               │   │
│  │  FAILED tests/auth/test_login.py::test_refresh   │   │
│  │  AssertionError: expected 200, got 401            │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  > 修一下 refresh token 的测试                           │
│  [Tab:补全] [Ctrl+S:steer] [Ctrl+O:follow-up]           │
└─────────────────────────────────────────────────────────┘
```

TUI 核心能力：

- **流式 Markdown 渲染**——模型回复随 Token 到达逐字渲染
- **工具卡片**——每次工具调用和结果以独立可展开卡片展示
- **路径自动补全**——Tab 补全项目目录下的文件路径
- **命令/Skill 补全**——斜杠命令和 Skill 名称自动提示
- **会话内切换模型**——不退出即可更换 Provider / 模型 / Thinking 档位
- **会话恢复**——从历史会话列表选择并恢复完整上下文
- **Steer & Follow-Up**——Agent 运行中注入指令或任务结束后追加消息
- **Plan 审批弹窗**——模态覆盖层审阅和选择执行方式

---

## 可复现评测

项目包含两套正式评测——不是临时演示，而是带有统计分析的受控实验。

### 上下文管理评测

**实验设计：** 9 项编码任务 × 3 档上下文负载（60–70%、75–85%、85–95%）× 2 种策略 × 2 次重复 = **54 个真实 API 会话**。

**结果**（`managed` vs `summary_only`）：

| 指标 | `summary_only` | `managed`（Lion Code） | Δ |
|---|---|---|---|
| 成功任务 | 13/18 | **14/18** | +5.6% |
| 累计输入 Token | 14,560,434 | **12,872,748** | −11.6% |
| 峰值输入 Token | 175,546 | **145,581** | −17.1% |
| API 费用（元） | 4.6672 | **4.4865** | −3.9% |

- Token 缩减具有统计显著性（配对 bootstrap 95% CI: [9.1%, 14.4%]）
- 费用下降方向利好但 95% 置信区间尚未跨 0（CI: [−7.2%, 13.6%]）
- 缓存命中率在热感知策略下从 64.2% 提升至 66.6%

离线校验（无 API 费用）：

```bash
python benchmarks/context_management/formal_benchmark.py
```

完整在线评测（产生真实 API 费用）：

```bash
export OPENAI_API_KEY="<你的 API Key>"
python benchmarks/context_management/formal_benchmark.py --online \
  --base-url "https://api.deepseek.com" \
  --model "deepseek-v4-flash" \
  --budget-cny 15
```

所有原始数据、任务定义和统计分析均在 `benchmarks/context_management/results/` 中。

### Agent 端到端评测

一个面向 Coding Agent 的生产级评测框架：

- **任务语料库**——版本化、哈希钉定的任务定义，带 SHA-256 完整性校验（`corpus_assets/public_catalog.v1.json`）
- **Orchestrator**——管理 Worker 生命周期、重试和超时
- **Checkpoint 系统**——评测运行可恢复
- **Verifier**——每项任务的结构化通过/失败判定
- **回归检测**——自动对比基线并标记退化
- **外部 Anchor**——SWE-bench 实时验证集成

```bash
python -m benchmarks.agent_e2e --help
```

---

## 项目结构

```
Lion-Code/
├── lion_code/                  # 主包 (~43K 行)
│   ├── __main__.py             # CLI、TUI 与 REPL 入口
│   ├── agent.py                # Agent 组装、工具路由与宿主能力 (~94 KB)
│   ├── agent_runtime.py        # Agent ↔ Core Runtime 桥接
│   ├── core/                   # 可移植 Agent 循环（从 Hugging Face Tau 吸收并演化）
│   │   ├── loop.py             # 异步生成器：整个工具使用周期
│   │   ├── harness.py          # 配置、事件总线、消息队列
│   │   ├── messages.py         # 规范消息类型（AgentMessage、ToolResult...）
│   │   ├── tools.py            # 工具定义、执行协议、并行批处理
│   │   ├── provider.py         # ModelProvider 抽象
│   │   └── provider_events.py  # 流式事件（delta、done、error）
│   ├── providers/              # 纯 httpx HTTP Provider（零 SDK 依赖）
│   │   ├── http.py             # 共享 HTTP 客户端（重试/流式）
│   │   ├── anthropic.py        # Anthropic Messages API 适配
│   │   ├── openai_compatible.py# OpenAI-compatible 适配
│   │   ├── model_limits.py     # 运行时上下文窗口发现
│   │   └── fake.py             # 测试用确定性 Fake Provider
│   ├── context/                # 多级上下文管理
│   │   ├── manager.py          # 编排管线
│   │   ├── policy.py           # 可配置阈值与预算
│   │   ├── projector.py        # 消息投影（裁剪/占位/清理）
│   │   ├── compaction.py       # 模型驱动摘要
│   │   ├── estimator.py        # Token 估算
│   │   └── limits.py           # 模型特定上下文限制
│   ├── tooling/                # 工具执行运行时
│   │   ├── runtime.py          # 统一执行入口（pre/post 中间件）
│   │   ├── builtin.py          # 文件、Shell、搜索、Web 工具
│   │   ├── mcp.py              # MCP 客户端集成
│   │   ├── permission.py       # 静态权限规则 + Auto 分类器
│   │   ├── registry.py         # 工具注册与解析
│   │   ├── middleware.py       # 拦截器链
│   │   └── result_store.py     # 大结果持久化存储
│   ├── application/            # 前端消费的会话边界
│   │   ├── session.py          # LionCodingSession：事件桥接 + 命令分发
│   │   ├── commands.py         # 斜杠命令协议
│   │   ├── events.py           # 高层会话事件
│   │   └── skills.py           # Skill 注册
│   ├── tui/                    # Textual 终端 UI (~5K 行)
│   │   ├── app.py              # 主 TUI 应用、屏幕、组件 (~1.4K 行)
│   │   ├── prompt_input.py     # 带补全、粘贴、快捷键的输入框
│   │   ├── widgets.py          # Transcript、工具卡片、Markdown 渲染
│   │   ├── themes.py           # 内置 + 自定义主题加载
│   │   └── autocomplete.py     # 路径/命令/Skill 补全引擎
│   ├── hooks.py                # PreToolUse 命令 Hook (~23 KB)
│   ├── memory.py               # 项目 Memory 文件系统 (~14 KB)
│   ├── memory_runtime/         # Memory Overlay 注入（含预算限制）
│   ├── dream.py                # 隔离式 Memory 整合 Agent (~19 KB)
│   ├── skills.py               # Skill 发现、解析与 /learn 创建
│   ├── session_runtime/        # JSONL 记录、旧 JSON 迁移、Repository
│   ├── subagent.py             # Sub-agent 配置与启动
│   ├── mcp_client.py           # MCP 协议客户端
│   ├── autonomy.py             # /goal、/loop、Auto 模式契约
│   ├── prompt.py               # System Prompt 拼装
│   └── config.py               # API 配置
├── benchmarks/
│   ├── context_management/     # 正式上下文评测（54 个 API 会话）
│   │   ├── formal_benchmark.py # 离线校验 + 在线跑测入口
│   │   ├── formal_dataset.json # 9 任务 × 3 负载水平
│   │   ├── formal_tasks.py     # 任务定义与验证标准
│   │   └── results/            # 原始数据与统计分析
│   └── agent_e2e/              # 生产级评测框架
│       ├── orchestrator.py     # Worker 生命周期与调度
│       ├── corpus.py           # 版本化、哈希钉定的任务目录
│       ├── verifier.py         # 结构化通过/失败判定
│       ├── regression.py       # 基线对比与退化检测
│       └── external_anchor.py  # SWE-bench 集成
├── tests/                      # 518 条测试
│   ├── core/                   # Core Runtime 单元测试
│   ├── context/                # 上下文管理测试
│   ├── integration/            # 集成测试
│   ├── tui/                    # TUI 组件测试
│   └── ...
├── docs/
│   ├── tui.md                  # TUI 使用说明、快捷键与配置
│   └── tui-migration-audit.md  # Tau → Lion 迁移审计
├── pyproject.toml              # 构建、依赖、CLI 入口
├── UPSTREAM.md                 # 上游（Tau）文件映射与同步日志
├── MAINTENANCE.md              # 维护台账与瘦身日志
└── README.md
```

---

## 快速开始

**环境要求：** Python 3.12+

```bash
git clone https://github.com/muyuzhong/Lion-Code.git
cd Lion-Code
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e .
```

### Anthropic API

```bash
export ANTHROPIC_API_KEY="<你的 API Key>"
lion-code "读取当前项目并总结最重要的执行路径"
```

### OpenAI-compatible API

```bash
export OPENAI_API_KEY="<你的 API Key>"
export OPENAI_BASE_URL="https://api.openai.com/v1"
lion-code --model "gpt-4o" "检查这个项目并运行测试"
```

### 常用命令

```bash
lion-code --plan "设计一个重构方案"                   # 只读规划
lion-code --accept-edits "修复测试并说明原因"          # 自动批准编辑
lion-code --max-cost 0.50 --max-turns 20 "完成任务 X"  # 预算控制
lion-code --resume                                     # 恢复最近会话
lion-code                                              # 启动 Textual TUI
lion-code --repl                                       # 纯文本 REPL
```

### REPL 命令

| 命令 | 作用 |
|---------|------|
| `/clear` / `/new` | 清空对话，开始新会话 |
| `/plan` | 切换 Plan 模式（只读分析） |
| `/cost` | 查看 Token 使用量和费用 |
| `/compact` | 手动压缩当前对话 |
| `/task` | 查看当前项目的目标、活动任务与下一步 |
| `/task switch <内容>` | 切换活动任务，并把旧任务保留为待继续事项 |
| `/task done` | 结束活动任务，保留完成摘要并准备受限长期候选 |
| `/session-memory` | 查看当前项目的跨会话短期工作状态 |
| `/handoff` | 生成并保存下一 Session 可继续的交接摘要 |
| `/dream` | 将受限候选与最近项目 Session 整理为 Auto Memory |
| `/learn` | 判断并沉淀当前会话中的可复用经验 |
| `/memory` | 查看已保存的 Memory |
| `/skills` | 查看可用 Skill |
| `/goal <条件>` | 围绕停止条件继续迭代 |
| `/loop <任务>` | 按间隔或模型自定时重复任务 |
| `/<skill-name>` | 调用一个用户可执行 Skill |
| `exit` / `quit` | 退出程序 |

项目上下文按 `AGENTS.md`（兼容 `CLAUDE.md`）→ Session Memory → Auto Memory 的优先级
临时投影给 Provider；不会写入 canonical 对话或 JSONL。`/clear` 只开启新对话，保留当前
项目或 worktree 的 Session Memory；`/dream` 只接收稳定偏好、明确反馈、已验证决策及原因、
可复用失败经验和外部引用等候选，不能自动改写 `AGENTS.md`。

### TUI（Textual）

裸运行 `lion-code` 启动 TUI。主要快捷键：

| 快捷键 | 作用 |
|----------|------|
| `Ctrl+K` | 命令补全 |
| `Ctrl+R` | 会话选择器 |
| `Ctrl+P` | 模型选择器 |
| `Ctrl+M` | 模型/API 配置 |
| `Ctrl+T` | 切换 Thinking 可见性 |
| `Ctrl+O` | 展开/折叠工具结果 |
| `Ctrl+B` | 切换会话侧栏 |
| `Ctrl+N` | 新建会话 |
| `Esc` | 关闭补全或中止任务 |
| `Tab` / `↑` / `↓` | 移动补全选择 |
| `Shift+Tab` | 循环 Thinking 档位 |
| `Alt+Enter` | 以 Follow-Up 提交（运行中） |
| `Ctrl+D` | 退出 TUI |

TUI 支持实时路径补全、命令/Skill 提示、流式 Markdown、可展开工具卡片，以及运行中 Steer / Follow-Up 消息注入。模型、API 地址、Thinking 档位和主题均可在会话内切换。详见 [`docs/tui.md`](docs/tui.md)。

### 运行时数据

所有持久状态位于 `~/.lion-code/`：

```text
~/.lion-code/
├── sessions/           # JSONL 会话记录（旧 JSON 透明迁移）
├── projects/           # 按项目隔离的 Memory 文件 + MEMORY.md 索引
├── tool-results/       # 超大工具结果全文（>30 KB）
├── trusted-hooks.json  # 项目 Hook 信任指纹
├── config.json         # 已保存的 API 配置
└── tui.json            # TUI 主题、快捷键和通知偏好
```

---

## 设计取舍

这张表记录了每个关键决策及其代价：

| 问题 | Lion Code 的选择 | 代价与边界 |
|------|-----------------|-----------|
| 超大结果挤占上下文 | 先完整落盘，再提供预览和可回读路径 | 增加本地 I/O，但避免永久丢失内容 |
| 立即裁剪能减少 Token | 缓存仍热时延迟改写旧前缀 | 短期保留更多 Token，换取更高缓存复用 |
| Hook 故障时是否继续执行 | 所有异常均 fail-closed | Hook 故障降低可用性，但不会静默绕过安全边界 |
| Memory 整合安全 | 隔离只读 Agent → 计划 → 主程序校验 → 应用 | 多一道结构校验，换取路径和删除边界可控 |
| 何时从经验中学习 | 仅用户显式执行 `/learn` 或 `/dream` | 不做后台自动沉淀，用户保留最终控制权 |
| 防止覆盖外部修改 | 写文件前要求先读，并校验 mtime | 多一次读取，换取更清晰的并发修改保护 |
| Provider SDK 依赖 | 纯 httpx，核心路径零 SDK 导入 | 必须直接实现 API 适配器 |
| 会话格式 | JSONL 而非 JSON | 读取器略复杂，但崩溃恢复更安全 |

---

## 测试

```bash
# 完整测试套件（518 条）
python -m pytest -q

# 编译检查
python -m compileall -q lion_code tests

# 离线 Benchmark 校验（无 API 费用）
python benchmarks/context_management/formal_benchmark.py
```

---

## 上游溯源

Lion Code 的 Core Runtime（`lion_code/core/`）从 [Hugging Face Tau](https://github.com/huggingface/tau)（Release 0.3.3，commit `d597a8a`，MIT License）以"源码吸收 + 本地演化"方式引入。选择源码引入而非包依赖，避免了 `tau_agent.UserMessage` 与 `lion_code.core.UserMessage` 两套运行时类型并存的问题，同时允许对循环、Harness 和消息类型进行深度修改。

详见 [`UPSTREAM.md`](UPSTREAM.md) 查看完整的文件级映射、修改日志与同步流程。

---

## 路线图

- [ ] **演示素材**——终端 GIF、代表性任务记录和结果截图
- [ ] **Auto Mode**——补全默认规则资产，补齐流程测试，标记为稳定能力
- [ ] **Goal 持久化**——将 `/goal` 变为可恢复的持久任务系统，支持独立验证
- [ ] **E2E 验证**——为 `/learn` 与 `/dream` 补充真实后端集成测试
- [ ] **CI 管线**——跨平台（Windows、Linux）、多 Python 版本 CI，展示测试状态徽章
- [ ] **评测扩展**——更多任务多样性和对抗性测试用例

---

## 许可证

[MIT](LICENSE)

Lion Code 包含来自 [Hugging Face Tau](https://github.com/huggingface/tau) 的代码（MIT）。详见 [`licenses/TAU_LICENSE`](licenses/TAU_LICENSE)。
