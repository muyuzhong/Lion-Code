# Implement: 过程证据投影(TraceEvent → ProcessEvidence)

> 配套 `prd.md` / `design.md`。按序执行;每步完成即核对。

## 0. 前置

- 分支:从 master 新建 `eval-process-evidence`(master 当前含 PR #143
  合并后状态;若未合并则从 PR 分支基出,实施时确认)。
- 先读 `lion_code/core/events.py`(typed event 全字段)、
  `benchmarks/agent_e2e/trace.py`(TraceEvent / sanitize / _PATH_KEYS)、
  `benchmarks/agent_e2e/worker_entrypoint.py`(recorder 构造点)、
  `tests/benchmarks/test_trace.py`(既有断言风格)。

## 1. 新增 `benchmarks/agent_e2e/evidence.py`

- [ ] 1.1 枚举:`ToolPhase` / `TargetScope` / `CompactionState` /
      `TerminationKind`。
- [ ] 1.2 `ProcessEvidence` 模型(design 3.1 字段;schema_version 沿用
      agent-e2e/v1 与 extensions 规则)。
- [ ] 1.3 `PathScopeRules` dataclass(design 3.3 默认值)。
- [ ] 1.4 `_command_heads` / 命令规范化(复用 process_verifier 思路,
      独立实现,不导入私有函数)。
- [ ] 1.5 `ProcessEvidenceProjector.project(event)`:
      - 识别 `tool_execution_start/update/end` → ToolEvidence(tool_call_id
        / tool_phase / tool_name / tool_fingerprint / is_error(仅 end));
      - 识别 `compaction_started/completed` → compaction 证据;
      - 识别 `turn_failed/cancelled` → termination 证据;
      - 路径字段 → target_scope + path_digest;
      - 命令字段 → validation_command / id / command_digest;
      - 未知事件返回 None。
- [ ] 1.6 `__all__` 导出。

## 2. 集成 `recorder` 与 worker

- [ ] 2.1 `TraceRecorder`:构造参数 `projector`;`record()` 同步投影;
      `evidence` 属性;`write_json` 输出 `evidence` 数组(排序确定)。
- [ ] 2.2 `record_tool_call()` 合成路径同步产出合成证据。
- [ ] 2.3 `worker_entrypoint.py`:投射 `ProcessEvidenceProjector(
      validation_commands=task.public_validation_commands)`。
- [ ] 2.4 旧文件读取:确认无 evidence 键时消费方(子任务二 reader)
      容错,本步只保证 write 侧新增不破坏既有 test_trace 断言
      (旧断言若断言 payload 键集合需同步更新)。

## 3. 新增 `tests/benchmarks/test_process_evidence.py`

- [ ] 3.1 typed event 构造(import lion_code.core.events 类,
      ToolExecutionStart/End/CompactionStarted/TurnFailed 等)。
- [ ] 3.2 tool 证据:start/update/end 三件套产出正确 tool_call_id /
      tool_phase / fingerprint;is_error 仅 end 有值。
- [ ] 3.3 路径分类:source/test/verifier/other 四类路径映射正确;
      序列化 JSON 无路径原文。
- [ ] 3.4 验证命令:`pytest -q` → validation_command=true +
      correct id + digest;不匹配 → false;命令正文不出现在 JSON。
- [ ] 3.5 compaction / termination 投影。
- [ ] 3.6 未知事件 → None 且不抛错。
- [ ] 3.7 `write_json` 输出 evidence 数组;隐私断言(全文扫描无
      命令/路径/输出明文)。
- [ ] 3.8 确定性:同事件两次 project 相同。

## 4. 验证

- [ ] 4.1 `pytest tests/benchmarks/test_process_evidence.py -q` 全绿。
- [ ] 4.2 `pytest tests/benchmarks/test_trace.py -q` 全绿(必要时按
      2.4 同步断言)。
- [ ] 4.3 `pytest tests/benchmarks -q` 全绿(环境性失败除外)。
- [ ] 4.4 ruff check 新文件与改动文件。

## 5. 提交

- [ ] 5.1 单次提交:`feat(benchmark): ProcessEvidence 语义化过程证据投影——tool_call_id/is_error/target_scope/validation 落盘`。