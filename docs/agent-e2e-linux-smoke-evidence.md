# Verified 单题 Linux 真实闭环验收记录(2026-08-28)

任务 `08-27-eval-cli-linux-smoke` 的第 4 条验收(PRD):在 Linux Docker 评测
主机完成一条真实单题闭环,保留可复核命令与受控产物。本文只记录非敏感摘要;
完整报告与受控产物位于本机 gitignore 目录
`benchmarks/agent_e2e/results/smoke-flask-5014/run-flask-5014-20260828-033257/`
(凭证值不落盘,仅经环境变量注入)。

## 运行摘要

| 项 | 值 |
|---|---|
| 运行 ID(run_id) | `flask-5014-20260828-033257` |
| 评测对象 commit | `851a048a281f03373d90ea275a2a4957acdc0693`(master) |
| instance | `pallets__flask-5014`(SWE-bench Verified,Blueprints 空名校验) |
| 模型 / Provider | `deepseek-v4-flash` @ 火山方舟 OpenAI-compatible 端点 |
| 官方 verifier 镜像 | `swebench/sweb.eval.x86_64.pallets_1776_flask-5014@sha256:bde4fbdafa36141d4396944da88ec37aabdef612ed36920090675bccd0ca5d72` |
| 依赖版本 | harbor 0.22.0 / swebench 5.0.1 / deepeval 4.2.0 / opik 2.2.42 |
| 退出码 | `0`(流程完成且官方结果通过) |

## 四段结果

- **Harbor**:completed,patch 导出(`patch_sha256=165c0d5a…`),worker 9 turn、成本 $0.09。
- **官方 Harness**(swebench 5.0.1):completed,`resolved=true`(官方结果,`official=true`)。
- **DeepEval**(judge=deepseek-v4-flash):completed,三项固定指标
  TaskCompletionMetric / StepEfficiencyMetric / TrajectoryQuality 均产出分值与理由
  (基于脱敏轨迹摘要,按契约只评判受控元数据)。
- **Opik Cloud**(workspace `muyuzhong`,project `lion-agent-e2e`):
  `exported`,`trace_id=01a044bb-8dd3-7f65-800e-18fc0a7804d0`(257 spans)。

## 可复核命令

```bash
bash benchmarks/agent_e2e/results/smoke-flask-5014/run_smoke.sh
```

脚本前置:在 `results/smoke-flask-5014/smoke.env` 填写 `OPENAI_API_KEY`/
`OPENAI_BASE_URL`/`LION_MODEL`(Opik 凭证已在文件中)。生成冻结 manifest 的
命令与 catalog 卡片见同一目录 `build_catalog.py` / `build_manifest.py`。

## 本次修复的真实环境缺陷(随本 PR 提交)

真实 Linux smoke 暴露并修复了 4 处评估链缺陷:

1. `harbor_agent.py`:wheel 上传/安装必须使用合法 pip 文件名;swebench 任务镜像
   为 Python 3.11,以固定 python-build-standalone 资产在容器内安装 Python 3.12
   (Lion 要求 >=3.12,PEP 695);`run()` 签名适配 Harbor 0.22 的 `instruction=`
   关键字调用;worker 在任务 checkout 工作目录运行(取消错误 cwd 覆盖)。
2. `agent_worker.py`:worker 需把环境解析的 Provider 凭证传给 Agent 工厂,否则
   默认落到 anthropic 通道报"API 未配置"。
3. `worker_entrypoint.py`:补丁导出以任务卡片 `base_revision` 为 diff 基准,
   兼容 Agent 已自行 `git commit` 的改动(实测 Agent 会提交修复)。
4. `trace.py`:`redact_text` 截断加省略号后超出 `max_length` 一字符,导致
   `AgentRunSummary.final_text_preview` 校验失败;修复为严格不超过上限。