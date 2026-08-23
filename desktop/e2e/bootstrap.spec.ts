import { _electron as electron, expect, test } from "@playwright/test";
import type { DesktopBridge } from "../src/shared/types";

test("launches the sandboxed lion protocol shell", async () => {
  const application = await electron.launch({ args: ["."] });
  try {
    const page = await application.firstWindow();
    await expect(page).toHaveURL("lion://app/");
    await expect(page.getByRole("heading", { name: "选择一个工作区" })).toBeVisible();
    expect(await page.evaluate(() => {
      const global = globalThis as typeof globalThis & { lionDesktop: DesktopBridge };
      return typeof global.lionDesktop.selectWorkspace;
    })).toBe("function");
    expect(await page.evaluate(() => {
      const global = globalThis as typeof globalThis & { lionDesktop: DesktopBridge };
      return {
        require: "require" in global,
        process: "process" in global,
        ipcRenderer: "ipcRenderer" in global.lionDesktop,
      };
    })).toEqual({ require: false, process: false, ipcRenderer: false });
  } finally {
    await application.close();
  }
});
