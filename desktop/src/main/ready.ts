/** sidecar ready 记录的严格解析与净化工具（纯函数，Main 与测试共用）。 */

import type { BootstrapFailure, SidecarReadyRecord } from "../shared/types";

const CAPABILITY_PATTERN = /^[A-Za-z0-9_-]{32,128}$/;

export type ReadyParseResult =
  | { ok: true; record: SidecarReadyRecord }
  | { ok: false; code: "invalid_ready"; reason: string };

/**
 * 解析 sidecar stdout 首条协议记录。
 * schema 严格：字段集合精确匹配，port 为 1..65535 整数，capability 满足
 * URL-safe token 契约；任何偏差都判启动失败，不做容错猜测。
 */
export function parseReadyLine(line: string): ReadyParseResult {
  const text = line.trim();
  if (!text) {
    return { ok: false, code: "invalid_ready", reason: "空记录" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, code: "invalid_ready", reason: "非 JSON 记录" };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { ok: false, code: "invalid_ready", reason: "记录不是对象" };
  }
  const record = parsed as Record<string, unknown>;
  if (record.type !== "ready" || record.version !== 1) {
    return { ok: false, code: "invalid_ready", reason: "协议类型或版本不支持" };
  }
  const port = record.port;
  if (typeof port !== "number" || !Number.isInteger(port) || port <= 0 || port > 65535) {
    return { ok: false, code: "invalid_ready", reason: "端口非法" };
  }
  const capability = record.capability;
  if (typeof capability !== "string" || !CAPABILITY_PATTERN.test(capability)) {
    return { ok: false, code: "invalid_ready", reason: "capability 非法" };
  }
  return {
    ok: true,
    record: { type: "ready", version: 1, port, capability },
  };
}

/** 净化 stderr 片段：移除已知 capability 等敏感 token。 */
export function sanitizeDiagnosticText(text: string, secrets: readonly string[]): string {
  let result = text;
  for (const secret of secrets) {
    if (secret) {
      result = result.split(secret).join("[REDACTED]");
    }
  }
  return result;
}

/** 保留 stderr 尾部（按字符截断），用于诊断视图。 */
export function tailText(text: string, maxChars: number): string {
  if (text.length <= maxChars) {
    return text;
  }
  return text.slice(text.length - maxChars);
}

export function failureFrom(
  code: BootstrapFailure["code"],
  message: string,
  stderrTail?: string,
): BootstrapFailure {
  return stderrTail === undefined ? { code, message } : { code, message, stderrTail };
}
