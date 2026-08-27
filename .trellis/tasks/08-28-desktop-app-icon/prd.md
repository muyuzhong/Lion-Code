# PRD：桌面客户端更换应用图标

## 需求

将 `desktop/` Electron 客户端（当前使用 Electron 默认图标）替换为用户提供的自定义图标。

## 输入

用户提供一张方形 PNG（≥512×512，透明背景），存放于 `desktop/build/icon.png`。

## 改动范围

1. `desktop/package.json` 的 `build.win` 增加 `"icon": "build/icon.png"`，打包出的 exe 与 NSIS 安装器使用新图标（electron-builder 自动将 PNG 转为多尺寸 .ico）。
2. `desktop/src/main/window.ts` 的 BrowserWindow 增加 `icon: "build/icon.png"`，运行时窗口/任务栏使用新图标。

## 验收标准

- `npm run package:win`（或 `npm run build && npx electron-builder --win`）产出的安装包 exe 显示新图标。
- 运行中的窗口与任务栏显示新图标。
- 不引入新依赖、不改动其他功能。

## 不做（YAGNI）

- macOS `.icns`：当前无 mac 打包目标，暂不处理。
- 应用内（渲染进程）品牌图：不在本次范围。