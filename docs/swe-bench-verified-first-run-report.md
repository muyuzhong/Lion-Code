# SWE-bench Verified 第一次正式测评报告（Baseline Report）

- 日期：2026-09-04 至 2026-09-05
- 模型（agent）：`deepseek-v4-flash`（火山方舟 OpenAI-compatible 端点）
- 模型（judge）：`glm-5.3-flash`（DeepEval 独立评分，3 采样均值）
- 评测链路：artifact → Harbor → 官方 SWE-bench Harness（swebench 5.0.1）→ DeepEval → Opik
- 定位：**30 题分层抽样诊断样本的结果，不是完整 SWE-bench Verified 榜单成绩**

## 核心结论

> **Lion Code 在本次 30 题诊断样本中取得 19/28 有效官方通过；9 个官方失败里
> 只有 1 个被现有确定性过程规则明确定位为提前结束，其余 8 个暂未被当前
> ProcessVerifier + DeepEval 进一步解释。下一阶段的重点不是立即修改某个
> Harness 机制，而是先人工分析这 8 条失败轨迹，扩充真正有证据支持的失败分类。**

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
| 失败（resolved=false） | **9** | 官方 Harness 判定修复失败 |
| 无可评测 Patch / 非官方可判定 | **1** | django-13513：agent 3 次尝试均未导出可评测 patch（不属基础设施失败，见第五节） |
| 环境剔除（gold 预检） | **1** | requests-2931：gold patch 亦判不过（老镜像环境回归，不计入分母） |

**有效判定分母 28，通过率 19/28 ≈ 67.9%**（无可评测 patch 计入分母为
19/29 ≈ 65.5%；30 题全口径为 19/30 ≈ 63.3%）。分层表现：easy 层 10 题中
9 通过、medium 层 15 题中 8 通过、hard 层 5 题中 2 通过——通过率随难度下降，
符合预期。

成本口径：**29 个实际执行并出报告的题总 agent 成本 $18.23，平均 $0.63/题**
（不含被 gold 剔除的 requests-2931；不可评测的 django-13513 成本为 $0）。

## 三、失败归因

对 9 个失败逐个跑 ProcessVerifier（轨迹过程违规）与 DeepEval 指标对照：

| 实例 | 难度 | 归因 | 证据 |
|---|---|---|---|
| sphinx-doc__sphinx-9229 | hard | **提前结束** | stop_reason=max_turns，60 回合预算耗尽仍未能收敛，ProcessVerifier 标记 `premature_termination` |
| astropy__astropy-13977 | medium | 未进一步归因的任务失败 | Agent 正常结束，当前 ProcessVerifier 与 DeepEval 未发现已覆盖的过程异常，但官方 Harness 判定修复失败 |
| django__django-13128 | hard | 未进一步归因的任务失败 | 同上 |
| matplotlib__matplotlib-23476 | easy | 未进一步归因的任务失败 | 同上 |
| pylint-dev__pylint-4604 | medium | 未进一步归因的任务失败 | 同上 |
| pylint-dev__pylint-4970 | easy | 未进一步归因的任务失败 | 同上 |
| pytest-dev__pytest-10356 | hard | 未进一步归因的任务失败 | 同上 |
| pytest-dev__pytest-7324 | medium | 未进一步归因的任务失败 | 同上 |
| sympy__sympy-17318 | medium | 未进一步归因的任务失败 | 同上 |

**关键发现**：
1. **9 个失败中 8 个目前无法被现有过程评测进一步细分**——Agent 正常结束，
   `ProcessVerifier` 未检测到已有规则覆盖的过程违规，`DeepEval` 也未检测到
   低于当前阈值的工具参数/工具决策异常。**这只能证明"检测器没发现异常"，
   不能证明根因是模型解题能力**；其真实根因（未识别根因、修复方向错误、
   测试理解偏差等）需要人工分析轨迹后才能判定。
2. **1 个被确定性规则定位为过程问题**（sphinx-9229 提前结束）：回合预算
   （max_turns=60）耗尽时仍在探索未收敛。
3. **DeepEval 未发现工具参数质量问题**：9 个失败的 ArgumentCorrectness /
   ToolDecisionQuality 均 ≥0.5（无低分 case）——详见第四节对其区分能力的说明。

## 四、DeepEval 指标分布（不合成总分）

| 指标 | 有效样本 | 均值 | 低分(<0.5) |
|---|---|---|---|
| ArgumentCorrectnessMetric | 25 | 0.881 | 0 |
| ToolDecisionQuality | 29 | 0.883 | 0 |

样本差异说明：ArgumentCorrectness 缺 4 个有效样本（django-16136、xarray-4629、
pytest-7324、sympy-17630），原因是该指标 **metric failed（Judge 未提供
sequence 定位）**，与题目通过与否无关，不是 Analysis Trace 缺失。

**结论**：DeepEval 对本轮工具行为整体评价较高（两指标均值 ≈0.88，无低分），
但**没有明显区分官方 PASS 与 FAIL**（PASS 高分、FAIL 也高分）。这与它当前
只评价工具参数和工具决策、不评价最终代码修复正确性的定位一致——它是
"工具过程是否合理"的过程观测，不是"这个 bug 修对没有"的结果判定。

## 五、评测体系解释盲区

- **8/9 的失败目前无法被现有过程评测进一步细分**：无过程违规、无工具异常、
  仅"官方判定未解决"——这是本轮评测体系最大的盲区，需要人工抽查轨迹
  才能进一步归因（如"未识别根因""修复方向错误""测试理解偏差"）。
- **django-13513 连续 3 次未导出 patch**（agent 未产生文件改动）：这不属于
  基础设施失败（网络/Docker 均正常），更接近"未形成可评测结果"；可能为
  prompt/工作区契约问题，值得专项排查，不应与 infra 混同。
- **自动生成器（run_summary.py）尚不能完全复现本报告**：它目前只统计
  `TOOL_ERROR_NOT_RECOVERED` 与 `PREMATURE_TERMINATION` 两类 ProcessViolation，
  且 gold 预检剔除的题不会进入其统计行；本报告为人工整理版，后续复用前
  需扩展生成器（不影响本轮结论，无需重跑）。

## 六、下一步优化方向（按优先级）

1. **人工分析 8 条未归因失败轨迹**：抽取轨迹做人工归类（根因识别失败 /
   修复方向错误 / 测试理解偏差），形成**真正有证据支持的失败分类**后再
   定向优化——本轮无证据表明上下文压缩或 Prompt 是瓶颈，不应据此调整。
2. **回合/时间预算策略**（解决 sphinx-9229 类提前结束）：max_turns=60 对
   hard 题偏紧；可对 hard 题提高预算，或在 agent 停滞时更早触发"换思路"策略。
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
