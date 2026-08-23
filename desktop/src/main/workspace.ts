/** workspace 选择与最近记录；只持久化路径，不持久化后端凭证。 */

import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";

const MAX_RECENT_WORKSPACES = 8;

export class WorkspaceController {
  constructor(private readonly storagePath: string) {}

  async validate(path: string): Promise<string> {
    if (!path.trim() || !isAbsolute(path)) throw new Error("workspace 必须是绝对路径");
    const absolute = resolve(path);
    const info = await stat(absolute);
    if (!info.isDirectory()) throw new Error("workspace 不是目录");
    return absolute;
  }

  async listRecent(): Promise<string[]> {
    try {
      const parsed: unknown = JSON.parse(await readFile(this.storagePath, "utf-8"));
      return Array.isArray(parsed) && parsed.every((item) => typeof item === "string") ? parsed : [];
    } catch {
      return [];
    }
  }

  async remember(path: string): Promise<void> {
    const recent = await this.listRecent();
    const next = [path, ...recent.filter((item) => item !== path)].slice(0, MAX_RECENT_WORKSPACES);
    await mkdir(dirname(this.storagePath), { recursive: true });
    await writeFile(this.storagePath, JSON.stringify(next), "utf-8");
  }
}
