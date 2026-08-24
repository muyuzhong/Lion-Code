import { execFile } from "node:child_process";
import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

import { _electron as electron, expect, test } from "@playwright/test";

import type { DesktopBridge } from "../src/shared/types";

const execFileAsync = promisify(execFile);

async function sidecarsForWorkspace(workspace: string): Promise<number[]> {
  const escapedWorkspace = workspace.replaceAll("'", "''");
  const command = [
    "$items = Get-CimInstance Win32_Process -Filter \"Name = 'lion-sidecar.exe'\"",
    `$items | Where-Object CommandLine -like '*${escapedWorkspace}*' | ForEach-Object ProcessId`,
  ].join("; ");
  const { stdout } = await execFileAsync("powershell", ["-NoProfile", "-Command", command]);
  return stdout.trim() ? stdout.trim().split(/\s+/).map(Number) : [];
}

test("packaged app owns the bundled sidecar through shutdown", async () => {
  const executablePath = process.env.LION_PACKAGED_APP;
  if (!executablePath) throw new Error("LION_PACKAGED_APP 未指向已打包 Lion.exe");

  const root = await mkdtemp(join(tmpdir(), "lion-packaged-smoke-"));
  const workspace = join(root, "workspace");
  const stateHome = join(root, "state");
  const userData = join(root, "user-data");
  await Promise.all([mkdir(workspace), mkdir(stateHome), mkdir(userData)]);
  const environment = { ...process.env };
  delete environment.PYTHONPATH;
  const application = await electron.launch({
    executablePath,
    args: [`--user-data-dir=${userData}`],
    env: {
      ...environment,
      LION_PYTHON: "missing-system-python.exe",
      LION_SIDECAR_STATE_HOME: stateHome,
    },
  });
  try {
    const page = await application.firstWindow();
    await page.evaluate(async (path) => {
      const global = globalThis as typeof globalThis & { lionDesktop: DesktopBridge };
      await global.lionDesktop.connectWorkspace(path);
    }, workspace);
    await expect.poll(() => page.evaluate(async () => {
      const global = globalThis as typeof globalThis & { lionDesktop: DesktopBridge };
      return (await global.lionDesktop.getBootstrapState()).phase;
    }), { timeout: 60_000 }).toBe("ready");
    await expect.poll(() => sidecarsForWorkspace(workspace), { timeout: 20_000 }).toHaveLength(1);
  } finally {
    await application.close();
  }
  await expect.poll(() => sidecarsForWorkspace(workspace), { timeout: 20_000 }).toEqual([]);
});
