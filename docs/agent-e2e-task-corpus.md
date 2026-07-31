# Lion 自建编码 Agent 任务集（V1）

## 目的

V1 从 Lion 的真实 Git 历史提取 30 个可复现的历史回放任务，用于编码
Agent 的快速回归与 holdout 评估。任务分为跨文件重构、缺陷修复、特性开发
三类，各 10 条；公开 task card 由 `benchmarks.agent_e2e.corpus` 生成。

供 evaluator 装载的冻结公开 catalog 位于
`benchmarks/agent_e2e/corpus_assets/public_catalog.v1.json`，同目录的
`public_catalog.v1.sha256` 是其 canonical JSON SHA-256。源代码中的
`bundled_catalog()` 是该资产的生成源；测试会阻止二者漂移。
`public_catalog.v1.lock.json` 锁定本轮的完整 30 题选择；每次正式实验仍应把
这个 catalog lock 连同 profile 冻结进自己的 manifest。

这是一套可审计的初始任务来源，不是一份已经测得的模型成绩：当前环境没有
真实 Docker backend，且 V1 的准入 verifier 只证明 historical patch 的来源、
可重放性和稳定性。它不能替代语义 hidden test，也不能产生 `task_resolved`
或官方成功率。

## 公开与私有边界

公开给 Agent 的内容仅包含：任务 ID、类别、split、base revision、公开问题
说明、可见 setup/validation 命令、资源元数据和 gold patch SHA-256。gold commit、
完整 patch、private verifier 细节以及 preflight 来源记录属于 evaluator 私有
资产；未来 Docker backend 必须只把**被选中的单题公开卡**与目标仓库快照挂载
到 Agent 容器。不得把完整 catalog、evaluator Git 仓库或包含 gold object 的
`.git` 对象库挂进去；历史回放任务需要使用只含 base tree 的导出快照或受限
浅克隆。

这避免 Agent 从公开 catalog 直接恢复 gold 实现。实现或调优产生的失败回流 ID
必须传入 corpus 准入校验；只要它与 holdout 相交，构建即失败，不能将已经被
看过的任务重新标成 holdout。

## 准入口径

每条任务的 private evidence 都要求：

- base revision 和 gold revision 都存在于指定 Lion Git 历史；
- 从二者计算的 binary diff SHA-256 与公开 task card 的
  `gold_evidence_hash` 完全一致；
- base 与 gold 确有差异，gold diff 通过 `git diff --check`；
- 同一 provenance 检查连续运行三次产生一致摘要；
- task ID、patch hash、base/gold 提交不会在 regression 和 holdout 之间交叉。

这里的“base fail / gold pass”是 **patch-provenance** 的 fail/pass：base 不等于
gold，gold diff 可重建且格式合法。它不是业务语义的 fail/pass。接入真实
container verifier 后，每题还必须补做 base fail、gold pass 三次和隐藏测试
稳定性检查，才可进入官方分母。

## Split

| Split | 重构 | 缺陷修复 | 特性 | 合计 | 用途 |
|---|---:|---:|---:|---:|---|
| regression | 4 | 9 | 5 | 18 | 提示词、压缩和工具改动的回归门禁 |
| holdout | 6 | 1 | 5 | 12 | 不参与调优的内部泛化检查 |
| total | 10 | 10 | 10 | 30 | V1 历史回放候选集 |

提交链被整体放在同一 split，避免某一题的 gold commit 恰好成为另一 split
题目的 base revision。

## 任务导航

下表是公开卡的导航摘要，不提供 gold commit 或 patch 内容。完整公开提示和
验证命令以 versioned catalog 为准。

| ID | 类别 | Split | 公开任务主题 |
|---|---|---|---|
| lion-cross-file-refactor-01 | 跨文件重构 | regression | 收敛 Core-only runtime 的依赖与文档边界 |
| lion-cross-file-refactor-02 | 跨文件重构 | regression | 移除 legacy TUI 与全局输出桥 |
| lion-cross-file-refactor-03 | 跨文件重构 | regression | 收敛 JSONL 会话持久化路径 |
| lion-cross-file-refactor-04 | 跨文件重构 | regression | 删除 SDK 专属对话与旧压缩路径 |
| lion-cross-file-refactor-05 | 跨文件重构 | holdout | 收敛 Core Provider 单一路径 |
| lion-cross-file-refactor-06 | 跨文件重构 | holdout | 将 side query 迁移到 Core Provider |
| lion-cross-file-refactor-07 | 跨文件重构 | holdout | 重命名旧 TUI 并保持兼容入口 |
| lion-cross-file-refactor-08 | 跨文件重构 | holdout | 将上下文基准迁移到 ContextManager |
| lion-cross-file-refactor-09 | 跨文件重构 | holdout | 建立供应商无关的上下文投影 |
| lion-cross-file-refactor-10 | 跨文件重构 | holdout | 适配 Lion tool runtime 到 portable Core |
| lion-bugfix-01 | 缺陷修复 | holdout | 修复流式 TUI 输出闪烁 |
| lion-bugfix-02 | 缺陷修复 | regression | 按渲染行裁剪补全窗口 |
| lion-bugfix-03 | 缺陷修复 | regression | 归一化 Windows 文件拖拽路径 |
| lion-bugfix-04 | 缺陷修复 | regression | 阻止取消后仍启动 Core 请求 |
| lion-bugfix-05 | 缺陷修复 | regression | 保留热切换前累计用量 |
| lion-bugfix-06 | 缺陷修复 | regression | 回收 Core Provider 连接资源 |
| lion-bugfix-07 | 缺陷修复 | regression | 保留 Provider 用户取消语义 |
| lion-bugfix-08 | 缺陷修复 | regression | 同步 Core 终态到 Agent |
| lion-bugfix-09 | 缺陷修复 | regression | 阻止运行中的 TUI 命令分发 |
| lion-bugfix-10 | 缺陷修复 | regression | 热配模型后重绑会话 Runtime |
| lion-feature-01 | 特性开发 | regression | 加入溢出压缩与自动重试链 |
| lion-feature-02 | 特性开发 | regression | 将 TUI 通知接入 AgentSettled |
| lion-feature-03 | 特性开发 | regression | 将 thinking 档位接入 Core 路径 |
| lion-feature-04 | 特性开发 | regression | 让子 Agent 使用 Core Runtime |
| lion-feature-05 | 特性开发 | regression | 将 Anthropic 后端接入 Core Runtime |
| lion-feature-06 | 特性开发 | holdout | 增加 `/resume` 会话选择器 |
| lion-feature-07 | 特性开发 | holdout | 增加 `/model` 选择器 |
| lion-feature-08 | 特性开发 | holdout | 增加命令补全与主题选择 |
| lion-feature-09 | 特性开发 | holdout | 接入精简 TUI 默认入口 |
| lion-feature-10 | 特性开发 | holdout | 扩展 LionCodingSession 与默认命令注册 |

## 局限与下一步

这 30 条都来自同一项目，因此即使没有共享 task ID、base 或 gold commit，也仍
可能存在同一架构阶段的语义相似性。外部泛化必须由 SWE-bench-Live 抽样任务
交叉校验。真实容器 backend 和 private semantic verifier 到位前，报告应把本
任务集的结果标记为 offline/provenance evidence，而不是对外宣称通过率。
