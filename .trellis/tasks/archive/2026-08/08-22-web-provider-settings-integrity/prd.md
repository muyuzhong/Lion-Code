# Provider 设置一致性

## Goal

让 Web 的局部 Provider 设置更新保持 Runtime、持久配置和 UI 草稿一致，并彻底隔离
真实用户凭证与测试。

## Requirements

- 局部请求与 `session.provider_config()` 当前快照合并为完整目标配置。
- Runtime 仍只由 ProviderController 修改；配置使用原子写，失败必须补偿回旧快照。
- Provider 切换校验目标凭证；同 Provider model-only 更新保留现有 key/base URL。
- SettingsModal 打开/服务状态改变时初始化草稿，不写回未加载默认值。
- ModelSelector 保留 provider/model 配对。
- config path/load/save 可注入测试，所有测试只用 `tmp_path`。

## Acceptance Criteria

- [ ] model-only 和空 API key 的同 Provider 保存成功。
- [ ] Provider 切换缺凭证返回 4xx，未改 Runtime/磁盘。
- [ ] Provider 构建失败或写盘失败后两侧均保持旧配置。
- [ ] 设置窗口展示真实 provider/model/thinking，不意外覆盖。
- [ ] 测试前后真实 `~/.lion-code/config.json` 内容和 mtime 不变。

## Dependency

基于 S1 capability-aware REST client；不依赖 S2 连接内部实现。

## Out of Scope

云端密钥库、密钥迁移、加密配置格式和多配置 profile。
