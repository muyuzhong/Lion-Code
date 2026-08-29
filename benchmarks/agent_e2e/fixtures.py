"""verified-task-1 共享测试基线，避免 benchmarks 各测试文件的 TaskSpec/SHA 漂移。"""

from __future__ import annotations

from benchmarks.agent_e2e.models import TaskSpec, TaskSplit

PUBLIC_PROMPT = "修复公开问题。"
AGENT_CODE_SHA = "abcdef0"
EVALUATOR_CODE_SHA = "1234567"


def make_task(
    *,
    task_id: str = "verified-task-1",
    split: TaskSplit = TaskSplit.REGRESSION,
    verifier_identity: str = "verified/v1",
    difficulty: int = 1,
    extensions: dict[str, object] | None = None,
    public_setup: tuple[str, ...] = (),
    public_validation_commands: tuple[str, ...] = (),
    involved_files: tuple[str, ...] = (),
) -> TaskSpec:
    """构造 verified-task-1 基线任务卡；调用方只覆盖语义差异字段。"""

    return TaskSpec(
        task_id=task_id,
        family="bugfix",
        split=split,
        repository="lion",
        base_revision=AGENT_CODE_SHA,
        public_prompt=PUBLIC_PROMPT,
        public_setup=public_setup,
        public_validation_commands=public_validation_commands,
        verifier_identity=verifier_identity,
        gold_evidence_hash="a" * 64,
        difficulty=difficulty,
        involved_files=involved_files,
        extensions=dict(extensions or {}),
    )
