# 实施计划

1. 实现 run_verified_evaluation 的顺序组合与最小请求对象，不增加通用 pipeline 抽象。
2. 扩展现有 benchmarks.agent_e2e CLI 增加 verified-run，固定单题参数和退出码。
3. 扩展现有 JSON/中文 Markdown 报告，展示四段结果、digest、成本、耗时和引用。
4. 添加 fake 集成测试，证明阶段顺序、失败隔离和 Agent 只执行一次。
5. 编写最短 Linux 安装/凭证/网络/运行说明。
6. 用一条固定 Verified instance 完成真实端到端 smoke 并保存受控证据。

## 验证

- compileall、tests/benchmarks、git diff --check。
- 项目 Ruff、format、mypy、radon、vulture、coverage 基线。
- Linux smoke 从干净 commit 执行，报告和 Opik UI 可通过 run_id 互相定位。

## 停止条件

- 任一底层任务尚未完成时不复制或临时替代其逻辑。
- 真实环境缺 Docker、凭证、预算或固定镜像时只报告 blocked，不伪造闭环。
