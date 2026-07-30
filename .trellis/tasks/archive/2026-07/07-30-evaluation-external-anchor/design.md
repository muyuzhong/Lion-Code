# SWE-bench-Live 外部锚点设计

## 冻结输入

- 数据集：`SWE-bench-Live/SWE-bench-Live`（Python-only）
- revision：`a637bd46829f3132e12938c8a0ca93173a977b8e`
- split：`verified`，500 条；对应 `data/verified-00000-of-00001.parquet` 的 LFS SHA-256 是
  `080e36e46198bf9c177a6b077624d4028baf6ff04d661c332cc1fe1e5dfa50b2`。
- evaluator：`microsoft/SWE-bench-Live@70ec57e852e3f2d195790fe71f553e272c691833`，入口
  `python -m evaluation.evaluation`，平台固定为 Linux。
- 抽样：以 `SHA-256("lion-swe-live-v1-20260730|<instance_id>")` 排序；按 gold patch
  涉及文件数分为 1、2、3--4、5+ 四层，每层取 5 个，并跨层禁止重复仓库。清单本身及每条
  base commit 是冻结的复跑输入，不会在运行时从 live 数据集重新抽样。

## 执行边界

1. Agent 仅在独立任务容器中产生预测 patch；SWE-bench-Live evaluator 在另一受控 host 目录
   调用官方 Docker evaluator。预检/评测目录不能挂载给 Agent。
2. 每个冻结实例先以官方 `gold` patch 连续运行三次。三次均 `resolved=true` 才进入本次
   有效分母；失败、缺失报告或 evaluator 异常均是基础设施无效，不可计作 Agent 失败。
3. 模型 patch 只交给官方 evaluator。报告只保留 patch/output 摘要、镜像引用/摘要、官方
   `resolved` 结果及受控原因，不写入原始 patch、测试日志、凭证、会话或绝对路径。
4. Docker daemon、evaluator checkout、镜像或数据快照任一不可用时，结果必须是 `blocked`；
   不写外部通过率，也不能以 fake backend 生成 `passed/failed`。

## 结果与校准

- 已完成的官方 evaluator 输出被归一为统一 `TaskResult`；仅真实官方运行可产生
  `official=true` 的 pass/fail。
- 外部报告含 gold 稳定清单、实际分母、Wilson 95% 区间和环境指纹。
- 任意比较先比对 manifest 指纹、数据 revision/file hash、evaluator revision、平台和每个
  镜像 digest；任一不同直接拒绝比较。
- 校准要求至少 5 个冻结 profile：1 个 baseline、至少 3 个 candidate、1 个故意退化 profile。
  对自建 holdout 与外部锚点成功率计算 Spearman rho 与成对方向一致率；仅 rho >= 0.70 且
  方向一致率 >= 80% 才视为外部有效性通过。

## 非目标

- 不在本任务执行真实模型调用、拉取 Docker 镜像或报告虚构分数。
- 不把 SWE-bench-Live 的 20 条题目放进日常低成本 CI，也不把其 gold patch 传给 Agent。
