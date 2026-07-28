# 阶段 5 实施计划

## 切片 1：Core/Provider 单路径

1. 将 `Agent` 初始化、`configure_api()`、child agent 配置和 `api_configured` 改为只依赖
   Agent 保存的 Provider 配置；移除 Core 开关和 optional 分支。
2. 把 goal、loop、plan、learning、dream 仍读取协议私有 history 的消费者迁到 canonical
   Core state，保持两协议现有行为。
3. 更新/补充 Core 双协议、API 热切换、child agent 和状态恢复测试，运行相关目标测试。
4. 残留扫描确认产品主流程不再进入 SDK chat；使用中文提交并直接推送 `master`。

## 切片 2：删除 SDK 查询、legacy chat 与压缩

1. 将所有 memory/evaluator/classifier/dream side-query 固定为 Provider 服务，删除
   `LegacySdkTextQueryService`、导出和 fallback。
2. 删除 `_chat_*`、`_call_*_stream`、协议私有 messages、`_compact_*` 与旧手工压缩
   pipeline；删除纯 legacy 测试，并为仍有效的契约补 Core 等价测试。
3. 运行 agent/provider/memory/application overflow 测试，扫描 legacy 符号为零。
4. 中文提交并直接推送 `master`。

## 切片 3：JSONL-only 会话

1. 删除 `lion_code/session.py` 旧 writer 和 Agent 对应的 serialize/auto-save/restore 分支。
2. 保留并验证 `session_runtime/legacy.py` 的发现、读取、迁移；断言源 `.json` 不变且新记录
   继续只写 JSONL。
3. 运行 session repository/runtime/migration 与 Agent restore 目标测试。
4. 中文提交并直接推送 `master`。

## 切片 4：移除 legacy TUI 与 UI sink

1. 对新 TUI 当前接受的 sink kind 做映射测试；优先证明已有 structured event/notice 已覆盖，
   只为真实缺口增加最小 typed application event 或 session callback。
2. 删除新 TUI mount/unmount 的 `ui.set_sink`、全局 sink 实现和对应 bridge 测试；保留 REPL
   直接 stdout 行为。
3. 删除 `legacy_tui.py`、`--legacy-tui`、入口回退和旧 TUI 测试，更新 CLI help 断言。
4. 运行 application/TUI 流式、工具、错误、retry、subagent 与 CLI 目标测试，确认正常 delta
   仍不全量重绘；中文提交并直接推送 `master`。

## 切片 5：依赖、文档与最终验收

1. 移除 `openai`、`anthropic` 直接依赖并同步锁文件；执行产品代码、测试、配置和文档的
   legacy 残留扫描，区分应删除的运行引用与应保留的迁移历史说明。
2. 更新 `UPSTREAM.md`、`docs/tui-migration-audit.md`、TUI/CLI 用户文档和 Trellis 规范，
   明确 JSONL-only write + legacy read migration 的最终边界。
3. 运行全量 pytest、compileall、项目已有 lint/type-check、`git diff --check`；记录
   `agent.py` 行数与两协议验证结果。
4. 执行 Trellis check，修复发现后使用中文提交并直接推送 `master`；等待用户验收后再归档。

## 完成后的下一阶段

阶段 5 验收并归档后，先根据最新迁移审计和仓库状态确认是否存在阶段 6；若路线图没有
新的预定义阶段，则转入“Core-only 稳定化”，优先处理全量真机回归、性能/可观测性和
文档收尾，而不自行扩张产品范围。
