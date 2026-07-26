# 上游溯源(UPSTREAM)

Lion-Code 以「源码吸收 + 本地演化」方式引入 Hugging Face Tau 的通用运行时,
不依赖外部 `tau-ai` 发行包(避免 `tau_agent.UserMessage` 与
`lion_code.core.UserMessage` 两套运行时类型并存,以及整个 Tau 应用层被连带安装)。

## 上游仓库

- 仓库:<https://github.com/huggingface/tau>
- License:MIT(全文见 [`licenses/TAU_LICENSE`](licenses/TAU_LICENSE))
- 当前同步基线:`d597a8a`(Release 0.3.3,2026-07-25)
- 最近比对时间:2026-07-27(逐文件 `git diff --no-index`,详见
  [`docs/tui-migration-audit.md`](docs/tui-migration-audit.md) §1)

## 导入模块映射

| 上游 | Lion 落点 | 引入方式 |
|---|---|---|
| `src/tau_agent/` | `lion_code/core/` | 已吸收(PR #7) |
| `src/tau_ai/` 子集 | `lion_code/providers/` | 已吸收(PR #8);`env.py` → `config.py` |
| `src/tau_coding/tui/` | `lion_code/tui/` | 迁移中(见审计文档阶段 2-3) |
| `src/tau_coding/` 其余业务层 | 不引入 | Lion 使用自有 tooling/context/session_runtime/application |

未吸收的 tau_ai 模块:`google.py`、`mistral.py`、`openai_codex.py`
(Lion 当前只支持 OpenAI-compatible 与 Anthropic 两类后端;`fake.py` 已为测试吸收)。

## 本地修改摘要(相对上游 0.3.3)

`lion_code/core/`:

- `tools.py`:`AgentToolResult` 增加 `is_error`,保留权限拒绝/Hook 拒绝/
  新鲜度失败等宿主结构化错误。
- `loop.py`:新增 `get_tools`/`get_system` 每轮解析、`prepare_context` 钩子
  (上下文投影/Memory 注入接入点)、并行工具分批执行、terminate 全量判定。
- `harness.py`:配置增加上述三钩子;中断修复的 ToolResult 以 Message 事件
  通知持久化订阅者。
- `session/storage.py`:追加前 fsync 并截断崩溃残留半行。
- `session/memory.py`:合成摘要 UserMessage 携带时间戳。
- 其余文件仅 import 路径改名(`tau_agent.*` → `lion_code.core.*`)。

`lion_code/providers/`:

- 新增 `factory.py`(不读环境变量的 Provider 组装)。
- `fake.py`:吸收自上游,供应用层/TUI 测试。
- 其余文件仅 import 路径改名与 docstring 本地化;`config.py` 对应上游 `env.py`。

## 同步流程

1. 浅克隆上游到临时目录,`git log -1` 记录基线 commit。
2. `git diff --no-index` 逐文件比对 `src/tau_agent` ↔ `lion_code/core`、
   `src/tau_ai` ↔ `lion_code/providers`,区分「本地演化」与「上游新增」。
3. 上游修复/特性择优回灌(例:anthropic `thinking_mode == "disabled"`
   显式 payload,已于 2026-07-27 同步)。
4. 更新本文件的基线 commit 与比对时间。
