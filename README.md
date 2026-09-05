<div align="center">

# Lion Code

**以最小 Agent Kernel 为核心、面向可靠 Coding Agent 构建的可组合运行时与完整客户端**<br/>
*A composable runtime for building reliable Coding Agents, built around a minimal agent kernel.*

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Desktop: Electron & React](https://img.shields.io/badge/Desktop-Electron%20%7C%20React%2019-61DAFB?logo=react&logoColor=white)](desktop/)
[![License: MIT](https://img.shields.io/badge/License-MIT-2ea44f.svg)](LICENSE)
[![CI](https://github.com/muyuzhong/Lion-Code/actions/workflows/ci.yml/badge.svg)](https://github.com/muyuzhong/Lion-Code/actions/workflows/ci.yml)
[![Architecture: import--linter](https://img.shields.io/badge/Architecture-Import%20Linter%20Enforced-blueviolet.svg)](pyproject.toml)
[![Status: Active](https://img.shields.io/badge/Status-Active%20Development-f59e0b.svg)](#路线图)

[产品形态](#产品形态) · [核心特性](#核心特性) · [快速开始](#快速开始) · [系统架构](#系统架构) · [工程机制](#工程机制) · [评测与质量](#评测与质量工程) · [项目结构](#项目结构)

</div>

---

## 产品形态

Lion Code 提供覆盖桌面 GUI、终端 TUI、命令行 CLI 以及 Python SDK 的交互矩阵：

### 1. Electron 桌面客户端（Desktop GUI）

基于 **Electron + React 19 + `@assistant-ui/react`** 构建，由独立的 API-only Python Sidecar（FastAPI / WebSocket）托管会话运行时，实现严格的进程隔离：

<p align="center">
  <img src="docs/assets/desktop-preview.png" alt="Lion Desktop Client Preview" width="850" />
</p>

- **流式交互与状态呈现**：打字机流式回复，工具调用卡片与模型思考过程（Thinking）可自由展开折叠。
- **工作面板（WorkPanel）**：
  - 文件资源视图：点击对话中的文件路径或产物链接，实时查看与语法高亮。
  - Git 审查视图：提供只读的工作区变更审查快照与 Diff 对比，改动一目了然。
  - 内置浏览器：直接呈现 Web 页面与抓取结果。

### 2. Textual 终端 TUI（Terminal GUI）

基于 [Textual](https://textual.textualize.io/) 构建的全屏终端应用，全键盘快捷驱动：

<p align="center">
  <img src="docs/assets/tui-preview.png" alt="Lion Textual TUI Preview" width="800" />
</p>

- 快捷键支持：`Ctrl+P` 切换模型，`Ctrl+R` 浏览与恢复会话，`Ctrl+M` 配置 API，`Ctrl+B` 切换侧边栏。
- 动态补全：按下 `Tab` 键自动补全文件路径、斜杠命令或 Skill 名称。
- 详见：[`docs/tui.md`](docs/tui.md)。

### 3. Headless CLI 与交互 REPL

- 单次执行：`lion-code "任务描述"`，执行完成后自动退出，适配自动化与 CI。
- 交互 REPL：`lion-code --repl` 启动轻量纯文本交互，支持 `/clear`、`/plan`、`/cost` 等命令。

### 4. 嵌入式 Python SDK

支持作为标准 Python 库导入并嵌入现有系统：

```python
import asyncio
from lion_code import build_coding_agent

async def main():
    agent = build_coding_agent(api_key="your-api-key")
    result = await agent.run("分析当前目录结构")
    print(result.final_text)
    await agent.close()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 核心特性

在长时程复杂任务中，系统的可靠性取决于内核精简度、扩展隔离性、执行边界与上下文控制能力。

<p align="center">
  <img src="docs/assets/lion-core-concept.png" alt="Lion Code Concept Architecture" width="600" />
</p>

- **Minimal Agent Kernel（最小核心内核）**：核心（[`lion_code/core/loop.py`](lion_code/core/loop.py)）仅作为一个单一异步生成器驱动循环、工具批处理与取消信号（`CancellationToken`），Provider 完全解耦，零业务污染。
- **Composable Capabilities（可组合能力平面）**：Plan、Skill、SubAgent、Memory、Git 等功能正交解耦，由 `CapabilityRegistry` 统一管理装配，遵循“优先扩展 Agent，而不是修改 Agent”原则，支持外部引擎替换（详见 [`docs/advanced-capability-guide.md`](docs/advanced-capability-guide.md)）。
- **Reliable Execution（Fail-Closed 执行硬边界）**：提供 `default` / `accept-edits` / `dont-ask` / `yolo` 四级权限；PreToolUse Hook 运行于独立子进程且隔离敏感环境变量；写操作强校验读取新鲜度防并发覆写；工作区快照支持一键回滚；出站域名白名单与密钥全文脱敏（详见 [`docs/security-design.md`](docs/security-design.md)）。
- **Long-running Context（缓存感知长上下文工程）**：超大工具输出（>30 KB）自动落盘；前缀缓存处于温热状态（< 5 分钟）时延迟裁剪旧结果以保全 Prefix Cache；超高负载时由同模型执行结构化自压缩（详见 [`docs/architecture/context-lifecycle.md`](docs/architecture/context-lifecycle.md)）。

---

## 快速开始

### 1. 环境准备

需要 **Python 3.12+**：

```bash
git clone https://github.com/muyuzhong/Lion-Code.git
cd Lion-Code
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -e .
```

### 2. 配置模型 API Key

```bash
# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# OpenAI 或兼容服务（DeepSeek、SiliconFlow 等）
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.openai.com/v1"
```

> 提示：在 TUI 界面中可直接按 `Ctrl+M` 打开图形化面板配置，无需手动设置环境变量。

### 3. 运行方式

```bash
# 启动终端 TUI
lion-code

# CLI 单次执行
lion-code "读取并总结项目入口"
lion-code --plan "生成重构方案"                   # Plan 只读模式
lion-code --accept-edits "修复测试用例"           # 自动批准编辑
lion-code --max-cost 0.50 --max-turns 20 "执行任务" # 预算与轮次限制
lion-code --resume                               # 恢复上次会话

# 启动桌面客户端（需 Node.js >= 22）
cd desktop && npm install && npm run dev
```

---

## 系统架构

运行时数据流（Runtime Flow）与构建装配流（Composition Flow）正交解耦：

### 1. 运行时数据流

<p align="center">
  <img src="docs/assets/architecture-runtime.png" alt="Runtime Data Flow Architecture" width="800" />
</p>

### 2. 组合构建架构

装配根（[`lion_code/composition/agent_builder.py`](lion_code/composition/agent_builder.py)）单向拓扑构建，杜绝循环依赖：

<p align="center">
  <img src="docs/assets/architecture-composition.png" alt="Composition Architecture" width="800" />
</p>

- **Profile 预设**：
  - `MinimalProfile`：零内置 Capability 的最小产品，仅装配传入工具。
  - `CodingProfile`：内置编码工具集与安全防护 Harness。
  - `FullProfile`：包含全套内置能力（Skill、SubAgent、Plan、Memory 等），支持外部扩展覆盖。
- **架构分层约束（Import-Linter）**：
  - `core` 严禁反向依赖上层运行时与能力；
  - `providers` 仅依赖 `core` 抽象，零三方 SDK 绑定（纯 `httpx`）；
  - `capabilities` 绝不依赖 Agent 宿主与 UI 应用层；
  - 详见：[`docs/architecture/boundaries.md`](docs/architecture/boundaries.md)。

---

## 工程机制

### 1. Fail-Closed 工具拦截流水线

<p align="center">
  <img src="docs/assets/tool-execution-boundary.png" alt="Tool Execution Boundary Flow" width="750" />
</p>

Hook 执行超时、崩溃或异常退出均 Fail-Closed 熔断阻断；敏感凭据严禁传入 Hook 子进程；复合指纹防篡改。

### 2. 多级上下文预算控制

| 阶段 | 触发水位 | 处理方式 | 缓存保护 |
|:---|:---|:---|:---:|
| **大结果落盘** | 工具输出 > 30 KB | 完整落盘至本地；上下文仅留预览与回读路径 | - |
| **动态预算** | 窗口利用率 > 50% | 动态压缩单次工具输出长度 | - |
| **陈旧结果裁剪** | 窗口利用率 > 60% | 历史工具结果替换为占位符 | 是 |
| **空闲清理** | 距上次调用 > 5 分钟 | 清理更早轮次工具输出，保留最近 3 项 | 是 |
| **模型自摘要** | 窗口利用率 > 85% | 同模型提取决策、关键路径与剩余任务结构化压缩 | - |

### 3. 会话持久化与崩溃恢复

- **Append-Only JSONL**：逐行追加伴随 `fsync`，进程崩溃不破坏历史完整性，启动时自动迁移旧版 JSON。
- **Supervisor 检查点**：长任务状态（Goal / Phase / Attempt）由 Supervisor 独立维护轻量 Checkpoint，与底层会话历史正交解耦（详见 [`docs/architecture/checkpoint-recovery.md`](docs/architecture/checkpoint-recovery.md)）。

---

## 评测与质量工程

- **上下文管理评测** ([`benchmarks/context_management`](benchmarks/context_management/README_CN.md))：验证高频工具调用下的截断落盘、缓存复用与 Token 节约率。
- **端到端 Agent 评测** ([`benchmarks/agent_e2e`](benchmarks/agent_e2e))：真实编码任务评测集，支持 DeepEval 语义轨迹校验与自动化回归防恶化拦截。
- **质量门禁命令**：
  ```bash
  lint-imports     # 架构分层约束门禁
  ruff check .     # 代码风格检查
  mypy lion_code   # 静态类型检查
  pytest           # 单元与集成测试套件
  ```

---

## 项目结构

```text
Lion-Code/
├── lion_code/                  # Python 核心运行时
│   ├── core/                   # 最小 Agent Kernel 与循环驱动 (loop.py)
│   ├── runtime/                # Agent 运行时状态协调
│   ├── composition/            # Profile 预设与装配根 (agent_builder.py)
│   ├── capabilities/           # Memory / Plan / Skill / SubAgent 等正交能力
│   ├── tooling/                # 工具执行边界、隔离 Hook、快照与出站防护
│   ├── context/                # 多级上下文管理与缓存感知裁剪
│   ├── providers/              # 纯 httpx HTTP Provider（零三方 SDK 依赖）
│   ├── session_runtime/        # Append-Only JSONL 会话存储与迁移
│   ├── supervisor.py           # 任务目标调度与 Checkpoint 协调
│   ├── tui/                    # Textual 终端客户端
│   └── sidecar.py              # 桌面端 API-only Sidecar 入口
├── desktop/                    # Electron + React 19 桌面客户端
│   ├── src/main/               # 窗口管理与 Sidecar 进程托管
│   ├── src/renderer/           # 前端交互与 WorkPanel 工作面板
│   └── e2e/                    # Playwright 端到端测试
├── benchmarks/                 # 上下文管理与 Agent 端到端评测集
├── tests/                      # 单元、集成与架构测试
└── docs/                       # 设计文档与使用指南
```

---

## 路线图

- [x] 最小 Agent Kernel：异步生成器事件驱动循环与 Provider 解耦
- [x] 缓存感知长上下文：超大结果落盘、热度感知延迟裁剪与模型自压缩
- [x] Fail-Closed 安全执行边界：子进程隔离 Hook、出站防护与数据脱敏
- [x] 多端交互矩阵：Textual 终端 TUI、Headless CLI 与 Electron 桌面客户端
- [x] 桌面工作面板（WorkPanel）：文件资源查看、Git 变更审查快照与内置浏览器
- [ ] 评测集持续扩展：扩充现实大型仓库重构任务与对抗性用例

---

## 许可证

本项目采用 [MIT 许可证](LICENSE)。
