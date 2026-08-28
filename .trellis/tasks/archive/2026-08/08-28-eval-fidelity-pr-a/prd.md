# PRD:评测链 PR A(离线分析安全声明与保真度)

> 来源:`benchmarks/agent_e2e/results/smoke-flask-5014/improvements-backlog.md`
> 推荐实施顺序第 1 项:P0-1 + P1-1 + P1-2,一个小 PR,随后重跑同题对比分数。
> 对应 `08-27-eval-analysis-observability` 任务的后续收口。

## 1. 背景与目标

2026-08-28 在评测主机完成 Verified 单题真实闭环(`flask-5014`,
PR #128 已合并 fix commit `ec837cf`),跑测日志证实三件事实:

1. **P0-1**:日志出现 `⚠ WARNING: All metrics errored ... Posting the run
   anyway ... on the Confident AI dashboard` 与 `deepeval view` 建议;
   查 deepeval 4.2.0 源码确认未配 `CONFIDENT_API_KEY` 时实际上报未发生,
   但该行为是"环境巧合"而非代码不变量,且横幅极具误导性。
2. **P1-1**:256 事件轨迹中 `tool_name` 全 null、`started_at/finished_at`
   全 null——Core 事件经 `WireModel` camelCase 序列化(`toolName`),
   `TraceRecorder` 按 `tool_name/name` 查找失败;`TraceEvent` 模型本身
   无时间戳。这是三项指标 0 分的直接原因之一。
3. **P1-2**:256 事件中 195 个 `message_update`,judge 看到的信噪比极低。

目标:一个独立 PR,把"不上报"变成显式不变量并消除误导性横幅来源,
修复轨迹保真度(tool 名 + 时间戳),压低轨迹噪声;重跑同题,
指标从 0 分回到有意义的分数,reason 可引用工具名。

## 2. 需求

### R1(P0-1)显式关停 DeepEval 上报

- R1.1 离线分析入口把 `CONFIDENT_API_KEY` 未设置作为不变量:
  - 已设置 → 拒绝进入分析(typed 错误,归入分析失败字段,不改 verdict);
  - 未设置 → 显式记录"telemetry off / 不上报"状态到分析结果。
- R1.2 消除带来误导的横幅来源:全部指标失败时 SDK 打印
  "Posting the run anyway ... Confident AI dashboard",修复 R2/R3
  保真度后真实闭环不再触发;对 SDK 无法配置的 `deepeval view` 固定
  文案,在评测文档注明为已知 SDK 输出,不做 SDK monkeypatch。
- R1.3 不允许本评测链任何路径设置 `CONFIDENT_API_KEY` 或调用上报 API。

### R2(P1-1)工具名 + 时间戳映射

- R2.1 `TraceRecorder` 识别 Core 事件 camelCase 字段 `toolName`(与
  现有 `tool_name`/`name` 兼容),轨迹事件携带工具名;
  `_event_summary` 同步携带工具名(judge reason 可引用)。
- R2.2 `TraceEvent` 模型增加 `started_at`/`finished_at`(受控元数据):
  消息类事件提取 `message.timestamp`(ms→UTC),工具执行事件以记录器
  接收时刻为准;两值均为可选,缺失保持 None。
- R2.3 事件时间戳贯通到 `DeepEvalTrajectoryEvent` 投影(该模型已有
  对应字段,投影函数已按 `getattr` 取数)与 Opik span。

### R3(P1-2)噪声事件过滤

- R3.1 `build_deepeval_trajectory` 投影前按事件类型升采样:
  丢弃 `message_update`(流式快照,与 message_start/end 冗余),
  保留 turn/tool/message 边界、compaction 信号与全部工具元数据。
- R3.2 过滤只作用于投影,不改变 `TraceEvent` 原始持久化,
  不破坏脱敏红线与循环候选检测。
- R3.3 事件上限 `MAX_TRAJECTORY_EVENTS = 256` 保持不变。

## 3. 非目标(本 PR 不做)

- P0-2 / P0-3 / P0-4(环境文档与模板化)、P1-3 / P1-4 / P1-5(judge
  独立配置、可复现性、阈值门禁)、P2 各项,均不在本 PR。
- 不修改 Harbor/Harness 官方评分链,不改 verdict 语义与退出码。
- 不 monkeypatch deepeval SDK,不引入新依赖,不做 schema 大版本迁移。

## 4. 约束与红线

- 脱敏红线不变:只新增工具名与时间戳这类受控元数据,禁止携带
  message 正文、prompt、session、凭证;`TraceEvent`/报告对象
  的 `extra="forbid"` 严格性保持。
- 兼容性:`TraceEvent` 新字段可选;`write_json` 的
  `schema_version="agent-e2e/v1"` 在本 PR 不 bump(同 repo 内
  worker 写入与 runner 读取同版本演进,旧轨迹文件可被新代码读)。
- 分析失败只落在 `deepeval` 字段,不改变 `task_result`。
- 最小验证:只运行与本次修改直接相关的 targeted tests。

## 5. 验收标准

- **A1(P0-1)**:单元测试覆盖"未配置 key"分支断言分析可运行且记录
  不上报状态;"已配置 key"分支断言拒绝进入分析;真实闭环重跑后运行
  日志不再出现 "Posting the run anyway ... Confident AI dashboard"
  (依赖 A2/A3 使指标不再全部失败)。
- **A2(P1-1)**:重跑同题,`harbor-trace.json` 事件带 `toolName` 映射
  的工具名与 `started_at/finished_at`;投影/Opik 载荷时间戳非空;
  judge 可见工具名(指标 reason 或 `_trajectory_output` 中)。
- **A3(P1-2)**:同题重跑,投影后事件数显著下降(256 事件样例
  期望降到 ~61),指标所需信号(工具名/边界/时间戳)不丢失。
- **A4**:既有评测链测试通过(`test_trace.py`、
  `test_eval_analysis_observability.py`、`test_verified_contracts.py`、
  `test_verified_execution_chain.py`、`test_verified_cli_composition.py`)。
- **A5**:正式 `task_result` 与 verdict 在改动前后不变(分析前后断言)。

## 6. 工作拆分建议

单任务单 PR(跨 3 个文件 + 测试,可独立理解与回滚),不拆父子任务。