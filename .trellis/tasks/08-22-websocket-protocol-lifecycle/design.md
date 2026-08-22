# WebSocket 协议与连接生命周期设计

采用一个 action `TypeAdapter`、一个 app-scoped connection lease 和一个可关闭 Bridge。
Bridge 是 pending approvals、active run task 与 notice task 的唯一 owner；lease 只决定谁能
绑定 Session callback，不保存 transcript。断线按 deny -> cancel -> await -> unbind 顺序
收敛。客户端把 wire event 交给纯 reducer/adapter，再由 Hook 管理 socket 与历史加载。

不修改 Core event 名称，不兼容 snake_case，不对增量做服务端缓存。任何无法通过 strict
action model 的输入只产生 `protocol_error`。第二连接在 callback 绑定前拒绝。
