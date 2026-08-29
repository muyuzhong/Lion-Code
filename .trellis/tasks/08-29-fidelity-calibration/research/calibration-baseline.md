# 校准信任基线(2026-08-29)

## 结论

- 9 个校准夹具全部通过:6 类违规全部检出(召回),2 条正常轨迹零
  critical_veto(精确率),1 条旧格式 trace 正确降级。
- 旧真实 trace(smoke-batch,13 条 / 45796 事件)evidence 缺失率
  **100%**——历史数据无法做语义过程判定,`evidence_unavailable`
  是唯一诚实路径。

## 校准暴露并修复的真实缺陷

1. **call 级指纹缺陷**:`ToolExecutionEnd` 事件没有 args,其
   fingerprint 只含工具名(所有 run_shell end 相同)→
   `clean-error-then-recover` 被误判 `tool_error_not_recovered`。
   修复:`_call_fingerprint_stream` 取每个 call 的带参阶段(start/
   update)指纹,生命周期不参与调用比对。
2. 索引与 stream 两个 helper 供 repeated/error/context 三条规则共用,
   保证「同一 fingerprint 语义」一致。

## 信任范围

- 本基线只证明「投影 + 规则」链路在构造的语义化轨迹上成立;
- 真实新格式 trace(worker 升级后)的端到端复核留待下次烟囱运行时;
- 阈值(repeat=3 / error_repeat=2)与工具名单(write_file/edit_file)
  为构造默认值,未对校准集调参。
