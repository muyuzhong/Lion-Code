# WebSocket 协议与连接生命周期执行计划

- [ ] 给所有 action model 增加 strict/extra-forbid 并建立 discriminated union adapter。
- [ ] Bridge 改为 typed dispatch、run gate、幂等 close 与 task result collection。
- [ ] App 建立 single-owner lease，保证 bind/unbind 身份一致。
- [ ] 前端建立 wire event/action union 与纯 reducer，Hook 只管理 I/O/state effects。
- [ ] 修复 tool/error/message final/reconnect/approval 清理。
- [ ] 接通 command/continue/compact；保留 steer/follow-up typed sender。
- [ ] 补 Python bridge/endpoint tests 与 frontend reducer/Hook tests。
- [ ] 运行父任务 S2 验证项，独立中文提交。
