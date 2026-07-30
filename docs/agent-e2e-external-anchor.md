# SWE-bench-Live 外部锚点

`benchmarks/agent_e2e/external_anchor_assets/swe_bench_live_verified.v1.json` 是 Lion V1 的外部
有效性锚点：20 条 Python-only `SWE-bench-Live/SWE-bench-Live` `verified` 实例。它不是日常
CI 数据集，也不向 Agent 提供 gold patch、测试 patch、完整 dataset 或 evaluator 的结果目录。

## 冻结内容

- 数据集 revision：`a637bd46829f3132e12938c8a0ca93173a977b8e`
- split 与文件：`verified` / `data/verified-00000-of-00001.parquet`
- 文件 LFS SHA-256：`080e36e46198bf9c177a6b077624d4028baf6ff04d661c332cc1fe1e5dfa50b2`
- 20 条完整行（含官方 evaluator 必需字段）的 canonical SHA-256：
  `f2ccf27b41c0028ec91a21faa6747659ab8f4db10291f3879e33bf36f2ad5a44`
- 官方 evaluator revision：`microsoft/SWE-bench-Live@70ec57e852e3f2d195790fe71f553e272c691833`
- 平台：Linux；官方镜像名按 `starryzhang/sweb.eval.x86_64.<instance-id>` 规则生成。

题目以 `SHA-256("lion-swe-live-v1-20260730|instance_id")` 排序后分层选出：按
`difficulty.files` 的 1、2、3--4、5+ 四层各 5 条，并保证 20 个仓库互不重复。运行不允许
重新从 live 数据集抽样；要更新锚点需新版本 manifest，并重新做外部校准。

离线核验清单无需网络、Docker 或模型凭证：

```powershell
python -m benchmarks.agent_e2e external-anchor-validate --show-instance-ids
```

## 正式运行协议

1. 在受控 host 上从 manifest 的 dataset revision/file materialize **恰好这 20 条完整行**为
   本地 JSONL；用 `validate_materialized_dataset_snapshot()` 校验 metadata 和 canonical SHA-256。
   官方 evaluator 本身没有 revision 参数，因此绝不能直接传会变化的 dataset 名称。
2. checkout 官方 evaluator 的冻结 revision，并验证 Docker daemon 已可用；在与 Agent 工作区
   隔离的 host 结果目录中，以该 JSONL 作为 `SubprocessOfficialSWEbenchLiveRunner(dataset_jsonl=...)`
   的 dataset 输入。
3. 对全部 20 条以官方 `gold` patch 连续运行三次。仅三次均 `resolved=true` 的实例构成本机
   实际分母；gold 失败、缺失 `report.json`、镜像/runner 故障都排除，绝不能计为模型失败。
4. 让 Agent 只提交 prediction JSON（20 个冻结 ID，值含 `model_patch`）；官方 evaluator 对本次
   stable 集合执行。只在所有 stable 实例完成、结果有可解析镜像 digest 时报告通过率和 Wilson
   95% 区间。
5. 保存 `ExternalAnchorReport` JSON/Markdown。它含统一 `TaskResult`、gold 预检、输出摘要和
   环境指纹；不含原始 patch、日志、会话、凭证或绝对路径。

若 Docker、官方 checkout、数据、镜像 digest 或 evaluator 输出不可用，runner 返回 `blocked`
或 `invalid`，`success_rate` 必须为 `null`。测试 fake 只能验证编排契约，不能生成官方分数。

## 比较与校准

两次外部报告可比较的前提是环境指纹完全一致：manifest、数据 revision/file SHA、evaluator
revision、Linux 平台和每个进入实际分母实例的镜像 digest。任一漂移会抛出
`ExternalAnchorDriftError`，不能拿旧 baseline 算 delta。

校准使用至少 5 个冻结 profile：1 个 baseline、至少 3 个候选变更、1 个故意退化 profile。每个
profile 同时记录自建 holdout 成功率与外部锚点成功率；`calibrate_external_anchor()` 计算
Spearman rho 和忽略并列后的成对方向一致率。只有 rho >= 0.70 且方向一致率 >= 80% 才能说明
自建分数对该锚点有足够外部有效性。未通过时先检查题型覆盖、gold 稳定性和环境漂移，不应以
调低门槛代替修复。

## 当前状态

仓库已经具备冻结清单、预检/官方 evaluator adapter、报告、漂移拦截和校准逻辑。本机未连接
Docker daemon，因此尚无真实外部通过率；这不是 0%，而是明确的 `blocked`，待受控 Linux
Docker 环境和已批准的模型预算到位后再执行。
