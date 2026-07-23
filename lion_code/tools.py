"""内置文件、搜索、Shell 与网页工具的底层实现。"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path

from .memory import get_memory_dir

# ─── 权限模式 ───────────────────────────────────────────────

PermissionMode = str  # 可用值由 CLI 的权限模式选项约束。

IS_WIN = sys.platform == "win32"

# ─── 类型别名 ───────────────────────────────────────────────

ToolDef = dict  # Anthropic 工具 schema；OpenAI 格式在 Agent 层转换。


# ─── 工具执行 ───────────────────────────────────────────────


def _read_file(inp: dict) -> str:
    try:
        # 解码失败时替换为 U+FFFD，而不是让混合编码文件中断 Agent 主循环；
        # 这也与 TypeScript 版本的 readFileSync("utf-8") 行为保持一致。
        content = Path(inp["file_path"]).read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        numbered = "\n".join(f"{i+1:4d} | {line}" for i, line in enumerate(lines))
        return numbered
    except Exception as e:
        return f"Error reading file: {e}"


def _write_file(inp: dict) -> str:
    try:
        path = Path(inp["file_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(inp["content"], encoding="utf-8")
        _auto_update_memory_index(str(path))
        lines = inp["content"].split("\n")
        line_count = len(lines)
        preview = "\n".join(f"{i+1:4d} | {l}" for i, l in enumerate(lines[:30]))
        trunc = f"\n  ... ({line_count} lines total)" if line_count > 30 else ""
        return f"Successfully wrote to {inp['file_path']} ({line_count} lines)\n\n{preview}{trunc}"
    except Exception as e:
        return f"Error writing file: {e}"


def _auto_update_memory_index(file_path: str) -> None:
    try:
        mem_dir = str(get_memory_dir())
        if file_path.startswith(mem_dir) and file_path.endswith(".md") and not file_path.endswith("MEMORY.md"):
            mem_path = Path(mem_dir)
            lines = ["# Memory Index", ""]
            for f in sorted(mem_path.glob("*.md")):
                if f.name == "MEMORY.md":
                    continue
                try:
                    raw = f.read_text(encoding="utf-8", errors="replace")
                    name_match = re.search(r"^name:\s*(.+)$", raw, re.MULTILINE)
                    type_match = re.search(r"^type:\s*(.+)$", raw, re.MULTILINE)
                    desc_match = re.search(r"^description:\s*(.+)$", raw, re.MULTILINE)
                    if name_match and type_match:
                        n = name_match.group(1).strip()
                        t = type_match.group(1).strip()
                        d = desc_match.group(1).strip() if desc_match else ""
                        lines.append(f"- **[{n}]({f.name})** ({t}) — {d}")
                except Exception:
                    pass
            (mem_path / "MEMORY.md").write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass


# ─── 编辑辅助：引号归一化与 diff ────────────────────────────


def _normalize_quotes(s: str) -> str:
    s = re.sub("[\u2018\u2019\u2032]", "'", s)
    s = re.sub('[\u201c\u201d\u2033]', '"', s)
    return s


def _find_actual_string(file_content: str, search_string: str) -> str | None:
    if search_string in file_content:
        return search_string
    norm_search = _normalize_quotes(search_string)
    norm_file = _normalize_quotes(file_content)
    idx = norm_file.find(norm_search)
    if idx != -1:
        return file_content[idx:idx + len(search_string)]
    return None


def _generate_diff(old_content: str, old_string: str, new_string: str) -> str:
    before_change = old_content.split(old_string)[0]
    line_num = before_change.count("\n") + 1
    old_lines = old_string.split("\n")
    new_lines = new_string.split("\n")

    parts = [f"@@ -{line_num},{len(old_lines)} +{line_num},{len(new_lines)} @@"]
    for l in old_lines:
        parts.append(f"- {l}")
    for l in new_lines:
        parts.append(f"+ {l}")
    return "\n".join(parts)


def _edit_file(inp: dict) -> str:
    try:
        path = Path(inp["file_path"])
        content = path.read_text(encoding="utf-8", errors="replace")

        actual = _find_actual_string(content, inp["old_string"])
        if not actual:
            return f"Error: old_string not found in {inp['file_path']}"

        count = content.count(actual)
        if count > 1:
            return f"Error: old_string found {count} times in {inp['file_path']}. Must be unique."

        new_content = content.replace(actual, inp["new_string"], 1)
        path.write_text(new_content, encoding="utf-8")

        diff = _generate_diff(content, actual, inp["new_string"])
        quote_note = " (matched via quote normalization)" if actual != inp["old_string"] else ""
        return f"Successfully edited {inp['file_path']}{quote_note}\n\n{diff}"
    except Exception as e:
        return f"Error editing file: {e}"


def _list_files(inp: dict) -> str:
    try:
        base = Path(inp.get("path") or ".")
        pattern = inp["pattern"]
        files = []
        extra = 0
        for p in base.glob(pattern):
            if p.is_file():
                rel = str(p.relative_to(base) if base != Path(".") else p)
                # 按路径段精确排除 node_modules 和隐藏目录，避免误伤名称中仅包含
                # `node_modules` 的普通文件；忽略 dotfile 与 TS 的 `dot:false` 一致。
                if any(part == "node_modules" or part.startswith(".") for part in Path(rel).parts):
                    continue
                # 返回值最多保留 200 项，但继续计数，让模型知道结果是否被截断。
                if len(files) < 200:
                    files.append(rel)
                else:
                    extra += 1
        if not files:
            return "No files found matching the pattern."
        result = "\n".join(files)
        if extra:
            result += f"\n... and {extra} more"
        return result
    except Exception as e:
        return f"Error listing files: {e}"


def _grep_search(inp: dict) -> str:
    pattern = inp["pattern"]
    path = inp.get("path") or "."
    include = inp.get("include")

    # Linux/macOS 优先使用系统 grep；Windows 或执行失败时走纯 Python 实现。
    if not IS_WIN:
        try:
            args = ["grep", "--line-number", "--color=never", "-r"]
            if include:
                args.append(f"--include={include}")
            args.extend(["--", pattern, path])
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 1:
                return "No matches found."
            if result.returncode == 0:
                lines = [l for l in result.stdout.split("\n") if l]
                output = "\n".join(lines[:100])
                if len(lines) > 100:
                    output += f"\n... and {len(lines) - 100} more matches"
                return output
            # 退出码 1 代表无匹配；其他非零状态交给 Python 路径重试。
        except Exception:
            pass  # 系统 grep 不可用时继续使用跨平台实现。

    # 纯 Python 实现保证 Windows 和缺少 grep 的环境仍可工作。
    return _grep_python(pattern, path, include)


def _grep_python(pattern: str, directory: str, include: str | None) -> str:
    try:
        regex = re.compile(pattern)
    except re.error as e:
        # 模型生成的非法正则应成为工具错误文本，不能让异常逃逸并终止 Agent 主循环。
        return f"Error: invalid regex pattern: {e}"
    include_pattern = include
    matches: list[str] = []
    extra = 0

    def walk(d: str) -> None:
        nonlocal extra
        try:
            entries = os.listdir(d)
        except Exception:
            return
        for name in entries:
            if name.startswith(".") or name == "node_modules":
                continue
            full = os.path.join(d, name)
            if os.path.islink(full):
                continue
            if os.path.isdir(full):
                walk(full)
                continue
            if include_pattern and not fnmatch.fnmatch(name, include_pattern):
                continue
            try:
                text = Path(full).read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.split("\n")):
                    if regex.search(line):
                        # 最多展示 100 个匹配，同时保留遗漏数量供模型判断完整性。
                        if len(matches) < 100:
                            matches.append(f"{full}:{i+1}:{line}")
                        else:
                            extra += 1
            except Exception:
                pass

    walk(directory)
    if not matches:
        return "No matches found."
    output = "\n".join(matches)
    if extra:
        output += f"\n... and {extra} more matches"
    return output


def _run_shell(inp: dict) -> str:
    try:
        timeout_ms = inp.get("timeout", 30000)
        timeout_s = timeout_ms / 1000
        result = subprocess.run(
            inp["command"],
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        output = result.stdout or ""
        if result.returncode != 0:
            stderr = f"\nStderr: {result.stderr}" if result.stderr else ""
            stdout = f"\nStdout: {result.stdout}" if result.stdout else ""
            return f"Command failed (exit code {result.returncode}){stdout}{stderr}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {inp.get('timeout', 30000)}ms"
    except Exception as e:
        return f"Error: {e}"


def _web_fetch(inp: dict) -> str:
    import urllib.request
    import urllib.error

    url = inp.get("url", "")
    max_length = inp.get("max_length", 50000)
    # urllib 默认允许 file:// 等协议，会把“网页读取”变成本地文件泄露入口；
    # 因此边界处只接受 http(s)，并与 TS 实现保持一致。
    if not url.lower().startswith(("http://", "https://")):
        return "Error: only http(s) URLs are supported"
    req = urllib.request.Request(url, headers={"User-Agent": "lion-code/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "")
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return f"HTTP error: {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return f"Error fetching {url}: {e.reason}"
    except Exception as e:
        return f"Error fetching {url}: {e}"

    if "html" in content_type:
        text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]*>", " ", text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

    if len(text) > max_length:
        text = text[:max_length] + f"\n\n[... truncated at {max_length} characters]"

    return text or "(empty response)"
