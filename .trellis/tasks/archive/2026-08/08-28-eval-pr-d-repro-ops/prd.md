# PRD:评测链 PR D(分析可复现与运维)

> 来源:`benchmarks/agent_e2e/results/smoke-flask-5014/improvements-backlog.md`
> 推荐实施顺序第 4 项(P1-4、P2-1 ~ P2-3 按需;P2-1 已随 PR C 完成)。
> 前序:PR A(#129)/PR B(#130)/PR C(#132)均已合并;本 PR 基于
> master(`b5bb677`)。

## 1. 背景与目标

Verified 单题闭环已具备评分语义化(P1-3/P1-5/P2-1),剩余三项链路工程
细节:

1. **P1-4 分析可复现性**:judge 调用无 seed、无重复,分数在不同轮次间
   漂移(A5 实测 TrajectoryQuality 0.5 → 0.3),同 payload 无法复现;
   也没有记录 judge 调用参数。
2. **P2-2 运行残留清理**:`harbor-home/`(109MB python + HF 缓存)与
   Harness 保留镜像(`swebench/sweb.eval.x86_64.*`)随运行累积,评测
   主机无一键清理手段。
3. **P2-3 digest 可反查性**:报告中的 `payload_digest`/`trajectory_digest`
   无法反查内容,复核困难;需要一个只存"digest → 脱敏摘要"的本地
   寻迹数据库(不存正文,不破坏脱敏红线)。

目标:一个独立 PR,让分析可复现(多次采样取均值±范围,报告标注采样
次数)、残留可一键清理(缓存重建无损)、digest 可反查(给定 digest
查到脱敏摘要与时间)。

## 2. 需求

### R1(P1-4)judge 多次采样取均值±范围

- R1.1 `analyze_deepeval_case` 支持 `judge_samples`(默认 3):每个指标
  独立采样 N 次,`score` = 成功采样均值,`score_min`/`score_max` =
  成功采样范围;全部失败时沿用既有失败语义;部分失败时以成功采样
  聚合并在 reason 标注"N 次采样失败"。采样在分析 deadline
  (`timeout_seconds`)内逐样本计时,超时样本按既有 TIMEOUT 语义计。
- R1.2 `DeepEvalMetricResult` 记录 `samples`(采样次数)、`score_min`/
  `score_max`(completed 且 samples>1 时必须齐备,min ≤ score ≤ max);
  `DeepEvalMetricResult` 仍在指标行渲染均值±范围与采样次数。
- R1.3 CLI `--deepeval-samples`(默认 3),`VerifiedExecutionRequest`
  透传并校验 ≥1;一键脚本 `--deepeval-samples "${DEEPEVAL_SAMPLES:-3}"`
  (可选 env,不新增必填)。
- R1.4 fixture 解析兼容:新增可选字段(默认 samples=1),旧 fixture 可
  继续解析;fixture 可显式携带 samples/min/max。
- R1.5 验收:同 payload 报告给出均值±范围并标注采样次数;采样次数
  可配置且被记录。

### R2(P2-2)运行残留一键清理脚本

- R2.1 新增 `scripts/benchmarks/verified-smoke/cleanup_smoke.sh`
  (仅本机运维,不入 CI):定位方式与 `run_smoke.sh` 一致
  (`SMOKE_RESULT_ROOT` 可覆写);默认删除缓存目录
  `harbor-home/`、`hf-home/`、`xdg-cache/`(可重建,不删 `run-*`
  证据目录);`SMOKE_CLEAN_IMAGES=1` 时同时删除
  `swebench/sweb.eval*` 镜像(docker rm,失败仅警告不中断);
  `SMOKE_CLEAN_DRY_RUN=1` 仅打印将删除项。
- R2.2 路径守卫:删除前解析并校验目标必须位于 `WORK_DIR` 之内,
  卫违反即拒绝(exit 2);删除失败 exit 2;镜像删除失败仅警告。
- R2.3 README 增 cleanup 用法与 env 表;docs 提及。
- R2.4 验收:清理后缓存可重建、评测可无损重跑(本机 A5 复跑);
  干跑模式不删任何文件;守卫拒绝越界路径。

### R3(P2-3)digest 寻迹数据库

- R3.1 新增 `benchmarks/agent_e2e/digest_ledger.py`:`DigestLedgerEntry`
  模型(digest/kind/task_id/run_id/event_type/tool_name/preview 脱敏
  摘要/first_seen_at/last_seen_at/count)与 `DigestLedger`
  (append-only JSONL,`append`/`lookup`/`count`);kind ∈
  {input, trace, payload, argument}。
- R3.2 勾挂点:`verified_runner` 在 trajectory 就绪后(分析前)写 ledger
  (`VerifiedExecutionRequest.digest_ledger_path`,缺省 None 不写,
  写失败不阻断主链);记录:input digest(preview = public_prompt 脱敏
  短预览)、trace digest(事件数摘要)、每个投影事件的 payload/
  argument digest(event_type/tool_name/时间)。
- R3.3 CLI 新增 `digest-lookup`:读 ledger 文件,给定 digest 输出全部
  关联条目(按 kind 分组、按 last_seen 倒序、聚合 count);退出码
  0=找到、1=未找到、2=ledger 缺失/不可读。
- R3.4 一键脚本传 `--digest-ledger "$RESULT_ROOT/digest-ledger.jsonl"`
  (results/ 已整体 gitignore,天然不入库)。
- R3.5 验收:给定 digest(报告/trajectory 中的)可查到脱敏摘要与
  时间;ledger 中无原始正文/无密钥(静态断言 + 运行时脱敏)。

## 3. 非目标(本 PR 不做)

- **不做 judge seed/温度固定**:DeepEval SDK 的 LLM 调用不支持 seed
  语义稳定化;以"多次采样均值±范围"承担可复现性,不假造确定性。
- **不做自动定时清理/磁盘配额**:清理为手动运维入口,不入 CI、
  不自动触发。
- **不做 ledger 正文存储**:寻迹数据库只存脱敏摘要与元数据,不存
  prompt/工具输出原文(脱敏红线不变)。
- 不改 verdict/退出码语义(除新增 digest-lookup 自身退出码);
  不改 Harbor/Harness/Opik 阶段的评分、镜像或缓存策略。

## 4. 约束与红线

- 最小实现:ledger 用标准库 JSONL 追加写(不引入 sqlite/第三方依赖);
  清理脚本只用 bash 标准命令。
- 脱敏红线:ledger 的 preview 一律经 `redact_text`;event 条目不带
  summary 原文;不记录凭证/会话字段;`_reject_sensitive_keys` 风格
  校验 ledger 写入口。
- 模型字段全部带默认值(旧 JSON 可继续解析);SCHEMA_VERSION 不变。
- 源码注释中文;文档语言与既有 docs 一致。
- 最小验证:只跑与本次修改直接相关的 targeted tests。

## 5. 验收标准

- **A1(P1-4)**:单测覆盖均值/min/max/samples 计算、部分失败 reason
  标注、全失败沿用失败语义、deadline 内逐样本计时、fixture 兼容;
  md 渲染"采样 N 次、范围 min–max"。
- **A2(P2-2)**:子进程测试:默认删缓存保留 run-* 目录;干跑不删除;
  越界路径拒绝(exit 2);`bash -n`;脱敏静态断言含新脚本。
- **A3(P2-3)**:ledger 单测:追加/查找/聚合 count/脱敏(无原文关键字);
  verified_runner 注入后产物 ledger 含 input/trace/payload/argument
  条目;`digest-lookup` CLI 三态退出码。
- **A4**:既有评测链测试不回归(targeted 全绿,含改动的
  analysis/contracts/cli composition 采样断言);`git diff --check`、
  ruff 无新指纹。
- **A5**:本机按模板复跑单题闭环:报告含采样均值±范围;ledger 文件
  生成且可反查本次 digest;cleanup 干跑/实跑后可无损重跑(缓存重建
  验证),backlog 勾销 P1-4/P2-2/P2-3。

## 6. 工作拆分建议

单任务单 PR(如 PR A/B/C):三项同属"链路工程细节",一个行为边界内
跨 analysis/models/runner/cli/模板/脚本/文档/测试,可独立理解与
回滚;P2-3(L)是本 PR 最大块,实施顺序 P1-4 → P2-2 → P2-3。