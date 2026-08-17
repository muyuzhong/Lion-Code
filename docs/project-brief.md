# Lion Code 项目情况说明（给面试辅导老师）

> 这份文档是对项目的真实描述，所有数字都可以复核，没有包装。
> 文末「值得一提的点」是我认为比较独特、放简历上能扛追问的部分，同样是如实描述。

## 一句话定位

Lion Code 是我个人从零做的一个轻量级 Python Coding Agent（命令行 + 终端 TUI），
对标 Claude Code 这类工具的最小可用实现：模型在一个循环里调用工具完成任务，
重点不在"能跑通"，而在工具执行安全、长会话上下文管理、经验复用和可复现评测。

## 基本事实（2026-08-04 实测）

- 仓库：github.com/muyuzhong/Lion-Code，MIT License
- 语言/运行时：Python 3.12+
- 代码规模：主包 `lion_code/` 约 **23,700 行**，测试约 **15,800 行**
- 测试：**577 条通过**、6 条跳过（`pytest -q` 实测约 59 秒）
- Git 历史：237 个 commit，首个提交 2026-07-21（期间做过一次核心运行时的整体迁移融合，core/providers/session/context/tooling 等层是从早期项目演进合并进来的）
- 依赖极少：pydantic、rich、textual、pygments、anyio、httpx。**Provider 层零 SDK**，Anthropic 和 OpenAI 兼容协议都是直接用 httpx 自己实现的适配器
- 安装后是真实可用的 CLI：`pip install -e .` 得到 `lion-code` 命令，支持一次性 prompt、REPL、Textual TUI、会话恢复

## 架构（真实分层）

```
CLI / Textual TUI
  └─ application/session.py   会话边界：事件桥接、斜杠命令、Skill 注册
       └─ agent.py            工具路由与宿主能力（约 2K 行，从 2397 行逐步瘦身到 2070）
            └─ core/          Provider 无关的运行时
                 ├─ loop.py       单一异步生成器驱动整个工具调用周期
                 ├─ messages.py   规范消息类型
                 └─ provider.py   ModelProvider 抽象
            ├─ providers/       anthropic / openai_compatible / fake（纯 httpx）
            ├─ context/         上下文管理管线（预算/裁剪/摘要/Token 估算）
            ├─ tooling/         权限、Hook、大结果落盘
            ├─ context + session 上下文管理与 JSONL 会话持久化
            └─ tui/             Textual 终端 UI（约 5K 行）
```

## 核心机制（实现层面的真实情况）

### 1. 工具执行安全：fail-closed 分层防线

- 6 种权限模式（default / plan / accept-edits / dont-ask / auto / yolo），从人工确认到全放行渐进
- 四层防御叠加：静态权限规则 → 人工确认 → PreToolUse Hook → 项目 Hook 信任注册
- Hook 以子进程运行，**环境变量白名单**（只继承 PATH/HOME/SYSTEMROOT），`ANTHROPIC_API_KEY`、`AWS_*` 等密钥被显式禁止传入
- 项目级 Hook 的信任指纹是复合的：项目根目录 + Hook ID + 配置哈希 + 脚本内容哈希，任一变化就要重新确认，`--yolo` 也不豁免
- 一个刻意维护的不变量：**Hook 故障（崩溃/超时/畸形输出）全部按拒绝处理**，而且报告为"基础设施故障"而不是"策略拒绝"，避免模型把故障当成策略信号去学习绕过

### 2. 多级上下文管理（带缓存热度感知）

不是快溢出时做一次摘要，而是 5 级管线逐级处理：大结果落盘（>30KB 全文存盘、上下文只留路径+预览）→ 动态预算（>50%）→ 陈旧结果裁剪（>60%）→ 空闲清理（>5 分钟无调用）→ 全量摘要（>85%）。

其中一个自己做的设计决策：**裁剪是缓存感知的**——如果 Provider 前缀缓存还热（距上次调用 <5 分钟），即使过了 60% 阈值也延迟改写旧前缀，直到 75% 才动手。动机是改写旧消息会作废整段前缀缓存，用一点 Token 缓冲换缓存命中率。

### 3. 会话持久化

JSONL 追加写 + `fsync`，选 JSONL 不选 JSON 就是为了崩溃恢复——半截写入最多丢最后一行。旧 JSON 格式会话只读迁移，源文件永不修改。

### 4. 评测（两套，都是真实跑过的受控实验）

**上下文管理评测**：9 项编码任务 × 3 档上下文负载（60–70% / 75–85% / 85–95%）× 多策略 × 2 次重复 = **54 个真实 API 会话**（DeepSeek API，总花费 ¥13.99，有 ¥15 预算保护阈值）。结果：

| 指标 | 单次摘要基线 | 完整管线 | 变化 |
|---|---|---|---|
| 成功任务 | 13/18 | 14/18 | +5.6pp |
| 累计输入 Token | 14,560,434 | 12,872,748 | **−11.6%**（配对 bootstrap 95% CI [9.1%, 14.4%]）|
| 峰值输入 Token | 175,546 | 145,581 | −17.1% |
| 缓存命中率（热感知消融） | 64.2% | 66.6% | +2.4pp（CI 跨 0，报告中如实标注）|
| API 费用 | 4.6672 元 | 4.4865 元 | −3.9%（CI 跨 0，报告中如实标注）|

报告里明确写了测量边界：样本量下费用和命中率差异不具有统计显著性，不声称非劣效——只声称 Token 缩减是显著的。原始数据、任务定义、分析脚本全部在 `benchmarks/context_management/` 里。

**Agent 端到端评测框架**：任务语料库用 SHA-256 哈希钉定版本、Orchestrator 管理 worker 生命周期与重试、checkpoint 支持断点续跑、verifier 做结构化通过/失败判定、回归检测自动对比基线、集成 SWE-bench 做外部锚点。

### 6. TUI

Textual 写的完整终端应用（不是带颜色的 REPL）：流式 Markdown 逐 token 渲染、工具调用卡片、路径/命令补全、会话内切换模型和 Thinking 档位、Agent 运行中注入 steer / follow-up 消息、Plan 审批弹窗、会话恢复。

## 工程治理（项目进行中的真实状态）

- CI（GitHub Actions）有一套**质量基线门禁**：ruff / mypy / format / coverage 不和满分比，而是和提交的机器可读 JSON 基线比，原则是"不许继续恶化"，后续阶段逐条收紧；另用 import-linter 做分层架构防回归断言
- 有一份设计取舍表记录在 README：每个关键决策（先落盘再预览、缓存热时延迟裁剪、Hook 故障 fail-closed、JSONL 选型、零 SDK 等）都写明代价
- 进行中的工作：跨平台 CI 未做、演示素材（GIF/截图）未补——这些在 README 路线图里都是未勾选项

## 值得一提的点（如实，但确实比较独特）

1. **缓存感知的上下文裁剪 + 拿真实 API 会话做了统计验证**。大多数个人项目讲到上下文管理就是"做个摘要"，这个项目做到了"延迟裁剪保护前缀缓存"这个决策，并且用 54 个付费会话 + 配对 bootstrap 置信区间验证收益，还如实报告了不显著的指标。能聊：前缀缓存机制、为什么改写旧消息会作废缓存、实验设计、为什么费用差异不显著也照写。
2. **Fail-closed 的工具执行边界**。分层权限 + Hook 子进程最小环境 + 复合信任指纹 + "Hook 故障 ≠ 策略拒绝"的不变量。能聊：威胁模型、为什么密钥不能进 Hook 子进程、fail-closed 的可用性代价。
3. **零 SDK 的 Provider 层 + Provider 无关的异步生成器核心循环**。同一套循环吃 Anthropic / OpenAI 兼容 / 测试 Fake 三种后端，靠每轮动态钩子（get_system / get_tools / prepare_context）实现 Plan 模式、Skill 激活、上下文投影而不重建运行时。能聊：协议适配细节、异步生成器做控制流的好处和代价。
4. **质量基线门禁的 CI 设计**。"不许恶化、逐条收紧"的 ratchet 式质量治理，配 import-linter 架构契约，是接手有历史债务代码时的现实做法，比"全绿"口号真实。
