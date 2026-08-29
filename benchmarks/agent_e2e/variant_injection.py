"""Harness 变异注入:把 profile 的版本声明映射为真实运行配置。

PR #143 审查问题二:worker 从未把 prompt_version / tool_policy_version
注入 Harness,导致「B 版本比 A 好」无法归因于「compression v2 导致
提升」。本模块提供受控映射表,把声明的版本解析为可注入配置
(custom_system_prompt / tool_registry),未命中时保持默认行为。

隐私边界:映射表内容由评测侧维护,不含凭证;compression_version
**永不**参与注入(尚无运行开关,如实标注为声明字段)。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from pydantic import Field, model_validator

from .models import (
    ExperimentManifest,
    ExperimentProfile,
    InjectionEvidence,
    RequestedVariant,
    ResolvedVariant,
    VersionedModel,
)


class PromptVariantMap(VersionedModel):
    """prompt 版本 → 系统提示词文本的受控映射。"""

    prompt_version: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(min_length=1)
    content_sha256: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def _validate_content_fingerprint(self) -> PromptVariantMap:
        expected = hashlib.sha256(self.system_prompt.encode("utf-8")).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("PromptVariantMap content_sha256 must match system_prompt")
        return self


class ToolPolicyVariantMap(VersionedModel):
    """tool_policy 版本 → 工具集白名单的受控映射;空名单不注入。"""

    tool_policy_version: str = Field(min_length=1, max_length=128)
    tool_names: tuple[str, ...] = ()
    content_sha256: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def _validate_content_fingerprint(self) -> ToolPolicyVariantMap:
        expected = hashlib.sha256(
            "\n".join(self.tool_names).encode("utf-8")
        ).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError(
                "ToolPolicyVariantMap content_sha256 must match tool_names"
            )
        return self


class VariantInjectionSpec(VersionedModel):
    """一次实验的注入映射表;默认空 = 全按现状运行。"""

    prompt_maps: tuple[PromptVariantMap, ...] = ()
    tool_policy_maps: tuple[ToolPolicyVariantMap, ...] = ()
    extensions: dict[str, Any] = Field(default_factory=dict)


class InjectionResolution(VersionedModel):
    """解析结果:命中映射时给出注入值;未命中时 resolved=False。

    同时携带完整执行证据(requested/resolved/fingerprint),供
    worker 落盘为可复核的 InjectionEvidence。
    """

    resolved: bool = False
    custom_system_prompt: str | None = None
    tool_names: tuple[str, ...] = ()
    injection_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    requested: RequestedVariant = Field(default_factory=RequestedVariant)
    resolved_variant: ResolvedVariant = Field(default_factory=ResolvedVariant)
    extensions: dict[str, Any] = Field(default_factory=dict)


def resolve_injection(
    profile: ExperimentProfile,
    spec: VariantInjectionSpec | None = None,
) -> InjectionResolution:
    """把 profile 的版本声明解析为可注入配置;compression 永不注入。

    ``tool_registry`` 不在结果中序列化(VersionedModel 的严格 JSON 边界
    不承载运行时对象);worker 侧按 ``tool_names`` 从默认工具集过滤
    构造 registry(与 agent_builder 的 builtin+internal 组合一致)。
    """

    active_spec = spec or VariantInjectionSpec()
    prompt_map = next(
        (
            item
            for item in active_spec.prompt_maps
            if item.prompt_version == profile.prompt_version
        ),
        None,
    )
    tool_map = next(
        (
            item
            for item in active_spec.tool_policy_maps
            if item.tool_policy_version == profile.tool_policy_version
        ),
        None,
    )
    resolved = prompt_map is not None or tool_map is not None
    fingerprint_parts: list[str] = []
    if prompt_map is not None:
        fingerprint_parts.append(prompt_map.content_sha256)
    if tool_map is not None:
        fingerprint_parts.append(tool_map.content_sha256)
    return InjectionResolution(
        resolved=resolved,
        custom_system_prompt=(
            prompt_map.system_prompt if prompt_map is not None else None
        ),
        tool_names=tuple(tool_map.tool_names) if tool_map is not None else (),
        injection_fingerprint=(
            hashlib.sha256("\n".join(fingerprint_parts).encode("utf-8")).hexdigest()
            if fingerprint_parts
            else None
        ),
        requested=RequestedVariant(
            prompt_version=profile.prompt_version,
            tool_policy_version=profile.tool_policy_version,
            compression_version=profile.compression_version,
        ),
        resolved_variant=ResolvedVariant(
            prompt_hit=prompt_map is not None,
            tool_policy_hit=tool_map is not None,
        ),
    )


def attach_injection_spec(
    manifest: ExperimentManifest,
    spec: VariantInjectionSpec,
) -> ExperimentManifest:
    """把注入映射表写入 manifest.extensions(可比性不变量,两侧共享)。

    manifest 是 frozen 模型,返回新实例;仅写入受控 JSON 对象,
    不含敏感内容。
    """

    extensions = dict(manifest.extensions)
    extensions["variant_injection_spec"] = json.loads(spec.canonical_json())
    return manifest.model_copy(update={"extensions": extensions})


def spec_from_manifest(
    manifest: ExperimentManifest,
) -> VariantInjectionSpec | None:
    """从 manifest.extensions 读取注入映射表;缺失或畸形返回 None。"""

    raw = manifest.extensions.get("variant_injection_spec")
    if not isinstance(raw, dict):
        return None
    try:
        return VariantInjectionSpec.from_dict(raw)
    except Exception:
        return None


def build_filtered_registry(tool_names: Sequence[str]) -> Any:
    """按白名单从默认工具集(builtin + internal)过滤出 ToolRegistry。

    与 agent_builder 的默认组合保持一致;只注册白名单命中的工具,
    其余默认工具不出现(等价于 tool_policy 收窄工具面)。
    """

    from lion_code.composition.agent_builder import LocalCommandExecutionBackend
    from lion_code.tooling import ToolRegistry
    from lion_code.tooling.builtin import create_builtin_tools
    from lion_code.tooling.internal import create_internal_tools

    allowed = frozenset(tool_names)
    registry = ToolRegistry()
    backend = LocalCommandExecutionBackend()
    for tool in [*create_builtin_tools(backend), *create_internal_tools()]:
        if tool.name in allowed:
            registry.register(tool)
    return registry


__all__ = [
    "InjectionEvidence",
    "InjectionResolution",
    "PromptVariantMap",
    "RequestedVariant",
    "ResolvedVariant",
    "ToolPolicyVariantMap",
    "VariantInjectionSpec",
    "attach_injection_spec",
    "build_filtered_registry",
    "resolve_injection",
    "spec_from_manifest",
]
