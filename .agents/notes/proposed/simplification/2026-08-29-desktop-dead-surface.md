# Agent Note: 删除 desktop 侧全仓零消费者导出与死 IPC 通道

- Status: proposed
- 日期: 2026-08-29
- 范围: `desktop/src/shared/types.ts`、`desktop/src/main/ipc.ts`、`desktop/src/preload/bridge.ts`、`desktop/src/renderer/src/lionRuntime.ts`、`desktop/tests/preload-bridge.test.ts`

## Problem

desktop（Electron）侧有一批只被定义/测试消费的导出与 IPC 通道：

1. **零消费者常量**：`DESKTOP_APP_ORIGIN`（`shared/types.ts:3`）与 `READY_PROTOCOL_VERSION`（:4）——全仓 import 零命中；`"lion://app"` 字面量反而硬编码在 `window-security.ts:12`、`protocol.ts:7`、`renderer-path.ts:7`、`e2e/bootstrap.spec.ts:8`、`lion_code/server/app.py:48`；`version !== 1` 硬编码在 `ready.ts:35`。`messageText`（`lionRuntime.ts:342`）函数体只是 `return message.content`，无调用者。
2. **死 IPC 通道**：`getAppInfo`（`types.ts:57`、`bridge.ts:13`、`ipc.ts:37` + allowlist `ipc.ts:70`）与 `getBackendEndpoint`（:65/:19/:40/:71）——renderer 从不调用（`App.tsx:33` 硬编码 "v1.0.0" 而非经 getAppInfo；endpoint 已随 BootstrapState 推送）；唯一消费是 `tests/preload-bridge.test.ts:11,16,21`（非生产）。

## Proposal

1. 删除 `DESKTOP_APP_ORIGIN`/`READY_PROTOCOL_VERSION`/`messageText` 三个导出；可选把 `lion://app` 与 version 字面量收敛到统一常量出处（同一候选的增强项）。
2. 删除 `getAppInfo`/`getBackendEndpoint` 在 types/bridge/ipc 三层的定义与 allowlist 条目（ipc.ts:70-71 移除两项）；同步改 `tests/preload-bridge.test.ts`；App 版本号硬编码是独立小缺陷，可改接真实版本。

## Why not keep it

「导出声明而无消费者」与「主进程/preload/协议三层定义只为测试存在」都是死面；desktop-sidecar spec §2 承诺的 getBackendEndpoint 是现状文档而非消费者。删实现保留 spec 同步（或仅删 spec 对应承诺行），恢复成本各约 3 行。

## Acceptance criteria

- `rg -n "DESKTOP_APP_ORIGIN|READY_PROTOCOL_VERSION|messageText|getAppInfo|getBackendEndpoint" desktop/src/` 零命中（文档/测试除外）。
- `desktop` 侧 vitest/playwright 测试全绿；sidecar 冒烟（`verify_desktop_delivery.py`）通过。

## Risks

- `getBackendEndpoint` 若未来 renderer 需要动态获取 endpoint 需重建三层——当前 endpoint 经 BootstrapState 推送已覆盖，风险低；收敛字面量时需全仓（含 `lion_code/server/app.py`）同步。