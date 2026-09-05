# SWE-bench Verified 第一次正式测评报告

- 日期：2026-09-04 至 2026-09-05
- 模型（agent）：`deepseek-v4-flash`（火山方舟 OpenAI-compatible 端点）
- 模型（judge）：`glm-5.3-flash`（DeepEval 独立评分，3 采样均值）
- 评测链路：artifact → Harbor → 官方 SWE-bench Harness（swebench 5.0.1）→ DeepEval → Opik

## 一、方法与样本

从 SWE-bench Verified 500 题中**分层抽样 30 题**：10 easy / 15 medium / 5 hard，
覆盖 **11 个仓库**（django/sympy/sphinx/matplotlib/sklearn/pytest/requests/
xarray/astropy/pylint/seaborn），排除全部已看过结果的实例（历史冒烟
flask-5014 / requests-5414 / pytest-6202 / django-11555），seed 固定可复现
（`selection.json`）。每题 agent 预算 timeout=2400s、budget=$2、max_turns=60。

## 二、结果总览

| 类别 | 数量 | 说明 |
|---|---|---|
| 官方通过（resolved=true） | **19** | 官方 Harness 判定通过 |
| 失败（agent 未能解决） | **9** | 官方判定 resolved=false |
| 环境/基础设施不可判定 | **1** | django-13513：agent 3 次尝试均未导出可评测 patch |
| 环境剔除（gold 预检） | **1** | requests-2931：gold patch 亦判不过（老镜像环境回归） |

**有效判定分母 28，通过率 19/28 ≈ 67.9%**（含不可判定为 19/30 ≈ 63.3%）。
总 agent 成本约 $14（19 题平均 ~$0.74）。

分层表现：easy 层 10 题中 9 通过、medium 层 15 题中 8 通过、hard 层 5 题中 2 通过
——通过率随难度下降，符合预期。

## 三、失败归因

对 9 个失败逐个跑 ProcessVerifier（轨迹过程违规）与 DeepEval 指标对照：

| 实例 | 难度 | 归因 | 证据 |
|---|---|---|---|
| sphinx-doc__sphinx-9229 | hard | **提前结束** | stop_reason=max_turns，60 回合预算耗尽仍未能收敛，ProcessVerifier 标记 `premature_termination` |
| astropy__astropy-13977 | medium | 能力失败 | 正常完成（stop=completed），无过程违规，DeepEval 无低分 |
| django__django-13128 | hard | 能力失败 | 正常完成，无过程违规 |
| matplotlib__matplotlib-23476 | easy | 能力失败 | 正常完成，无过程违规 |
| pylint-dev__pylint-4604 | medium | 能力失败 | 正常完成，无过程违规 |
| pylint-dev__pylint-4970 | easy | 能力失败 | 正常完成，无过程违规 |
| pytest-dev__pytest-10356 | hard | 能力失败 | 正常完成，无过程违规 |
| pytest-dev__pytest-7324 | medium | 能力失败 | 正常完成，无过程违规 |
| sympy__sympy-17318 | medium | 能力失败 | 正常完成，无过程违规 |

**关键发现**：
1. **9 个失败中 8 个是"能力失败"**——agent 正常走完流程、工具调用无异常、
   未触发错误恢复问题，但最终没有做出正确修复。这说明本轮的失败**主要不是
   错误恢复或工具参数问题**，而是 agent 对特定 bug 的解题能力边界。
2. **1 个是过程问题**（sphinx-9229 提前结束）：回合预算（max_turns=60）耗尽
   时仍在探索未收敛。
3. **DeepEval 未发现工具参数质量问题**：9 个失败的 ArgumentCorrectness /
   ToolDecisionQuality 均 ≥0.5（无低分 case），与"能力失败"归因一致——
   没有工具使用异常，就是没做对。

## 四、DeepEval 指标分布（不合成总分）

| 指标 | 样本数 | 均值 | 低分(<0.5) |
|---|---|---|---|
| ArgumentCorrectnessMetric | 25 | 0.881 | 0 |
| ToolDecisionQuality | 29 | 0.883 | 0 |

DeepEval 整体信号与官方判定方向一致（通过题普遍高分），但对"能力失败"型
错误区分度有限——它擅长抓工具使用异常，不擅长判断"修复本身是否错误"。

## 五、评测体系解释盲区

- 8/9 失败当前归因为"能力失败"，属于**评测体系无法进一步细分的盲区**
  （无过程违规、无工具异常、仅"未解决"）——这类失败需要人工抽查轨迹
  才能进一步归因（如"未识别根因""修复方向错误""测试理解偏差"）。
- django-13513 连续 3 次未导出 patch（agent 未产生文件改动）值得专项排查：
  可能是 prompt/工作区契约问题，而非能力问题。

## 六、下一步优化方向（按优先级）

1. **回合/时间预算策略**（解决 sphinx-9229 类提前结束）：max_turns=60 对
   hard 题偏紧；可对 hard 题提高预算，或在 agent 停滞时更早触发
   "换思路"策略。
2. **能力失败的专项分析**（8 个样本）：抽取轨迹做人工归类（根因识别失败 /
   修复方向错误 / 测试理解偏差），形成失败模式清单后再定向优化——**不应急于
   调整上下文压缩或 Prompt**，因为本轮无证据表明它们是瓶颈。
3. **django-13513 无 patch 问题**：排查 worker 的 patch 导出契约（是否 agent
   认为"无需修改"时正常结束但未留下改动）。
4. **扩展样本**：本轮通过率 68% 的置信区间较宽（19/28），后续可先补跑
   30 题再下结论；gold 预检剔除（requests-2931）说明老镜像存在环境回归，
   新实例选择时应规避。

## 七、局限与说明

- 单次运行：agent 存在随机性（sphinx-9673 在本轮 passed 而在早期污染批
  次 failed），单题结果有波动，多题聚合后才有意义。
- 网络环境：github.com 出网抖动导致部分实例需重试（已在 run_batch 中
  对 infra 失败自动重试、对真实失败不重试以保证单次干净结果）。
- 镜像环境：requests 老镜像存在 Python 3.11 环境回归（gold 预检剔除）。
- 数据与代码全部落盘可复核：`selection.json`、各 `run-*/verified-report.json`、
  `run-summary.json`、Opik traces（project `lion-agent-e2e`）。
