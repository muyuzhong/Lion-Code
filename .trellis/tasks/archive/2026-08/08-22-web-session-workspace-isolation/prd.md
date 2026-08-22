# Web 会话 workspace 隔离

## Goal

确保 Web 只能枚举和恢复当前 cwd 的 Session，不因空结果、异常路径或直接 id 请求扩大
到其他 workspace。

## Requirements

- list 与 resume 共用一个 current-cwd eligibility 判断。
- 明确其他 cwd 永不返回；缺 cwd 的 legacy session 保留现有可恢复语义。
- resolve 失败只比较规范化路径文本，不回退为全量 sessions。
- 跨 workspace resume 与不存在 id 都返回 404，不泄漏存在性差异。

## Acceptance Criteria

- [ ] 当前 cwd 零匹配返回空列表。
- [ ] Windows 大小写、resolve 异常、legacy cwd 缺失均有测试。
- [ ] 其他 cwd id 无法通过直接 resume 恢复。

## Dependency

基于 S1 受保护 REST surface；可与 S2/S3 代码逻辑独立回滚。

## Out of Scope

跨 workspace 搜索、导入、复制或迁移 Session。
