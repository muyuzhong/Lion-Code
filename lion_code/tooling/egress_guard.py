"""Egress Guard：Level A 可承诺出口控制 + Level B 尽力而为观测。

信任域 = {本机 + LLM Provider}：provider 流量不经过本守卫，
守卫只拦 Agent 工具出口（web_fetch）并观测 shell 中的 URL。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from .context import ToolContext
from .middleware import NextCall
from .secret_provider import SecretStore
from .types import JSONValue, LionTool, ToolResult

_URL_RE = re.compile(r"""https?://[^\s"'<>`\\]+""")


def extract_urls(text: str) -> list[str]:
    return _URL_RE.findall(text)


def host_of(url: str) -> str | None:
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


def _load_settings(file_path: Path) -> dict | None:
    if not file_path.exists():
        return None
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


class EgressWhitelist:
    """host 集合白名单：provider 端点派生 + settings `egress.allow_hosts` 加白。"""

    def __init__(self, hosts: frozenset[str]) -> None:
        self._hosts = hosts

    def allows(self, host: str | None) -> bool:
        return host is not None and host.lower() in self._hosts

    @classmethod
    def from_sources(
        cls,
        *,
        home: Path,
        cwd: Path,
        provider_hosts: frozenset[str] = frozenset(),
    ) -> EgressWhitelist:
        hosts = {host.lower() for host in provider_hosts if host}
        for settings_path in (
            home / ".claude" / "settings.json",
            cwd / ".claude" / "settings.json",
        ):
            settings = _load_settings(settings_path)
            if not settings or not isinstance(settings.get("egress"), dict):
                continue
            raw = settings["egress"].get("allow_hosts", [])
            if isinstance(raw, list):
                hosts.update(str(host).lower() for host in raw if host)
        return cls(frozenset(hosts))


class EgressGuardMiddleware:
    """pre 相：web_fetch 未加白即阻断（S4 缺位期 fallback=block+audit）；
    run_shell 中的 URL 只提取观测并标注 best_effort，不做命令意图分析。"""

    phase: Literal["pre"] = "pre"

    def __init__(
        self,
        whitelist: EgressWhitelist,
        store: SecretStore | None = None,
    ) -> None:
        self.whitelist = whitelist
        self.store = store

    async def handle(
        self,
        *,
        tool: LionTool,
        context: ToolContext,
        tool_call_id: str,
        arguments: Mapping[str, JSONValue],
        call_next: NextCall,
    ) -> ToolResult:
        del context, tool_call_id
        if tool.name == "web_fetch":
            url = arguments.get("url")
            if isinstance(url, str):
                host = host_of(url)
                if not self.whitelist.allows(host):
                    return self._block(
                        host,
                        f"Egress blocked: destination not whitelisted: {host}",
                    )
                if self._fingerprint_hit(url):
                    return self._block(
                        host,
                        "Egress blocked: outbound URL carries a registered "
                        "secret fingerprint.",
                        fingerprint_hit=True,
                    )
        result = await call_next()
        if tool.capabilities.executes_process:
            command = arguments.get("command")
            hosts = [
                host
                for host in (host_of(url) for url in extract_urls(str(command or "")))
                if host
            ]
            if hosts:
                result.details = {
                    **result.details,
                    "egress_destination": ",".join(dict.fromkeys(hosts)),
                    "egress_best_effort": True,
                }
        return result

    def _block(
        self,
        host: str | None,
        message: str,
        *,
        fingerprint_hit: bool = False,
    ) -> ToolResult:
        details: dict[str, JSONValue] = {
            "egress_blocked": True,
            "egress_destination": host,
        }
        if fingerprint_hit:
            details["fingerprint_hit"] = True
        return ToolResult(content=message, is_error=True, details=details)

    def _fingerprint_hit(self, url: str) -> bool:
        if self.store is None:
            return False
        candidates = [url]
        try:
            split = urlsplit(url)
            candidates.append(split.path)
            candidates.extend(segment for segment in split.path.split("/") if segment)
            candidates.extend(value for _, value in parse_qsl(split.query))
        except ValueError:
            pass
        return any(self.store.matches(item) for item in candidates if item)
