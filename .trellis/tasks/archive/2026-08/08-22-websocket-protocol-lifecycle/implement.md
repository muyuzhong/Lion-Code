# WebSocket 协议与连接生命周期执行计划

- [x] 给所有 action model 增加 strict/extra-forbid 并建立 discriminated union adapter。
- [x] Bridge 改为 typed dispatch、run gate、幂等 close 与 task result collection。
- [x] App 建立 single-owner lease，保证 bind/unbind 身份一致。
- [x] 前端建立 wire event/action union 与纯 reducer，Hook 只管理 I/O/state effects。
- [x] 修复 tool/error/message final/reconnect/approval 清理。
- [x] 接通 command/continue/compact；保留 steer/follow-up typed sender。
- [x] 补 Python bridge/endpoint tests 与 frontend reducer/Hook tests。
- [x] 运行父任务 S2 验证项，准备独立中文提交。
