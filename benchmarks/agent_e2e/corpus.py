"""Lion 历史回放任务集的公开卡、私有证据与准入检查。"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .catalog import validate_catalog
from .models import Catalog, TaskResources, TaskSpec, TaskSplit, TaskStatus


CORPUS_ID = "lion-historical-replay"
CORPUS_VERSION = "v1"
PRIVATE_VERIFIER_IDENTITY = "lion-historical-patch-provenance/v1"
_REPOSITORY = "https://github.com/muyuzhong/Lion-Code"
_RESOURCES = TaskResources(
    cpu_cores=2.0,
    memory_mb=4096,
    disk_mb=4096,
    estimated_minutes=20,
)


class CorpusAdmissionError(ValueError):
    """任务卡、私有证据或历史 provenance 不满足准入条件。"""


@dataclass(frozen=True, slots=True)
class PrivateEvidence:
    """仅 evaluator 可见的 gold provenance；不要传给 Agent container。"""

    task_id: str
    gold_revision: str
    gold_patch_sha256: str
    base_verdict: str = "fail"
    gold_verdict: str = "pass"
    stability_repeats: int = 3
    leakage_review_passed: bool = True

    @property
    def expected_stability_digest(self) -> str:
        """从不可变来源字段导出三次 preflight 应得到的稳定摘要。"""

        payload = {
            "base_verdict": self.base_verdict,
            "gold_patch_sha256": self.gold_patch_sha256,
            "gold_revision": self.gold_revision,
            "gold_verdict": self.gold_verdict,
            "task_id": self.task_id,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def expected_stability_digests(self) -> tuple[str, ...]:
        """返回私有 evidence 预期保存的三次一致 preflight 摘要。"""

        return (self.expected_stability_digest,) * self.stability_repeats


@dataclass(frozen=True, slots=True)
class HistoricalPreflight:
    """一次三轮 historical patch-provenance 检查的受控结果。"""

    task_id: str
    base_verdict: str
    gold_verdict: str
    run_digests: tuple[str, ...]

    @property
    def stable(self) -> bool:
        return len(self.run_digests) == 3 and len(set(self.run_digests)) == 1


def bundled_catalog() -> Catalog:
    """返回 V1 的公开 catalog；调用方可序列化后单独挂载给 Agent。"""

    return Catalog(
        catalog_id=CORPUS_ID,
        catalog_version=CORPUS_VERSION,
        tasks=_PUBLIC_TASKS,
    )


def bundled_private_evidence() -> dict[str, PrivateEvidence]:
    """返回 evaluator 私有 evidence 副本，避免调用方修改模块级映射。"""

    return dict(_PRIVATE_EVIDENCE)


def validate_corpus(
    catalog: Catalog,
    evidence: Mapping[str, PrivateEvidence],
    *,
    feedback_task_ids: Iterable[str] = (),
) -> None:
    """校验任务配额、公开/私有对应、稳定证据与 split 防泄漏规则。"""

    validate_catalog(catalog)
    tasks = tuple(task for task in catalog.tasks if task.status is TaskStatus.ACTIVE)
    if len(catalog.tasks) != 30 or len(tasks) != 30:
        raise CorpusAdmissionError("Corpus must contain exactly 30 active tasks")
    family_counts = Counter(task.family for task in tasks)
    if family_counts != Counter(
        {"cross_file_refactor": 10, "bugfix": 10, "feature": 10}
    ):
        raise CorpusAdmissionError("Corpus must contain 10 tasks for each required family")
    split_counts = Counter(task.split for task in tasks)
    if split_counts != Counter(
        {TaskSplit.REGRESSION: 18, TaskSplit.HOLDOUT: 12}
    ):
        raise CorpusAdmissionError("Corpus must use an 18 regression / 12 holdout split")

    task_ids = {task.task_id for task in tasks}
    if set(evidence) != task_ids:
        raise CorpusAdmissionError("Private evidence IDs must match active public task IDs")
    _validate_evidence(tasks, evidence)
    _validate_feedback_holdout(tasks, feedback_task_ids)
    _validate_split_commit_isolation(tasks, evidence)


def validate_bundled_corpus(*, feedback_task_ids: Iterable[str] = ()) -> Catalog:
    """校验并返回仓库内置 corpus，供 CLI/回归门禁显式调用。"""

    catalog = bundled_catalog()
    validate_corpus(
        catalog,
        bundled_private_evidence(),
        feedback_task_ids=feedback_task_ids,
    )
    return catalog


def run_historical_preflight(
    task: TaskSpec,
    evidence: PrivateEvidence,
    *,
    repository_root: str | Path,
    repeats: int = 3,
) -> HistoricalPreflight:
    """执行纯 Git provenance 检查，不运行 Docker、模型或语义 hidden test。

    `base fail` 表示 base 与 gold 树不同，`gold pass` 表示 gold binary diff
    可从 Git 重建且通过格式检查。两者仅用于任务来源准入，不能解释为任务
    行为已经被语义 verifier 验证。
    """

    if repeats != 3:
        raise CorpusAdmissionError("Historical preflight requires exactly three repeats")
    if task.task_id != evidence.task_id:
        raise CorpusAdmissionError("Task and private evidence IDs do not match")
    if task.base_revision == evidence.gold_revision:
        raise CorpusAdmissionError("Base and gold revisions must differ")

    root = Path(repository_root).resolve()
    run_digests: list[str] = []
    for _ in range(repeats):
        _require_git_object(root, task.base_revision)
        _require_git_object(root, evidence.gold_revision)
        patch = _git_bytes(
            root,
            "diff",
            "--binary",
            task.base_revision,
            evidence.gold_revision,
        )
        patch_sha256 = hashlib.sha256(patch).hexdigest()
        if patch_sha256 != task.gold_evidence_hash:
            raise CorpusAdmissionError(f"Gold patch hash mismatch for {task.task_id}")
        if patch_sha256 != evidence.gold_patch_sha256:
            raise CorpusAdmissionError(f"Private patch hash mismatch for {task.task_id}")
        if _git_status(root, "diff", "--quiet", task.base_revision, evidence.gold_revision) != 1:
            raise CorpusAdmissionError(f"Base provenance did not fail for {task.task_id}")
        if _git_status(root, "diff", "--check", task.base_revision, evidence.gold_revision):
            raise CorpusAdmissionError(f"Gold patch format failed for {task.task_id}")
        run_digests.append(evidence.expected_stability_digest)

    result = HistoricalPreflight(
        task_id=task.task_id,
        base_verdict="fail",
        gold_verdict="pass",
        run_digests=tuple(run_digests),
    )
    if not result.stable or result.run_digests != evidence.expected_stability_digests:
        raise CorpusAdmissionError(f"Historical preflight is unstable for {task.task_id}")
    return result


def _validate_evidence(
    tasks: tuple[TaskSpec, ...],
    evidence: Mapping[str, PrivateEvidence],
) -> None:
    for task in tasks:
        item = evidence[task.task_id]
        if item.gold_patch_sha256 != task.gold_evidence_hash:
            raise CorpusAdmissionError(f"Gold hash mismatch for {task.task_id}")
        if item.gold_revision == task.base_revision:
            raise CorpusAdmissionError(f"Base and gold revisions match for {task.task_id}")
        if item.base_verdict != "fail" or item.gold_verdict != "pass":
            raise CorpusAdmissionError(f"Base/gold evidence is incomplete for {task.task_id}")
        if item.stability_repeats != 3:
            raise CorpusAdmissionError(f"Evidence is not three-run stable for {task.task_id}")
        if len(item.expected_stability_digests) != 3 or len(
            set(item.expected_stability_digests)
        ) != 1:
            raise CorpusAdmissionError(f"Evidence digest is not stable for {task.task_id}")
        if not item.leakage_review_passed:
            raise CorpusAdmissionError(f"Leakage review did not pass for {task.task_id}")


def _validate_feedback_holdout(
    tasks: tuple[TaskSpec, ...],
    feedback_task_ids: Iterable[str],
) -> None:
    holdout_ids = {task.task_id for task in tasks if task.split is TaskSplit.HOLDOUT}
    overlap = holdout_ids.intersection(feedback_task_ids)
    if overlap:
        raise CorpusAdmissionError(
            f"Feedback-derived tasks cannot be holdout: {sorted(overlap)!r}"
        )


def _validate_split_commit_isolation(
    tasks: tuple[TaskSpec, ...],
    evidence: Mapping[str, PrivateEvidence],
) -> None:
    references: dict[TaskSplit, set[str]] = {
        TaskSplit.REGRESSION: set(),
        TaskSplit.HOLDOUT: set(),
    }
    for task in tasks:
        references[task.split].add(task.base_revision)
        references[task.split].add(evidence[task.task_id].gold_revision)
    overlap = references[TaskSplit.REGRESSION].intersection(
        references[TaskSplit.HOLDOUT]
    )
    if overlap:
        raise CorpusAdmissionError(
            f"Regression and holdout share historical commits: {sorted(overlap)!r}"
        )


def _require_git_object(repository_root: Path, revision: str) -> None:
    if _git_status(repository_root, "cat-file", "-e", f"{revision}^{{commit}}"):
        raise CorpusAdmissionError(f"Historical commit is unavailable: {revision}")


def _git_bytes(repository_root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository_root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()[:160]
        raise CorpusAdmissionError(f"Git command failed: {' '.join(args)}: {detail}")
    return result.stdout


def _git_status(repository_root: Path, *args: str) -> int:
    result = subprocess.run(
        ["git", "-C", str(repository_root), *args],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode


def _task(
    task_id: str,
    family: str,
    split: TaskSplit,
    base_revision: str,
    gold_evidence_hash: str,
    prompt: str,
    validation_command: str,
    involved_files: tuple[str, ...],
    difficulty: int,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        family=family,
        split=split,
        repository=_REPOSITORY,
        base_revision=base_revision,
        public_prompt=prompt,
        public_setup=("python -m pip install -e .",),
        public_validation_commands=(validation_command,),
        verifier_identity=PRIVATE_VERIFIER_IDENTITY,
        gold_evidence_hash=gold_evidence_hash,
        difficulty=difficulty,
        involved_files=involved_files,
        resources=_RESOURCES,
        status=TaskStatus.ACTIVE,
        extensions={
            "corpus_version": CORPUS_VERSION,
            "evidence_kind": "historical_patch_provenance",
        },
    )


_PUBLIC_TASKS: tuple[TaskSpec, ...] = (
    _task("lion-cross-file-refactor-01", "cross_file_refactor", TaskSplit.REGRESSION, "3370351f2cfc4a30927e79a50f0ab9276880e6ef", "55136a2acf17a2643dac9885fa7556e9902aa782568fc97fb61b7fc26c7a8e68", "收敛 Core-only runtime 的依赖与文档边界，删除已经失效的旧路径引用，并保持测试和基准入口一致。", "python -m pytest -q tests/test_context_formal_benchmark.py", ("lion_code/agent_runtime.py", "benchmarks/context_management/formal_benchmark.py", "tests/test_context_formal_benchmark.py"), 4),
    _task("lion-cross-file-refactor-02", "cross_file_refactor", TaskSplit.REGRESSION, "1f95fb02ac9afc546b3b3f44705d86ce1607a43b", "bc30736737c96b03c2c1669e8bfdee1f3dfa0651dd9223dbc61b91e8b8b51440", "移除 legacy TUI 与全局输出桥，让默认 TUI 和 Agent 观察器保留单一输出所有权。", "python -m pytest -q tests/application/test_coding_session.py", ("lion_code/agent.py", "lion_code/application/session.py", "lion_code/tui/app.py"), 5),
    _task("lion-cross-file-refactor-03", "cross_file_refactor", TaskSplit.REGRESSION, "9e92d09f9619d3985a31bf54878c487e1a268d0c", "7ae4f1d8ebe99fa01bae11abc01406e65672482ad297ec0569e8eb288b71228c", "把会话持久化收敛到 JSONL 单一路径，并保持 Dream 和集成恢复行为一致。", "python -m pytest -q tests/integration/test_agent_core_runtime.py", ("lion_code/dream.py", "lion_code/session.py", "tests/integration/test_agent_core_runtime.py"), 3),
    _task("lion-cross-file-refactor-04", "cross_file_refactor", TaskSplit.REGRESSION, "53571928af1a45670c34eaaab595028e2ae03d61", "79cace39e8dbcb85035fcc4fc406c0e818868ea08620259a3d770ebae3541281", "删除 SDK 专属对话和旧压缩路径，使 Agent、记忆协调器和 Core 集成只依赖规范运行时。", "python -m pytest -q tests/memory_runtime/test_core_integration.py", ("lion_code/agent.py", "lion_code/memory_runtime/coordinator.py", "tests/memory_runtime/test_core_integration.py"), 5),
    _task("lion-cross-file-refactor-05", "cross_file_refactor", TaskSplit.HOLDOUT, "563121ffcaa973106e513fa22bdfeefbcf7fc396", "6278a9e2141189a701628a4f9af1bd71892b974d379f01acbaf6f46cdae692f4", "收敛 Core Provider 单一路径，确保应用会话、Agent 和自动化路径不再保留平行 provider 状态。", "python -m pytest -q tests/integration/test_agent_core_runtime.py", ("lion_code/agent.py", "lion_code/application/session.py", "lion_code/autonomy.py"), 5),
    _task("lion-cross-file-refactor-06", "cross_file_refactor", TaskSplit.HOLDOUT, "e2bde092c0b422f9628fa93a320220e806063620", "3ce9150e45a15ecd358cc173ff0e0cf37626a828f780239f4b6cca5e8f951798", "将 side query 全面迁移到 Core Provider，统一 Dream、记忆查询和一次性 provider 的使用边界。", "python -m pytest -q tests/providers/test_oneshot.py", ("lion_code/agent.py", "lion_code/dream.py", "lion_code/providers/oneshot.py"), 4),
    _task("lion-cross-file-refactor-07", "cross_file_refactor", TaskSplit.HOLDOUT, "96d8cd18d0604d149ca260e9aaaf53bb25e92e9c", "07a29085048b6ca3d2896a142693cef852f00a6c864d72b67d4ee350dd0fbfc6", "重命名旧 TUI 模块，为新 TUI 腾出包名，同时保持命令行和遗留测试的兼容入口。", "python -m pytest -q tests/test_legacy_tui.py", ("lion_code/__main__.py", "lion_code/legacy_tui.py", "tests/test_legacy_tui.py"), 3),
    _task("lion-cross-file-refactor-08", "cross_file_refactor", TaskSplit.HOLDOUT, "886e78833aea32b92e2ffaf0ce126c6faab357af", "796ea0ff04e6d6b09ab85157a235469119ba745631291f535054c975386d6fb4", "把上下文管理基准迁移到 ContextManager，统一正式基准、数据集和断言的入口。", "python -m pytest -q tests/test_context_formal_benchmark.py", ("benchmarks/context_management/benchmark.py", "benchmarks/context_management/formal_benchmark.py", "tests/test_context_formal_benchmark.py"), 3),
    _task("lion-cross-file-refactor-09", "cross_file_refactor", TaskSplit.HOLDOUT, "f986aa74e7ab0a66583a8bc55913f6a3540a41b4", "58de6a669284b7f99df028c5d19d2041ec028a31fcbce7cd4c2e36455333e4ec", "引入供应商无关的上下文投影，使 Agent 和 ContextManager 共享模型限制、估算和策略类型。", "python -m pytest -q tests/context/test_projector.py", ("lion_code/agent.py", "lion_code/context/projector.py", "tests/context/test_projector.py"), 5),
    _task("lion-cross-file-refactor-10", "cross_file_refactor", TaskSplit.HOLDOUT, "f82b6710749fc1e530dc17c1c304ca42162ca386", "5f40b01799cef393f66030f9e03f64c3f246e437995838b41d956503f3ecbbab", "适配 Lion 工具运行时到 portable Core，同时保证 adapter 与集成工具循环的行为契约。", "python -m pytest -q tests/adapters/test_tool_adapter.py", ("lion_code/adapters/tool_adapter.py", "tests/adapters/test_tool_adapter.py", "tests/integration/test_core_tool_runtime.py"), 4),
    _task("lion-bugfix-01", "bugfix", TaskSplit.HOLDOUT, "70fe53710d6ad04fcca116842df8d9968f7f987b", "2f8e12c72b7038b3ae6dde07780a6bcc0b254fd1b53b930cf966a9d6b5ca97f6", "修复流式 TUI 输出在连续增量到达时的闪烁，同时保留现有渲染顺序。", "python -m pytest -q tests/tui/test_tui_app.py", ("lion_code/tui/app.py", "lion_code/tui/widgets.py", "tests/tui/test_tui_app.py"), 3),
    _task("lion-bugfix-02", "bugfix", TaskSplit.REGRESSION, "82b28d7d02e72bdee38f8205d5969cd9b1697ad4", "264f4a518788dcf52f899c051fd2fd4d226d0357b3482a51a0018e9622f2ca5b", "按实际渲染行裁剪补全窗口，避免长候选在 TUI 中越界或遮挡。", "python -m pytest -q tests/tui/test_tui_app.py", ("lion_code/tui/app.py", "tests/tui/test_tui_app.py"), 2),
    _task("lion-bugfix-03", "bugfix", TaskSplit.REGRESSION, "d3ee6f6252d2ba97646d2c098f0208edc56d763f", "0a8680a2530d8d275ea153eb7f8cff0ed1c55d8ed798abba0a9e16648ea4c365", "归一化 Windows 文件拖拽路径，使带引号、空格和反斜杠的路径能够可靠插入输入框。", "python -m pytest -q tests/tui/test_tui_file_drop.py", ("lion_code/tui/file_drop.py", "tests/tui/test_tui_file_drop.py"), 2),
    _task("lion-bugfix-04", "bugfix", TaskSplit.REGRESSION, "502cfd4071ed0efb46f57197de2192cc69113688", "b4f06a3c39a6a6a05095156f9f2170a214b873b13796d841a4d85e3e57783e13", "阻止取消信号已经生效后仍启动新的 Core 请求，保持取消语义和事件顺序。", "python -m pytest -q tests/integration/test_agent_core_runtime.py", ("lion_code/agent.py", "tests/integration/test_agent_core_runtime.py"), 3),
    _task("lion-bugfix-05", "bugfix", TaskSplit.REGRESSION, "2db28bb51247f1c51d3cf78c8f052fe033222751", "aca638e3623725fa3651468a888a74844e93fd99caa8e41c9be7c8db26733e37", "在热切换 provider 或模型后保留先前累计用量，避免成本和 token 指标回退。", "python -m pytest -q tests/integration/test_agent_core_runtime.py", ("lion_code/agent.py", "tests/integration/test_agent_core_runtime.py"), 3),
    _task("lion-bugfix-06", "bugfix", TaskSplit.REGRESSION, "41e8617ecffd934eb37b6ab53f388c3782edb1d1", "9a98d421217f5763f157b35f7399098139bcc6d3fccbab4383b952eb60dee920", "释放已替换的 Core Provider 连接，避免配置切换后保留不再使用的资源。", "python -m pytest -q tests/integration/test_agent_core_runtime.py", ("lion_code/agent.py", "lion_code/agent_runtime.py", "tests/integration/test_agent_core_runtime.py"), 3),
    _task("lion-bugfix-07", "bugfix", TaskSplit.REGRESSION, "74a91844ddde9fdf44a66a0620efc5395fe3ffe8", "92c724ab5c9beb15283540d11d92a90b3fbd69dc8025f7087befc9870f2ca2f0", "保留 Provider 的用户取消语义，不把取消转换成普通模型错误或额外重试。", "python -m pytest -q tests/providers/test_anthropic.py tests/providers/test_openai_compatible.py", ("lion_code/providers/anthropic.py", "lion_code/providers/openai_compatible.py", "lion_code/providers/stream.py"), 4),
    _task("lion-bugfix-08", "bugfix", TaskSplit.REGRESSION, "74ea3bc0f9674a2caedea90d3c7ca9949ba2721a", "dd68dee9d9e7cafdadb9e2841d22bb157caf42fc64ff37ec532173c7ac973b68", "将 Core 终态同步回 Agent，确保结构化结果、停止原因和前端观察器读取同一状态。", "python -m pytest -q tests/integration/test_agent_core_runtime.py", ("lion_code/agent.py", "tests/integration/test_agent_core_runtime.py"), 3),
    _task("lion-bugfix-09", "bugfix", TaskSplit.REGRESSION, "c65bf81a6a7ef8e1a0784414ded8dcfdaea4008b", "cb297625d6ad01ca5b3d45e960588a2cab893745d40c6a0a7424aa19cbcbc563", "当 TUI 正在处理模型请求时阻止新的命令分发，避免并发命令破坏会话状态。", "python -m pytest -q tests/tui/test_tui_app.py", ("lion_code/tui/app.py", "tests/tui/test_tui_app.py"), 2),
    _task("lion-bugfix-10", "bugfix", TaskSplit.REGRESSION, "87407595a8f75ceb26b76e91d5954a4ec03868c5", "b18cc7c2dbcb75d7b84b8fb56a8c67e6eb8e155485aa12179056b7fd303d7011", "模型热配完成后重绑应用会话 Runtime，防止后续命令仍指向旧 provider 或旧状态。", "python -m pytest -q tests/application/test_coding_session.py", ("lion_code/application/session.py", "tests/application/test_coding_session.py"), 3),
    _task("lion-feature-01", "feature", TaskSplit.REGRESSION, "ff85b953f3894fcc195297514acd267d0be23cf4", "f95945100c1054db8cd8ff32c6e502e01fbf61990ce779e8821a9a051073ffc2", "为上下文溢出加入受控压缩和一次自动重试链，并保持应用会话事件的可观察顺序。", "python -m pytest -q tests/application/test_coding_session.py", ("lion_code/agent.py", "lion_code/application/session.py", "tests/application/test_coding_session.py"), 5),
    _task("lion-feature-02", "feature", TaskSplit.REGRESSION, "223bbfb3257a2b4e1d4f5d8494b26d84a6c41ef8", "e8f5313da327002fb5db9a85b41d8a914d1672a9f9ba5e7ac4f59d5b2ae6ee0d", "将 TUI 终端通知接入 AgentSettled，使完成态通知只显示一次且不抢占流式输出。", "python -m pytest -q tests/tui/test_tui_app.py", ("lion_code/tui/app.py", "tests/tui/test_tui_app.py"), 2),
    _task("lion-feature-03", "feature", TaskSplit.REGRESSION, "ab36504cf53acbb1ccd3e53f49381d71c7284313", "de70f30a2c7b126b5cd76831d7f565c4efb06a8548485c96c4e34307ec5617e9", "把六档 thinking 配置接入 Core 路径，并让 Agent、应用命令、provider factory 和 TUI 使用同一配置。", "python -m pytest -q tests/providers/test_thinking.py", ("lion_code/agent.py", "lion_code/application/session.py", "lion_code/providers/thinking.py"), 5),
    _task("lion-feature-04", "feature", TaskSplit.REGRESSION, "26968194652ef3c19d9edc96141efe74525d0a34", "e353789c0536e5ee2c30199acf02032a4e97cc6d32fcec32324d30b2ae18ee95", "让子 Agent 复用 Core Runtime 和父级工具边界，同时保持子任务结果能够汇总回根 Agent。", "python -m pytest -q tests/integration/test_agent_core_runtime.py", ("lion_code/agent.py", "lion_code/tui/app.py", "tests/integration/test_agent_core_runtime.py"), 4),
    _task("lion-feature-05", "feature", TaskSplit.REGRESSION, "4c2ae4e700bcd5bc795af0e7ce6ea3df9ff69e9c", "bdfd72509fe4d4e1e332488767e177d9dd080907f8a065132b5011fafc5d66fe", "将 Anthropic 后端接入 Core Runtime，使命令行、Agent 与 TUI 的模型运行路径一致。", "python -m pytest -q tests/integration/test_agent_core_runtime.py", ("lion_code/__main__.py", "lion_code/agent.py", "lion_code/tui/app.py"), 4),
    _task("lion-feature-06", "feature", TaskSplit.HOLDOUT, "22a3840dbe92b532b4b55361813f9e2171d7f736", "44172d6ba977a2f39449b66d5882457e5d84a4246ed272132e5503739ce18508", "增加 `/resume` 会话选择器，展示可恢复会话并将选择结果安全地交给应用会话。", "python -m pytest -q tests/tui/test_tui_app.py", ("lion_code/application/commands.py", "lion_code/tui/app.py", "tests/tui/test_tui_app.py"), 3),
    _task("lion-feature-07", "feature", TaskSplit.HOLDOUT, "cc182a6c69b547ccb6f23901efe5ce32c1336e14", "3e4a5a14d00017f81ea0cbded628aba7f22391f28ad4e53e5b21da82a0f7a283", "增加 `/model` 选择器，统一 provider 设置、应用会话和 TUI 的模型切换体验。", "python -m pytest -q tests/application/test_provider_settings.py", ("lion_code/application/commands.py", "lion_code/application/provider_settings.py", "lion_code/tui/app.py"), 4),
    _task("lion-feature-08", "feature", TaskSplit.HOLDOUT, "73e758311f0d636cc3b40ae58c400272cbc1d845", "20bcb00ddeea10f01fa01ebc120ea8bce4b326fd8051f8ce825a7536aa4df3b2", "增加命令补全和主题选择列表，保证输入组件、应用会话和 TUI 焦点行为一致。", "python -m pytest -q tests/tui/test_tui_autocomplete.py", ("lion_code/application/session.py", "lion_code/tui/app.py", "lion_code/tui/prompt_input.py"), 3),
    _task("lion-feature-09", "feature", TaskSplit.HOLDOUT, "9a6eb03dfe8cbc58d9f918746ebf5299db44ad8f", "4590745df4239f4e2f692de1ddbf07b0871fcc9fd726d1cdbf8bda4dc6718b4e", "接入精简 TUI 主应用作为默认入口，并保持 CLI 和 TUI 入口的稳定启动契约。", "python -m pytest -q tests/tui/test_tui_app.py", ("lion_code/__main__.py", "lion_code/tui/__init__.py", "lion_code/tui/app.py"), 4),
    _task("lion-feature-10", "feature", TaskSplit.HOLDOUT, "6a3471124181844b66a69c80861a8441a85748a0", "250275d131744b308a1c791f8e742c71bc24307b47ae8c6f8839378d7f91cea5", "扩展 LionCodingSession 的属性面并落地默认命令注册表，使上层 TUI 能通过稳定接口驱动会话。", "python -m pytest -q tests/application/test_coding_session.py", ("lion_code/application/commands.py", "lion_code/application/session.py", "tests/application/test_coding_session.py"), 3),
)


_GOLD_REVISIONS: Mapping[str, str] = {
    "lion-cross-file-refactor-01": "46f9dfe60d20f0ad7a99aecd9a0521c6e24b6a05",
    "lion-cross-file-refactor-02": "3370351f2cfc4a30927e79a50f0ab9276880e6ef",
    "lion-cross-file-refactor-03": "1f95fb02ac9afc546b3b3f44705d86ce1607a43b",
    "lion-cross-file-refactor-04": "9e92d09f9619d3985a31bf54878c487e1a268d0c",
    "lion-cross-file-refactor-05": "64e25b6c21a5876866decf5a17799d9acf8d4447",
    "lion-cross-file-refactor-06": "517fde844aedc4c8fb0cae4199c093e39c4d48c3",
    "lion-cross-file-refactor-07": "0b3aa4d0b69b88243b18e31964b2039ce4795d66",
    "lion-cross-file-refactor-08": "43d0819ae64eaca71cad93aa87f982066ee8b7a4",
    "lion-cross-file-refactor-09": "047c1875c64c0788ddd73201c3fab2edd580eabb",
    "lion-cross-file-refactor-10": "44718f1338e0a7913042004f33f5021a365b8d19",
    "lion-bugfix-01": "f82959e2d9326965de6ff060e3cd08879eca3f8a",
    "lion-bugfix-02": "b29e9fe05d6a3c9c3751c8178d23badc241645f9",
    "lion-bugfix-03": "82b28d7d02e72bdee38f8205d5969cd9b1697ad4",
    "lion-bugfix-04": "ab36504cf53acbb1ccd3e53f49381d71c7284313",
    "lion-bugfix-05": "502cfd4071ed0efb46f57197de2192cc69113688",
    "lion-bugfix-06": "2db28bb51247f1c51d3cf78c8f052fe033222751",
    "lion-bugfix-07": "41e8617ecffd934eb37b6ab53f388c3782edb1d1",
    "lion-bugfix-08": "74a91844ddde9fdf44a66a0620efc5395fe3ffe8",
    "lion-bugfix-09": "74ea3bc0f9674a2caedea90d3c7ca9949ba2721a",
    "lion-bugfix-10": "c65bf81a6a7ef8e1a0784414ded8dcfdaea4008b",
    "lion-feature-01": "7224a0acaa53f5563e8aa3147e31d9d7e2681ac2",
    "lion-feature-02": "2c439109216d0cd80b208273ecca3157fa85d434",
    "lion-feature-03": "f5fcc06eca7211218c8faf9fafb6abe34af55142",
    "lion-feature-04": "30c788d8aee93e15a1824e5b1b372dba5726ef28",
    "lion-feature-05": "26968194652ef3c19d9edc96141efe74525d0a34",
    "lion-feature-06": "b41e64be9832e8337144941ac9d608e4298a237f",
    "lion-feature-07": "22a3840dbe92b532b4b55361813f9e2171d7f736",
    "lion-feature-08": "60c17e51624615577f6d8bc326e7f062f174829d",
    "lion-feature-09": "fbf00fcf27f18e088512314d37125f954f3bd5ec",
    "lion-feature-10": "9a6eb03dfe8cbc58d9f918746ebf5299db44ad8f",
}

_PRIVATE_EVIDENCE: Mapping[str, PrivateEvidence] = {
    task.task_id: PrivateEvidence(
        task_id=task.task_id,
        gold_revision=_GOLD_REVISIONS[task.task_id],
        gold_patch_sha256=task.gold_evidence_hash,
    )
    for task in _PUBLIC_TASKS
}
