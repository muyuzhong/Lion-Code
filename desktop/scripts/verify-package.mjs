import { listPackage } from "@electron/asar";
import { readdir, stat } from "node:fs/promises";
import { join, resolve } from "node:path";

const packageRoot = resolve(process.argv[2] ?? "release/win-unpacked");
const resources = join(packageRoot, "resources");
const sidecar = join(resources, "sidecar");

async function filesBelow(root) {
  const files = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) files.push(...await filesBelow(path));
    else files.push(path);
  }
  return files;
}

if (!(await stat(join(sidecar, "lion-sidecar.exe"))).isFile()) {
  throw new Error("安装态缺少 resources/sidecar/lion-sidecar.exe");
}
const sidecarFiles = await filesBelow(sidecar);
if (sidecarFiles.some((path) => path.toLowerCase().endsWith(".py"))) {
  throw new Error("安装态 sidecar 包含 Python 源码");
}

const members = listPackage(join(resources, "app.asar"))
  .map((member) => member.replaceAll("\\", "/").toLowerCase());
const forbidden = [
  "/frontend/",
  "/server/static/",
  "/node_modules/@playwright/",
  "/node_modules/electron-builder/",
  "/node_modules/typescript/",
  "/node_modules/vitest/",
];
const leaked = members.find((member) =>
  member.endsWith(".py") || forbidden.some((fragment) => member.includes(fragment))
);
if (leaked) throw new Error(`安装态包含旧 Web、Python 源码或开发依赖: ${leaked}`);

console.log("Electron 安装态资源验证通过");
