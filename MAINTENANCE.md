# 维护台账

## 状态说明
- 候选：已识别但未处理
- 完成：已改动，附 commit
- 无需改动：已检查，判断不该动（不再重复检查）
- 待人工：需要我拍板，agent 不得自行决定

## 候选范围
（暂无；m-010 已完成，见「完成」。）

## 瘦身账
| 轮次  | commit  | 文件数 | 净行数 | 测试数 | benchmark |
| ----- | ------- | ------ | ------ | ------ | --------- |
| m-001 | abc1234 | 3      | −29    | 142    | 通过      |
| m-008 | 2d092d3 | 4      | −115   | 238    | 18/18     |
| 二阶段 | 5238ae6 | 17     | −197   | 533    | 通过      |
| 三阶段-1 | （本提交） | 3      | agent.py −245 | 543    | 通过      |
| 三阶段-2 | （本提交） | 3      | agent.py −89，新增协调器 347 行 | 547    | 通过      |

## 完成
### 三阶段-1 · 2026-08-01 · 拆解 agent.py:autonomy_runtime 提取
- 范围:把 /goal、/loop、Auto Mode 的状态与协调循环从 `agent.py` 迁入新模块 `autonomy_runtime.py`(纯提示词已在 `autonomy.py`)。
- 做了:`AutonomyRuntime` + `AutonomyHost` 窄协议(经 host 回调 Agent 的 chat/emit/budget/side-query,非 Service Locator);迁入 6 个状态字段 + 16 个方法;Agent 保留薄委托(公共 API 不变)+ 6 个状态属性委托;side-query 工具(`_run_evaluator_query`/`_run_classifier_query`/`_canonical_side_messages`)暂留 agent.py(learning 后续也用)。先补 /goal、/loop 特征测试(10 例,`tests/test_autonomy_goal_loop.py`)再迁移。
- 验证:全量 543 passed(+10 新测试)、6 skipped;compileall 通过;ruff 218 / format 146 / mypy 105 均持平基线。agent.py 2397->2152(−245)。
- 路线图:后续 session_memory_coordinator -> subagent_factory -> learning_runtime -> agent_lifecycle -> agent_runtime Core 协调,目标 agent.py ~1200 行。

### 三阶段-2 · 2026-08-03 · 提取 agent.py:session_memory_coordinator
- 范围:把项目级 Session Memory、项目指令 Overlay、Auto Memory 召回协调、Dream
  入口和每轮短期状态更新迁入 `session_memory_coordinator.py`；Core canonical
  history、JSONL schema、Provider 协议和 TUI 命令解析不变。
- 做了:`SessionMemoryCoordinator` + `SessionMemoryHost` 窄协议持有项目身份、
  Session Memory、三层 Overlay、MemoryCoordinator、Dream 和轮后更新；Agent
  保留公共入口、Core 消费所需的兼容属性和 Provider/clear/restore/abort/close
  路径，既有测试替身继续有效。
- 验证:全量 547 passed、6 skipped、6 subtests；compileall 通过；import-linter
  3 契约 KEPT；ruff 218 / format 146 / mypy 102 / vulture 5，未引入新的静态
  错误。新协调器测试覆盖状态所有权、query service 绑定、兼容 setter 和公共
  委托。已知 GBK spinner `UnicodeEncodeError` 警告仍存在。
- 结果:`agent.py` 1,890 -> 1,801 行（−89）；新增 `session_memory_coordinator.py`
  347 行和 4 个特征测试。下一步按路线进入 `subagent_factory`。

### 二阶段 · 2026-08-01 · 清掉已知的架构债务（m-012 / m-007 / m-013 / m-010 + 第二套路径扫描）
- **m-012**：删除 `/skill:` 半成品入口。`application/skills.py` 移除 tau `<skill>` 块机器（expand_skill_command / format_skill_invocation / parse_skill_invocation / SkillInvocation，保留 `Skill`）；TUI autocomplete 的 `/skill:` 处理、`app.py` 与 `commands.py` 的 `/skill:` 特判、`state.py` 展示分支、相关测试一并移除。接线（让 TUI `/skill:` 走 `lion_code.skills.resolve_skill_prompt`）转预留任务 `08-01-tui-skill-wiring`。
- **m-007**：`mcp_client.py` 两条未测容错分支（连接失败隔离、读循环 EOF）补测试 `tests/test_mcp_client.py`（5 例）。确认无实际「重连」逻辑——只有失败隔离与 EOF 退出，属容错路径非死代码。
- **m-013**：合并两套 MEMORY 索引重建。`memory.py` 新增 `rebuild_memory_index_if_needed` 作为唯一写入入口，`tools.py:_write_file` 改调它，删除 `_auto_update_memory_index`（脆弱正则版）。
- **m-010**：清理 TUI 零引用符号。`terminal_title.py` 薄化为仅 `sanitize_terminal_title`（删 `TerminalTitleController` / `build_terminal_title` / `osc_terminal_title_sequence` / `terminal_title_supported` 及专用常量）；删 `state.py` 的 `format_terminal_command_result_block` 与 `TERMINAL_COMMAND_OUTPUT_PREVIEW_LINES`。
- **第二套路径扫描（Task 5）**：扫描 Provider/Session/Tool/Memory。结论：**无第二套权威路径**——core 运行时迁移（PR#7-12）成立，现存均为分层（接口/实现、存储/运行时、格式/回放）。Provider：`core/provider.py`（Protocol）+ `providers/`（factory+impls）+ `providers/provider.py`（重导出 shim）；Session：`core/session/`（格式+回放）+ `session_runtime/`（record/repository，活）+ `session_memory.py`（项目状态，异概念）；Tool：`core/tools.py`（类型）+ `tooling/`（框架）+ `tools.py`（handler 后端，被 builtin.py 包装，活）；Memory：`memory.py`（存储）+ `memory_runtime/`（运行时）+ `session_memory.py` / `core/session/memory.py`（异概念）。唯一真正行为重复（MEMORY 索引）已由 m-013 处理。可选小清理（`providers/provider.py` shim 收敛、`core/session/memory.py` 命名澄清）defer。
- 验证：全量 533 passed（532 − 4 个 `/skill:` 专项测试 + 5 个 MCP 容错测试）、6 skipped；compileall 通过；ruff 218 / format 146（由 147 改善）/ mypy 105 / vulture 5 均未超基线。
- 基线同步：`docs/quality-baseline-2026-08.md` §9/§10/§11 与 `.github/workflows/ci.yml` format 阈值 147→146。
- diff：17 文件，+204 −401，净 −197（不含本台账更新）。

### m-011 · 2026-07-29 · commits 9e92d09 / 3370351
- 范围：旧 SDK 对话/压缩、legacy TUI 与全局 UI sink。
- 做了：删除协议专用 chat/stream/压缩路径、旧 TUI/CLI 回退和全局 sink；新 TUI 复用 Core/application 事件与会话 notice，REPL 保留直接 stdout。
- 验证：双协议/provider/application/session/TUI/CLI 矩阵 277 passed、1 skipped；产品禁止符号扫描零命中。

### m-009 · 2026-07-29 · commit 1f95fb0
- 范围：旧 `lion_code/session.py` JSON writer。
- 做了：新会话只写 JSONL；保留旧 `.json` 的只读发现、恢复和迁移，源文件不变。
- 验证：session/runtime/application 目标测试纳入阶段5矩阵。

### m-008 · 2026-07-27 · commit 2d092d3
- 范围：零引用死函数清理（Tau 移植残留），分支 slim/round-2
- 做了：删 providers/config.py 的 openai_compatible_config_from_env 及仅被它调用的三个私有 env helper（连带孤立的 environ 导入）；删 providers/http.py 的 get_json；删 memory.py 的 save_memory/delete_memory（连带孤立的 _slugify 与 format_frontmatter 导入）；删 subagent.py 的 reset_agent_cache
- 刻意没做：expand_skill_command--scope-reviewer 查明 tui/app.py:857 特判放行 /skill: 前缀，它是待接线半成品不是死代码，转待人工 m-012；tui/ 三个零引用符号阶段4 在途，转候选 m-010；session.py 旧读函数审计排阶段5，转候选 m-009
- 验证：unittest 238 通过、skipped 5（change-reviewer 复跑时 241，并行会话新增 3 条，只升未降）；compileall 通过；离线 benchmark 9 任务 + 9 类型/负载组合全过；hooks.py 零改动，六条 fail-closed 路径不受影响；diff 仅落在 4 个声明文件
- diff：4 文件，+1 −116，净 −115
- 评审：scope-reviewer = narrow（剔除 expand_skill_command）；change-reviewer = approve
- 删除依据：AST 全库零引用扫描 + 全仓库全文件类型字符串 grep（防按名路由）+ pyproject entry points + getattr/importlib 动态调用 + tests/ 引用检查，全部无命中
- 后续：m-012 / m-010 已由「二阶段」处理（见上）。

### m-001 · 2026-07-26 · commit abc1234
- 做了：合并 3 处重复的权限判断分支
- 刻意没做：没有改判断顺序，顺序是语义的一部分
- 验证：全量测试 142 通过；compileall 通过；离线 benchmark 校验通过
- diff：3 文件，+12 −41，全部在声明范围内

## 无需改动
### m-004 · lion_code/dream.py 的 JSON 校验分支
- 看起来冗余，实际覆盖了 dream agent 返回非法 action 的路径
- tests/test_dream.py 有对应断言

## 待人工
- m-007 / m-012 / m-013 已处理（见「完成」）。m-012 的接线（让 TUI `/skill:` 走权威 skill 路径）转预留任务 `08-01-tui-skill-wiring`，待后续实施。
