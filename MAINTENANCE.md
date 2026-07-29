# 维护台账

## 状态说明
- 候选：已识别但未处理
- 完成：已改动，附 commit
- 无需改动：已检查，判断不该动（不再重复检查）
- 待人工：需要我拍板，agent 不得自行决定

## 候选范围
| id    | 路径                                     | 描述                                                         | 预估风险 |
| ----- | ---------------------------------------- | ------------------------------------------------------------ | -------- |
| m-010 | lion_code/tui/（state.py、terminal_title.py） | format_terminal_command_result_block、TerminalTitleController 仍零引用；与阶段5 legacy 删除无关 | 中       |

## 瘦身账
| 轮次  | commit  | 文件数 | 净行数 | 测试数 | benchmark |
| ----- | ------- | ------ | ------ | ------ | --------- |
| m-001 | abc1234 | 3      | −29    | 142    | 通过      |
| m-008 | 2d092d3 | 4      | −115   | 238    | 18/18     |

## 完成
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
- 刻意没做：expand_skill_command——scope-reviewer 查明 tui/app.py:857 特判放行 /skill: 前缀，它是待接线半成品不是死代码，转待人工 m-012；tui/ 三个零引用符号阶段4 在途，转候选 m-010；session.py 旧读函数审计排阶段5，转候选 m-009
- 验证：unittest 238 通过、skipped 5（change-reviewer 复跑时 241，并行会话新增 3 条，只升未降）；compileall 通过；离线 benchmark 9 任务 + 9 类型/负载组合全过；hooks.py 零改动，六条 fail-closed 路径不受影响；diff 仅落在 4 个声明文件
- diff：4 文件，+1 −116，净 −115
- 评审：scope-reviewer = narrow（剔除 expand_skill_command）；change-reviewer = approve
- 删除依据：AST 全库零引用扫描 + 全仓库全文件类型字符串 grep（防按名路由）+ pyproject entry points + getattr/importlib 动态调用 + tests/ 引用检查，全部无命中
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
### m-007 · mcp_client.py 里两个未被任何测试覆盖的重连分支
- 无法判断是死代码还是未测的容错路径

### m-012 · application/skills.py 的 expand_skill_command 未接线
- /skill: 命令展开器零引用，但 tui/app.py:857 特判放行 /skill: 前缀文本却不做展开——半成品入口，不是死代码
- 接线（让 TUI 调它）还是删除（放弃 /skill: 命令），需人工拍板；scope-reviewer 建议按"待接线"处理

### m-013 · 两套 MEMORY.md 索引重建逻辑并存（重叠机制，只报告不合并）
- tools.py 的 _auto_update_memory_index（挂在 write_file 工具上）与 memory.py 的 _update_memory_index（被 dream.py 调用）功能重叠但格式化细节不同
- 合并会动模块边界，需人工拍板
