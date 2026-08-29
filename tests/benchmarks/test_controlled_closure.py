"""Controlled Experiment Closure 单元测试。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from benchmarks.agent_e2e.harbor_agent import LionInstalledAgent
from benchmarks.agent_e2e.harbor_runner import (
    HarborExecutionRequest,
    HarborSingleTaskRunner,
)
from benchmarks.agent_e2e.models import (
    ExperimentManifest,
    InjectionEvidence,
    RequestedVariant,
    ResolvedVariant,
)
from benchmarks.agent_e2e.variant_injection import (
    PromptVariantMap,
    ToolPolicyVariantMap,
    VariantInjectionSpec,
    attach_injection_spec,
    resolve_injection,
    spec_from_manifest,
)
from tests.benchmarks.test_agent_worker import _manifest, _task


def _spec() -> VariantInjectionSpec:
    prompt_fp = hashlib.sha256("受控提示词".encode()).hexdigest()
    tool_fp = hashlib.sha256(
        "\n".join(("read_file", "edit_file")).encode("utf-8")
    ).hexdigest()
    return VariantInjectionSpec(
        prompt_maps=(
            PromptVariantMap(
                prompt_version="prompt-v2",
                system_prompt="受控提示词",
                content_sha256=prompt_fp,
            ),
        ),
        tool_policy_maps=(
            ToolPolicyVariantMap(
                tool_policy_version="tools-v2",
                tool_names=("read_file", "edit_file"),
                content_sha256=tool_fp,
            ),
        ),
    )


class TestManifestSpecAttachment:
    def test_attach_and_read_round_trip(self) -> None:
        manifest = _manifest(_task())
        attached = attach_injection_spec(manifest, _spec())
        restored = spec_from_manifest(attached)
        assert restored == _spec()

    def test_original_manifest_unchanged(self) -> None:
        manifest = _manifest(_task())
        attach_injection_spec(manifest, _spec())
        assert spec_from_manifest(manifest) is None

    def test_missing_spec_returns_none(self) -> None:
        assert spec_from_manifest(_manifest(_task())) is None

    def test_attached_manifest_serializes(self) -> None:
        manifest = attach_injection_spec(_manifest(_task()), _spec())
        restored = ExperimentManifest.from_json(manifest.canonical_json())
        assert spec_from_manifest(restored) == _spec()


class TestInjectionEvidence:
    def test_resolution_carries_requested_and_resolved(self) -> None:
        from benchmarks.agent_e2e.models import ExperimentProfile

        profile = ExperimentProfile(
            profile_id="p1",
            model="m",
            provider="fake",
            prompt_version="prompt-v2",
            compression_version="compression-v1",
            tool_policy_version="tools-v2",
            seed=1,
            repeats=1,
            timeout_seconds=30,
            budget_usd=1,
            agent_code_sha="abcdef0",
            credential_env_vars=("K",),
        )
        resolution = resolve_injection(profile, _spec())
        assert resolution.resolved is True
        assert resolution.requested.prompt_version == "prompt-v2"
        assert resolution.requested.compression_version == "compression-v1"
        assert resolution.resolved_variant.prompt_hit is True
        assert resolution.resolved_variant.tool_policy_hit is True
        assert resolution.injection_fingerprint is not None

    def test_evidence_json_round_trip(self) -> None:
        evidence = InjectionEvidence(
            requested=RequestedVariant(prompt_version="prompt-v2"),
            resolved_variant=ResolvedVariant(prompt_hit=True),
            injection_fingerprint="f" * 64,
        )
        restored = InjectionEvidence.from_json(evidence.canonical_json())
        assert restored == evidence

    def test_requested_includes_compression_as_declared_only(self) -> None:
        from benchmarks.agent_e2e.models import ExperimentProfile

        profile = ExperimentProfile(
            profile_id="p1",
            model="m",
            provider="fake",
            prompt_version="prompt-v1",
            compression_version="compression-v9",
            tool_policy_version="tools-v1",
            seed=1,
            repeats=1,
            timeout_seconds=30,
            budget_usd=1,
            agent_code_sha="abcdef0",
            credential_env_vars=("K",),
        )
        resolution = resolve_injection(profile, VariantInjectionSpec())
        assert resolution.requested.compression_version == "compression-v9"
        assert resolution.injection_fingerprint is None


class TestHarborSourceFiles:
    def test_source_files_include_fidelity_modules(self) -> None:
        source_files = set(LionInstalledAgent._SOURCE_FILES)
        assert "evidence.py" in source_files
        assert "variant_injection.py" in source_files
        assert "worker_entrypoint.py" in source_files

    def test_source_files_are_importable_chain(self) -> None:
        # agent_worker 依赖 variant_injection,worker_entrypoint 依赖
        # evidence;两模块必须随 worker 一起进容器。
        source_files = set(LionInstalledAgent._SOURCE_FILES)
        for required in ("agent_worker.py", "models.py", "trace.py"):
            assert required in source_files


def _artifact(root: Path):
    from benchmarks.agent_e2e.artifact import CommitArtifact

    wheel = root / "lion_code.whl"
    wheel.write_bytes(b"wheel")
    return CommitArtifact(
        commit_sha="a" * 40,
        tree_sha="b" * 40,
        wheel_path=wheel,
        wheel_sha256=hashlib.sha256(b"wheel").hexdigest(),
        wheel_size_bytes=5,
        source_tree_sha256="c" * 64,
        repository_fingerprint="d" * 64,
        python_version="3.12.10",
        platform="linux",
    )


class TestHarborVariantValidation:
    def test_request_variant_requires_spec(self, tmp_path: Path) -> None:
        request = HarborExecutionRequest(
            repository_root=tmp_path,
            artifact=_artifact(tmp_path),
            manifest=_manifest(_task()),
            task=_task(),
            output_dir=tmp_path / "out",
            request_variant=True,
        )
        runner = HarborSingleTaskRunner()
        result = runner.run(request)
        assert result.result is not None
        assert "injection spec" in result.result.reason

    def test_request_variant_with_manifest_spec_passes_validation(
        self, tmp_path: Path
    ) -> None:
        task = _task()
        manifest = attach_injection_spec(_manifest(task), _spec())
        request = HarborExecutionRequest(
            repository_root=tmp_path,
            artifact=_artifact(tmp_path),
            manifest=manifest,
            task=task,
            output_dir=tmp_path / "out",
            injection_spec=_spec(),
            request_variant=True,
        )
        runner = HarborSingleTaskRunner()
        result = runner.run(request)
        # 校验通过后应继续走预检(缺少 harbor),不报 injection 错误。
        assert result.result is not None
        assert "injection spec" not in result.result.reason
