"""Egress Guard：Level A 可承诺出口控制 + Level B 尽力而为观测。

信任域 = {本机 + LLM Provider}：provider 流量不经过本守卫，
守卫只拦 Agent 工具出口（web_fetch）并观测 shell 中的 URL。
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
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

    @property
    def hosts(self) -> frozenset[str]:
        return self._hosts

    def allows(self, host: str | None) -> bool:
        return host is not None and host.lower() in self._hosts

    def update_hosts(self, hosts: frozenset[str]) -> None:
        self._hosts = hosts

    @classmethod
    def _read_hosts_from_sources(
        cls,
        *,
        home: Path,
        cwd: Path,
        provider_hosts: frozenset[str] = frozenset(),
    ) -> frozenset[str]:
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
        return frozenset(hosts)

    @classmethod
    def from_sources(
        cls,
        *,
        home: Path,
        cwd: Path,
        provider_hosts: frozenset[str] = frozenset(),
    ) -> EgressWhitelist:
        return cls(
            cls._read_hosts_from_sources(
                home=home, cwd=cwd, provider_hosts=provider_hosts
            )
        )

    def reload(
        self,
        *,
        home: Path,
        cwd: Path,
        provider_hosts: frozenset[str] = frozenset(),
    ) -> None:
        self._hosts = self._read_hosts_from_sources(
            home=home, cwd=cwd, provider_hosts=provider_hosts
        )


def load_configured_egress_hosts(
    *,
    home: Path | None = None,
    cwd: Path | None = None,
) -> list[str]:
    """按用户级后项目级顺序读取 settings.json 中的原始 allow_hosts 配置列表。"""
    home = home or Path.home()
    cwd = cwd or Path.cwd()
    hosts: list[str] = []
    for settings_path in (
        home / ".claude" / "settings.json",
        cwd / ".claude" / "settings.json",
    ):
        settings = _load_settings(settings_path)
        if not settings or not isinstance(settings.get("egress"), dict):
            continue
        raw = settings["egress"].get("allow_hosts", [])
        if isinstance(raw, list):
            for host in raw:
                if isinstance(host, str) and host.strip():
                    normalized = host.strip()
                    if normalized not in hosts:
                        hosts.append(normalized)
    return hosts


def save_project_egress_hosts(cwd: Path, allow_hosts: list[str]) -> None:
    """原子写回项目级 .claude/settings.json 中的 egress.allow_hosts。"""
    settings_path = cwd / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {}
    if settings_path.exists():
        loaded = _load_settings(settings_path)
        if isinstance(loaded, dict):
            data = loaded

    if not isinstance(data.get("egress"), dict):
        data["egress"] = {}

    data["egress"]["allow_hosts"] = [
        host.strip() for host in allow_hosts if isinstance(host, str) and host.strip()
    ]

    tmp_file = settings_path.with_suffix(f".tmp.{os.getpid()}")
    tmp_file.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_file, settings_path)


def normalize_egress_hosts(allow_hosts: Sequence[str]) -> list[str]:
    """把 API 输入归一化为可持久化的精确 host 列表。"""

    normalized_hosts: list[str] = []
    for raw in allow_hosts:
        host = str(raw).strip()
        if not host:
            continue
        if host.lower().startswith(("http://", "https://")):
            extracted = host_of(host)
            if extracted:
                host = extracted
        host = host.lower()
        if host not in normalized_hosts:
            normalized_hosts.append(host)
    return normalized_hosts


@dataclass(slots=True)
class EgressConfiguration:
    """Tooling-owned settings port for reading and refreshing Egress state."""

    home: Path
    cwd: Path
    whitelist: EgressWhitelist | None = None
    provider_hosts: frozenset[str] = frozenset()

    def configured_hosts(self) -> list[str]:
        return load_configured_egress_hosts(home=self.home, cwd=self.cwd)

    def configure_hosts(self, allow_hosts: Sequence[str]) -> list[str]:
        normalized_hosts = normalize_egress_hosts(allow_hosts)
        save_project_egress_hosts(self.cwd, normalized_hosts)
        if self.whitelist is not None:
            self.whitelist.reload(
                home=self.home,
                cwd=self.cwd,
                provider_hosts=self.provider_hosts,
            )
        return normalized_hosts


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
