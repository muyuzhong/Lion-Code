# 编码 Agent 端到端评测闭环实施计划

## 执行顺序

### 1. 评测基础设施：07-30-evaluation-foundation

1. 定义 TaskSpec、ExperimentManifest、TaskResult、FailureRecord、GateVerdict 的严格 JSON 契约和 schema version。
2. 实现 catalog/selection/lock 校验、预算与 checkpoint 模型、结构化报告骨架和被忽略的在线结果目录。
3. 实现容器 worker/orchestrator 接口，先以 fake Docker 和 FakeProvider 覆盖生命周期、异常、资源清理和无密钥输出。
4. 为 Agent 增加默认不变的 mcp_enabled seam；测试根 Agent 默认行为、禁用后的零 MCP 发现、独立 SessionRepository 和 Core event 订阅。
5. 只在 Docker 可用时运行单题 smoke；Docker 不可用时必须返回 blocked，而非零分或通过。

### 2. 自建任务集：07-30-evaluation-task-corpus

1. 制定任务候选来源规则：历史已解决 issue/commit、跨文件变更、可在固定 base revision 上复现，且不含 API/网络依赖。
2. 建立公开 task card 与 host-private verifier/gold 的双资产结构，并实现泄漏扫描。
3. 逐题建立 10 条重构、10 条缺陷、10 条特性任务；为每题记录 base fail、gold pass、稳定性和资源证据。
4. 以固定 seed 写入 18/12 split，测试一题不会同时落在调优 regression 与报告 holdout。
5. 生成 catalog version/sha 与中文任务构造说明。

### 3. 外部锚点：07-30-evaluation-external-anchor

1. 将 SWE-bench-Live 安装/数据集/镜像定位包装为可选且显式的外部 adapter，不添加到 Lion 生产依赖。
2. 实现可审计的分层抽样和 selection manifest，先固定 Python 数据集 revision、Linux 平台、20 个 instance ID。
3. 实现 gold patch 三次预检、actual denominator、官方 patch evaluator 调用、镜像/平台信息捕获与失败归类。
4. 接入统一 TaskResult/report；在 Docker 可用的机器完成一次 anchor smoke，再完成五 profile 的校准运行。
5. 只在 gold 预检和完整校准都有证据后，允许该锚点影响 gate 结论。

### 4. 回归门禁与失败回流：07-30-evaluation-regression-feedback

1. 实现 baseline/candidate manifest 可比性验证、三次多数评分、灾难性回退、配对非劣和 reject/invalid/waived 判定。
2. 实现不可变 interception ledger，拒绝把系统故障或人为撤回统计为拦截。
3. 实现受控 trace 精简和四类 failure candidate rule；为每类准备合成轨迹和反例。
4. 实现 triage/review 状态、failure signature、去重和 regression/holdout 回流规则。
5. 完成一次不合入的受控劣化候选，证明 gate 能拦截；完成一条已验证失败的安全回流。

### 5. 父任务整合

1. 在同一 evaluation lock 上跑 self regression、self holdout 和 anchor 校准，记录真实 N、X、Y、成本和有效分母。
2. 对 prompt、压缩和工具三种受控变更各执行一次比较，确认 profile 指纹、报告和 gate 走同一路径。
3. 复核校准阈值、输出中文方法报告、更新 README 的评测边界，并归档不会复现的临时容器/结果。

## 验证策略

- 每次代码切片先运行对应 tests/benchmarks 或受影响的 Agent/tooling 测试，再运行 python -m pytest -q。
- 每次切片运行 python -m compileall -q lion_code benchmarks tests 和 git diff --check。
- 离线验证不得调用真实 provider：catalog 校验、manifest 解析、split、gate、trace 与 Docker adapter 都用 fixture/FakeProvider/FakeDocker。
- 在线运行必须带显式 online 开关、预算、凭证环境变量、输出路径和 resume ID；先执行单题 smoke，再扩大到正式批次。
- Docker 环境验证包括镜像可用、agent/verifier 文件系统隔离、hidden asset 不可见、session 不污染 patch、容器异常后清理。
- 每份正式报告必须人工核对成功数、有效分母、invalid、未归属费用、重复次数和 configuration fingerprint。

## 关键风险与停止条件

- Docker daemon 不可用、gold 三次预检失败、数据集 revision 漂移、有效分母改变或预算不足时，停止正式比较并输出 blocked/invalid 证据。
- 任何发现 Agent 可访问 hidden verifier/gold/host result 的情况都阻塞任务入库和所有官方成绩，先修复隔离。
- 自建评分与外部锚点不满足 evaluation lock 的校准阈值时，禁止将 self-only gate 描述为泛化质量门禁；只保留诊断用途。
- profile/任务/资源不一致时不允许 merge 两份结果，也不允许用新的 baseline 覆盖旧实验。

## 提交与回滚边界

- 每个子任务独立提交，使用中文提交说明；只暂存该子任务实际拥有的文件，保留工作区无关改动。
- foundation 的 mcp_enabled seam 是唯一允许进入 lion_code 的评测支撑改动，默认行为必须有回归测试；其余评测逻辑保持在 benchmarks。
- 若外部 adapter 或 gate 不稳定，回滚到上一个可复跑 catalog/lock；不删除历史 manifest、interception ledger 或用户 session。
