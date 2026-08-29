"""Harness 变异注入与受控实验语义单元测试。"""

from __future__ import annotations

import hashlib

import pytest

from benchmarks.agent_e2e.models import ExperimentProfile
from benchmarks.agent_e2e.variant_injection import (
    InjectionResolution,
    PromptVariantMap,
    ToolPolicyVariantMap,
    VariantInjectionSpec,
    build_filtered_registry,
    resolve_injection,
)


def _profile(
    *,
    prompt_version: str = "prompt-v1",
    tool_policy_version: str = "tools-v1",
    compression_version: str = "compression-v1",
    agent_code_sha: str = "abcdef0",
) -> ExperimentProfile:
    return ExperimentProfile(
        profile_id="profile-1",
        model="fake-model",
        provider="fake",
        prompt_version=prompt_version,
        compression_version=compression_version,
        tool_policy_version=tool_policy_version,
        seed=1,
        repeats=1,
        timeout_seconds=30,
        budget_usd=1,
        agent_code_sha=agent_code_sha,
        credential_env_vars=("EVAL_API_KEY",),
    )


def _prompt_map(
    version: str = "prompt-v2", text: str = "你是一个编码助手"
) -> PromptVariantMap:
    return PromptVariantMap(
        prompt_version=version,
        system_prompt=text,
        content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _tool_map(
    version: str = "tools-v2",
    names: tuple[str, ...] = ("read_file", "edit_file", "run_shell"),
) -> ToolPolicyVariantMap:
    return ToolPolicyVariantMap(
        tool_policy_version=version,
        tool_names=names,
        content_sha256=hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest(),
    )


class TestResolveInjection:
    def test_prompt_hit_returns_system_prompt(self) -> None:
        spec = VariantInjectionSpec(prompt_maps=(_prompt_map(),))
        result = resolve_injection(_profile(prompt_version="prompt-v2"), spec)
        assert result.resolved is True
        assert result.custom_system_prompt == "你是一个编码助手"
        assert result.prompt_sha256 == spec.prompt_maps[0].content_sha256
        assert result.tool_policy_sha256 is None

    def test_tool_policy_hit_returns_tool_names(self) -> None:
        spec = VariantInjectionSpec(tool_policy_maps=(_tool_map(),))
        result = resolve_injection(_profile(tool_policy_version="tools-v2"), spec)
        assert result.resolved is True
        assert result.tool_names == ("read_file", "edit_file", "run_shell")
        assert result.tool_policy_sha256 == spec.tool_policy_maps[0].content_sha256
        assert result.prompt_sha256 is None

    def test_no_hit_keeps_defaults(self) -> None:
        result = resolve_injection(_profile(), VariantInjectionSpec())
        assert result.resolved is False
        assert result.custom_system_prompt is None
        assert result.tool_names == ()
        assert result.injection_fingerprint is None

    def test_compression_never_injected(self) -> None:
        # 只有 compression 变化时,即使声明了映射也不能解析。
        result = resolve_injection(
            _profile(compression_version="compression-v9"),
            VariantInjectionSpec(),
        )
        assert result.resolved is False

    def test_injection_fingerprint_present_on_hit(self) -> None:
        spec = VariantInjectionSpec(
            prompt_maps=(_prompt_map(),),
            tool_policy_maps=(_tool_map(),),
        )
        result = resolve_injection(
            _profile(prompt_version="prompt-v2", tool_policy_version="tools-v2"),
            spec,
        )
        assert result.injection_fingerprint is not None
        assert len(result.injection_fingerprint) == 64

    def test_resolution_json_round_trip(self) -> None:
        spec = VariantInjectionSpec(prompt_maps=(_prompt_map(),))
        result = resolve_injection(_profile(prompt_version="prompt-v2"), spec)
        restored = InjectionResolution.from_json(result.canonical_json())
        assert restored == result


class TestVariantMapValidation:
    def test_prompt_map_rejects_bad_fingerprint(self) -> None:
        with pytest.raises(ValueError, match="content_sha256"):
            PromptVariantMap(
                prompt_version="prompt-v2",
                system_prompt="text",
                content_sha256="b" * 64,
            )

    def test_tool_map_rejects_bad_fingerprint(self) -> None:
        with pytest.raises(ValueError, match="content_sha256"):
            ToolPolicyVariantMap(
                tool_policy_version="tools-v2",
                tool_names=("read_file",),
                content_sha256="b" * 64,
            )

    def test_empty_tool_whitelist_is_rejected(self) -> None:
        # 空白名单会产生「tool_policy_hit=True 但实际未注入」的假注入,
        # 直接禁止,而不是让证据撒谎。
        with pytest.raises(ValueError, match="at least 1"):
            ToolPolicyVariantMap(
                tool_policy_version="tools-v2",
                tool_names=(),
                content_sha256=hashlib.sha256(b"").hexdigest(),
            )

    def test_maps_round_trip(self) -> None:
        spec = VariantInjectionSpec(
            prompt_maps=(_prompt_map(),),
            tool_policy_maps=(_tool_map(),),
        )
        restored = VariantInjectionSpec.from_json(spec.canonical_json())
        assert restored == spec


class TestBuildFilteredRegistry:
    def test_registry_contains_only_allowed_tools(self) -> None:
        registry = build_filtered_registry(("read_file", "edit_file"))
        names = {tool.name for tool in registry.active_tools()}
        assert {"read_file", "edit_file"} <= names
        assert "run_shell" not in names

    def test_empty_whitelist_yields_empty_registry(self) -> None:
        registry = build_filtered_registry(())
        assert list(registry.active_tools()) == []


class TestWorkerInjection:
    """run_agent_worker 把解析出的注入真正传给 factory。"""

    def test_prompt_and_tool_policy_are_injected(self) -> None:
        import asyncio
        import tempfile
        from pathlib import Path

        from benchmarks.agent_e2e.agent_worker import run_agent_worker
        from benchmarks.agent_e2e.backend import AgentExecutionRequest
        from tests.benchmarks.test_agent_worker import _manifest, _task

        captured: dict = {}
        evidence_holder: dict = {}

        class FakeAdapter:
            def __init__(self, **kwargs) -> None:
                captured.update(kwargs)

            def subscribe(self, _listener):
                return lambda: None

            async def run(self, _prompt, *, timeout=None):
                return None

            async def close(self) -> None:
                return None

        async def main() -> None:
            task = _task()
            manifest = _manifest(task)
            profile = manifest.profile.model_copy(
                update={
                    "prompt_version": "prompt-v2",
                    "tool_policy_version": "tools-v2",
                    "profile_id": "profile-v2",
                }
            )
            manifest_with_variant = manifest.model_copy(
                update={
                    "profile": profile,
                    "profile_fingerprint": profile.fingerprint(),
                }
            )
            spec = VariantInjectionSpec(
                prompt_maps=(
                    PromptVariantMap(
                        prompt_version="prompt-v2",
                        system_prompt="受控提示词",
                        content_sha256=hashlib.sha256(
                            "受控提示词".encode()
                        ).hexdigest(),
                    ),
                ),
                tool_policy_maps=(
                    ToolPolicyVariantMap(
                        tool_policy_version="tools-v2",
                        tool_names=("read_file", "edit_file"),
                        content_sha256=hashlib.sha256(
                            "\n".join(("read_file", "edit_file")).encode()
                        ).hexdigest(),
                    ),
                ),
            )
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                workspace = root / "ws"
                workspace.mkdir()
                request = AgentExecutionRequest(
                    manifest=manifest_with_variant,
                    task=task,
                    attempt=1,
                    agent_workspace=workspace,
                    session_root=root / "sessions",
                )
                worker_result = await run_agent_worker(
                    request,
                    agent_factory=lambda **kwargs: FakeAdapter(**kwargs),
                    injection_spec=spec,
                )
                evidence_holder["evidence"] = worker_result.injection_evidence

        asyncio.run(main())
        assert captured.get("custom_system_prompt") == "受控提示词"
        registry = captured.get("tool_registry")
        assert registry is not None
        names = {tool.name for tool in registry.active_tools()}
        assert "read_file" in names
        assert "run_shell" not in names
        evidence = evidence_holder["evidence"]
        assert evidence is not None
        assert evidence.requested.prompt_version == "prompt-v2"
        assert evidence.resolved_variant.prompt_hit is True
        assert evidence.resolved_variant.tool_policy_hit is True
        assert evidence.injection_fingerprint is not None

    def test_no_spec_keeps_default_injection(self) -> None:
        import asyncio
        import tempfile
        from pathlib import Path

        from benchmarks.agent_e2e.agent_worker import run_agent_worker
        from benchmarks.agent_e2e.backend import AgentExecutionRequest
        from tests.benchmarks.test_agent_worker import _manifest, _task

        captured: dict = {}

        class FakeAdapter:
            def __init__(self, **kwargs) -> None:
                captured.update(kwargs)

            def subscribe(self, _listener):
                return lambda: None

            async def run(self, _prompt, *, timeout=None):
                return None

            async def close(self) -> None:
                return None

        async def main() -> None:
            task = _task()
            manifest = _manifest(task)
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                workspace = root / "ws"
                workspace.mkdir()
                request = AgentExecutionRequest(
                    manifest=manifest,
                    task=task,
                    attempt=1,
                    agent_workspace=workspace,
                    session_root=root / "sessions",
                )
                await run_agent_worker(
                    request,
                    agent_factory=lambda **kwargs: FakeAdapter(**kwargs),
                )

        asyncio.run(main())
        assert captured.get("custom_system_prompt") is None
        assert captured.get("tool_registry") is None
