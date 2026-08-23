import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { WorkspaceController } from "../src/main/workspace";

describe("WorkspaceController", () => {
  it("validates directories and keeps newest unique paths", async () => {
    const root = await mkdtemp(join(tmpdir(), "lion-workspace-"));
    const storage = join(root, "settings", "recent.json");
    const controller = new WorkspaceController(storage);
    const path = await controller.validate(root);
    await controller.remember(path);
    await controller.remember(path);
    expect(await controller.listRecent()).toEqual([path]);
    expect(JSON.parse(await readFile(storage, "utf-8"))).toEqual([path]);
  });

  it.each(["", ".", "relative/path"])("rejects a non-absolute path", async (path) => {
    const controller = new WorkspaceController("unused.json");
    await expect(controller.validate(path)).rejects.toThrow("绝对路径");
  });
});
