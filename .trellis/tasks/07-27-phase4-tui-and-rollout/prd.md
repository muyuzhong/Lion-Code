# 阶段4:TUI 能力补齐与灰度扩围

> 上游依据:`docs/tui-migration-audit.md` §12 阶段 4;交接明细见
> `.trellis/workspace/zhangcx/journal-1.md` Session 1「遗留债务」。

## Goal

阶段 0-3 已完成:application 层(LionCodingSession/事件模型/命令注册表)、
lion_code/tui/(vendored 组件 + 新 app.py + PromptInput 补全)已接为默认入口
(fe8825d 起裸启动即新 TUI)。本阶段补齐用户可感知能力并扩大 Core Runtime
灰度,为阶段 5 删除 legacy 扫清依赖。

## Requirements(按优先级)

### A. Claude Code 式 picker(用户点名)

1. **model picker**:`/model` 从表单 Modal 换成可搜索列表(上游
   ModelPickerScreen 216 行现成)。前置:`application/provider_settings.py`
   模型目录——最小实现 = 保存过的配置 + 手填项合成 ModelChoice 列表,
   不引入 Tau 的 catalog.toml 目录制。
2. **session picker**:`/resume` 列表选择(上游 SessionPickerScreen 121 行)。
   前置:`application/session_manager.py` 会话索引(标题/touch,包装
   SessionRepository,不做第二套存储),发 SessionChangedEvent。

### B. 会话能力

3. thinking 档位:`/thinking <level>` + Shift+Tab 循环,写
   ThinkingLevelChangeEntry,发 ThinkingLevelChangedEvent。
4. AgentSettled 终端通知:接 tui/terminal_notification(设置项
   turn_notification: off/bell/desktop)。
5. 溢出压缩 + AutoRetry 事件链:对齐审计 §9 次序
   AgentEnd→CompactionStart(overflow)→CompactionEnd→AutoRetryStart→…→Settled。

### C. 灰度扩围(阶段 5 前置)

6. Anthropic 后端上 Core(factory 已支持,Agent 接线 + 验证);完成后
   移除新 TUI ModelScreen 的 Anthropic 封锁与入口 legacy 回退。
7. 子 Agent 上 Core(文本捕获复用 _capture_core_text)。
8. 3 处 side-query 迁 Provider(agent.py:_build_side_query/
   _run_evaluator_query/_run_classifier_query)+ LegacySdkTextQueryService
   替换 + dream.py 私有客户端解耦。

### D. 小项

9. Windows 拖拽路径归一化(file_drop 目前只认 POSIX 转义格式)。
10. 补全窗口溢出时迁上游按渲染行测量的 _visible_completion_state。

### E. 真机冒烟回归

11. LLM 流式输出必须复用已 vendor 的 `MarkdownStream` 增量渲染路径；单个
    text/thinking delta 不得重建完整 transcript，已挂载的历史消息保持 widget 身份稳定。

## Acceptance Criteria

- [x] 各项单测 + 集成测试;全量 pytest 绿
- [ ] 两后端 × 新 TUI 手工冒烟矩阵(文本/工具/权限/Plan/picker)
- [x] A1/A2 后:`/model`、`/resume` 不再出现表单式 Modal
- [x] C 完成后:`grep "import openai\|import anthropic" lion_code/` 仅剩
      agent.py legacy 对话路径(留给阶段 5 删除)
- [x] 连续 text/thinking delta 通过增量 widget API 写入，消息终止和工具边界正确收敛为
      canonical state，历史 transcript 不发生全量卸载/重挂载
- [x] 每完成一个子项按仓库惯例单独提交并推送,journal 记录

## Notes

- ponytail full 生效:每个子项先问"上游有没有现成组件/Lion 有没有既有实现"。
- 阶段 5(不在本任务):删 legacy 双后端/legacy_tui/session.py 旧 JSON 写、
  pyproject 移除 openai/anthropic。
