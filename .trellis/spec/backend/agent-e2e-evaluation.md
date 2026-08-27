# Agent E2E Evaluation Boundaries

## 1. Scope / Trigger

Apply this contract when adding a coding-Agent evaluation task, changing an
evaluation manifest/result schema, wiring an Agent worker, or implementing a
container backend. It also applies when adding a historical-replay task card or
changing corpus admission evidence, or adding a SWE-bench-Live external anchor. The evaluation system is a separate orchestration boundary:
it reuses `Agent.run()` and typed Core events but must not create a second Agent
history, session writer, provider path, or stdout-log parser.

The current `benchmarks/agent_e2e/` foundation is deliberately offline-only.
It contains a backend protocol and test fakes, not a Docker scheduler or a real
provider invocation. A host process or a Git worktree alone is never an official
evaluation isolation boundary.

## 2. Signatures

```python
class Agent:
    def __init__(...) -> None: ...

async def run_agent_worker(
    request: AgentExecutionRequest,
    *,
    agent_factory: AgentFactory = Agent,
    trace_recorder: TraceRecorder | None = None,
) -> WorkerResult: ...

def validate_corpus(
    catalog: Catalog,
    evidence: Mapping[str, PrivateEvidence],
    *,
    feedback_task_ids: Iterable[str] = (),
) -> None: ...

def run_historical_preflight(
    task: TaskSpec,
    evidence: PrivateEvidence,
    *,
    repository_root: str | Path,
    repeats: int = 3,
) -> HistoricalPreflight: ...

def run_gold_preflight(
    manifest: ExternalAnchorManifest,
    *,
    runner: OfficialSWEbenchLiveRunner,
    output_root: str | Path,
    workers: int = 1,
) -> GoldPreflightReport: ...

def run_external_anchor_evaluation(
    manifest: ExternalAnchorManifest,
    *,
    runner: OfficialSWEbenchLiveRunner,
    prediction_path: str | Path,
    output_root: str | Path,
    workers: int = 1,
) -> ExternalAnchorReport: ...

def require_comparable_external_reports(
    baseline: ExternalAnchorReport,
    candidate: ExternalAnchorReport,
) -> None: ...

def calibrate_external_anchor(
    points: Iterable[CalibrationPoint],
) -> CalibrationReport: ...

def write_materialized_dataset_snapshot(
    manifest: ExternalAnchorManifest,
    rows: Iterable[Mapping[str, Any]],
    *,
    output_path: str | Path,
) -> Path: ...

def validate_materialized_dataset_snapshot(
    manifest: ExternalAnchorManifest,
    dataset_jsonl: str | Path,
) -> None: ...

def evaluate_regression_gate(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
    *,
    declared_changes: Iterable[ChangeKind],
    policy: RegressionGatePolicy | None = None,
    waiver_reason: str | None = None,
    calibration: CalibrationReport | None = None,
) -> RegressionGateDecision: ...

def classify_failure(
    task_result: TaskResult,
    trace_events: Sequence[TraceEvent],
    *,
    allowed_tool_names: Iterable[str] | None,
    reproduction_command: str,
    triage_owner: str | None = None,
) -> FailureRecord: ...

def admit_failure_to_regression(
    triage: FailureTriage,
    *,
    source_task: TaskSpec,
    feedback_task: TaskSpec,
    active_holdout_task_ids: Iterable[str],
    retired_holdout_task_ids: Iterable[str],
) -> FeedbackAdmission: ...

class ContainerBackend(Protocol):
    @property
    def available(self) -> bool: ...

    @property
    def supports_official_scores(self) -> bool: ...

    async def inspect_isolation(
        self,
        request: AgentExecutionRequest,
        *,
        verifier_workspace: Path,
    ) -> IsolationReport: ...

    async def run_agent(self, request: AgentExecutionRequest) -> WorkerResult: ...
    async def run_verifier(
        self, request: VerifierExecutionRequest
    ) -> VerifierResult: ...
    async def cleanup(self, *, run_id: str, task_id: str, attempt: int) -> None: ...
```

The CLI is `python -m benchmarks.agent_e2e`. `validate` validates a public
catalog/lock pair, `offline-run` writes blocked evidence, and `online-run`
returns exit code `2` with a JSON `blocked` status until a real backend exists.

## 3. Contracts

- Every persisted evaluation model carries `schema_version="agent-e2e/v1"`,
  rejects unknown top-level fields, and permits future additions only under its
  explicit `extensions` field. Credentials, session keys, cookies, and tokens
  are forbidden in `extensions`.
- Freeze tasks with `CatalogLock` before execution. `ExperimentManifest` must
  repeat the profile fingerprint, code SHA, seed, repeat count, timeout, and
  budget exactly; a selected task must belong to the lock.
- An evaluation worker must call `Agent.run()`, subscribe through
  `agent.core_runtime`, and construct `SessionRepository` under a path outside
  the Agent workspace.
- `IsolationReport.official_safe` requires workspaces that do not overlap in
  either direction and `private_assets_visible_to_agent=False`. Equal or nested
  Agent/verifier paths are unsafe because the Agent could read verifier files.
- Historical-replay tasks must give the Agent only the selected public card and
  a base-tree snapshot. Do not mount the evaluator repository, a full catalog,
  or a `.git` object database that contains the gold commit; a normal worktree
  from the source repository leaks future history even when verifier files are
  elsewhere.
- The V1 Lion historical corpus has exactly 30 active cards: ten
  `cross_file_refactor`, ten `bugfix`, and ten `feature`; its split is 18
  regression / 12 holdout. Public cards contain the base revision and gold patch
  SHA-256 only. `PrivateEvidence.gold_revision` and provenance details remain on
  the evaluator side and must agree with the public hash.
- The V2 corpus keeps the same 30-card / 10-10-10 / 18-12 contract. It retires
  cards whose referenced modules were deleted (Dream/Memory/Learning/MCP and
  legacy TUI, PR9/PR7b) instead of mutating their v1 SHA-pinned records in
  place; rewrites surviving cards to currently existing paths when the original
  test file was renamed; and backfills four `cross_file_refactor` cards from the
  real Git history (#48/#52/#55/#57) using single-commit base/gold pairs whose
  REG and HOLDOUT commit sets do not intersect. Since v2, `validate_active_resources_exist`
  rejects ACTIVE cards whose involved files or validation paths are missing from
  the current worktree; v1 assets stay frozen as historical records.
- Historical `base=fail` / `gold=pass` is provenance language: the base tree
  differs from the gold tree and the Git binary diff is clean, hash-matched, and
  stable for exactly three repeats. It is not a semantic hidden-test pass and
  cannot yield an official score.
- The V1 external anchor is a committed, Python-only `SWE-bench-Live/SWE-bench-Live`
  `verified` manifest at one dataset revision and one evaluator revision. It has exactly 20
  IDs: five per `difficulty.files` stratum (1, 2, 3--4, 5+) and no repeated repository.
  The Agent never receives its gold patch, test patch, full dataset, evaluator checkout, or
  output directory.
- Official SWE-bench-Live scoring starts with exactly three official `gold` evaluator runs
  per frozen instance. An instance enters this machine's denominator only when all three
  records are completed and `resolved=true`. A gold failure, missing report, image failure,
  or runner error is excluded/invalid infrastructure evidence, never a model failure.
- `SubprocessOfficialSWEbenchLiveRunner` must call the frozen official entrypoint on Linux
  with only frozen IDs and a host-controlled result directory. Because the official evaluator has
  no dataset-revision argument, it must receive a host-materialized local JSONL of exactly the
  frozen 20 full rows. Its canonical selected-row SHA-256 must match the manifest before every
  run; passing the mutable Hugging Face dataset name directly is forbidden. `UnavailableOfficialSWEbenchLiveRunner`
  and test fakes may prove lifecycle behavior only; they cannot create an external score.
- A completed external report has an `ExternalAnchorEnvironment` containing the manifest,
  dataset revision/file SHA, evaluator revision, platform, and a resolved image digest for
  every denominator instance. If any digest is unavailable, the report is invalid and has no
  `success_rate`.
- Compare external success rates only after exact environment-fingerprint equality. Calibration
  requires at least five unique frozen profiles: one baseline, at least three candidates, and
  one deliberately degraded profile; it accepts external validity only at Spearman rho >= .70
  and pairwise direction agreement >= 80%.
- `evaluate_regression_gate` compares only two complete official reports with the same frozen
  catalog ID/version/SHA/task IDs, seed, repeats, timeout, budget, platform, agent/verifier
  image digests, evaluator code, resume state, and resource-related extensions. Model, provider,
  thinking, permission, maximum turns, credential-variable names, and profile extensions must
  also be equal. The only permitted profile differences are explicitly declared prompt,
  compression, and tool-policy version changes; corresponding Agent code may change with them.
- The V1 gate rejects a drop greater than 10 percentage points and unconditionally rejects a
  three-task `3/3 -> 0/3` catastrophe. A waiver requires an explicit reason after comparability
  succeeds. Only `reject && !merged` contributes to `RegressionGateLedger.intercepted_count`.
  Missing tasks, unequal denominators, blocked/offline/invalid reports, or non-official results
  are `invalid`, not a score delta.
- A passed gate is `self_only` until an accepted external calibration both satisfies the five-profile
  threshold and covers the baseline and candidate profile fingerprints. It may then be labelled
  `external_calibrated`; no calibration or a non-covering calibration cannot support a
  generalization claim.
- `classify_failure` consumes only redacted `TraceEvent` metadata and emits candidate labels plus
  event sequence offsets. Three consecutive identical tool/argument/workspace fingerprints are
  `loop`; typed context/compaction signals are `context_decay`; a disallowed tool or typed
  tool/permission error is `tool_misuse`; max-turn/cost, abort/cancel, or timeout signals are
  `premature_termination`. A blocked, invalid, or offline result is `infrastructure` and has
  precedence over Agent-behaviour labels.
- Candidate labels are not final attribution. A feedback task can enter the next catalog only after
  `FailureTriage` records reproduction and Agent responsibility, the failure is not deduplicated,
  and the new task has a distinct active `regression` ID. If the source is holdout, it must be put
  in the retired-holdout list and be absent from the next active holdout list. Do not mutate the
  V1 historical corpus in place.
- `TaskVerdict.PASSED` and `FAILED` require `official=True`, `validity=VALID`,
  a patch SHA, and a verifier outcome that agrees with the verdict. Only a
  backend with `supports_official_scores=True` may produce them.
- `FakeContainerBackend`, `UnavailableContainerBackend`, and host fallback can
  produce lifecycle evidence only. They must return `blocked`, `offline_only`,
  or `invalid`, never an official score. Do not store raw session text, tool
  output, or credentials in trace/report artifacts; retain controlled metadata
  and digests instead.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Unknown top-level schema field or incompatible version | Pydantic validation error or `SchemaVersionError`; do not coerce it |
| Catalog ID/hash/task selection mismatch | `CatalogValidationError`; do not run the task |
| Corpus has wrong family/split count, missing/private hash mismatch, or unstable evidence | `CorpusAdmissionError`; reject admission |
| Feedback-derived task is in holdout, or base/gold commit occurs across splits | `CorpusAdmissionError`; preserve the original holdout boundary |
| Historical commit is unavailable or its recomputed patch hash differs | `CorpusAdmissionError`; report blocked provenance rather than inventing gold evidence |
| External manifest has not exactly 20 unique IDs, five per stratum, or unique repositories | `ExternalAnchorError`; reject before evaluator execution |
| Docker daemon or frozen official evaluator checkout unavailable | external `blocked` report and blocked `TaskResult`s; no external success rate |
| Local materialized JSONL is absent, not exactly 20 frozen IDs, or its canonical full-row SHA differs | `ExternalAnchorDriftError`; do not invoke the official evaluator against a mutable dataset name |
| A gold preflight record is false, incomplete, missing, or errors | exclude that instance from the actual denominator; do not call it a model failure |
| Official model evaluator omits a stable ID, lacks a boolean `resolved`, or cannot resolve its image digest | external `invalid` report; no external success rate |
| Dataset revision/file, evaluator revision, platform, selected IDs, or image digest differs | `ExternalAnchorDriftError`; reject baseline comparison/calibration |
| Fewer than five calibration profiles, no degraded profile, or constant rank vector | `ExternalAnchorError` or non-accepted calibration; do not claim external validity |
| Gate catalog/profile/resource invariants, frozen task/repeat coverage, or official denominators differ | `GateStatus.INVALID`; do not compute delta or count an interception |
| Candidate falls below the V1 non-inferiority bound or changes `3/3` to `0/3` | `GateStatus.REJECT`; add one ledger interception only if it remains unmerged |
| Candidate is comparable but needs an approved exception | `GateStatus.WAIVED` with a non-empty waiver reason |
| Trace has a loop/context/tool/premature candidate | `FailureRecord` with only redacted metadata, stable signature, and evidence offsets; require human triage |
| Blocked, invalid, or offline task is classified | `FailureMode.INFRASTRUCTURE`; do not attribute it to the Agent |
| A reproduced Agent failure originated from holdout | retire the source ID before admitting a distinct regression feedback task |
| Docker/backend unavailable | `TaskResult(verdict=blocked, validity=blocked, official=False)` |
| Fake backend completes worker/verifier lifecycle | `TaskResult(verdict=blocked, validity=offline_only, official=False)` |
| Agent/verifier workspaces overlap or private assets are visible | `TaskResult(verdict=invalid, validity=invalid, official=False)` before worker execution |
| Worker timeout/error, verifier error, or cleanup failure | `TaskResult(verdict=invalid, validity=invalid, official=False)` and one cleanup attempt |
| Checkpoint exists for same run/task/attempt | Return the recorded result with `resumed_from_checkpoint=True`; do not rerun backend |

## 5. Good / Base / Bad Cases

- Good: a real backend mounts an Agent worktree and a separate verifier worktree,
  sends only the patch digest across the boundary, and marks a verified pass as
  official.
- Base: the current offline command validates a frozen manifest and emits one
  blocked report without reading credentials, starting Docker, or claiming a
  success rate.
- Good: the historical corpus sends one task's public card to an isolated base
  snapshot, while `PrivateEvidence` checks its gold revision on the evaluator
  host.
- Base: a three-run Git provenance check proves a patch source is reproducible,
  then records `fail/pass` only as provenance evidence.
- Bad: treating two paths as isolated merely because their strings differ. A
  verifier directory inside the Agent workspace is still visible to the Agent.
- Bad: using a host worktree plus `bypassPermissions` as an official run; the
  Agent can access paths outside the worktree and the verifier assets are not
  protected by a container boundary.
- Bad: copying the full historical catalog or `.git` object store into the
  Agent workspace; an adjacent task's public base can reveal another task's
  gold commit.
- Good: the host runs `gold` three times through the official SWE-bench-Live evaluator,
  drops one unstable instance from the denominator, and reports `passed / stable_count` only
  after every remaining official report has an image digest.
- Bad: treating a Docker-less fake result as an external failure/pass rate, keeping the raw
  prediction patch in a report, or comparing results after the evaluator image changed.
- Good: a declared prompt-version candidate replays every frozen task and repeat under the same
  evaluator, resources, images, model, and permissions; its complete official score stays within
  the non-inferiority boundary before merge.
- Bad: changing the model or task selection while claiming a prompt-only gate pass, or writing a
  delta from blocked/offline results. Both are `invalid`, not successful experimentation.
- Good: a repeated `read_file` call with identical argument and workspace digests is classified as
  a loop candidate, then a reviewer reproduces it and records Agent responsibility before adding
  a new regression task.
- Bad: copying a holdout failure into regression while leaving the source task active in holdout,
  or automatically treating a timeout/invalid verifier as an Agent failure.

## 6. Tests Required

- `tests/benchmarks/test_models_catalog.py`: version round-trip, unknown fields,
  catalog/lock mismatches, and official verdict/score consistency.
- `tests/benchmarks/test_orchestrator.py`: unavailable/fake backend, worker and
  verifier errors, cleanup, checkpoint resume, equal/nested workspace rejection.
- `tests/benchmarks/test_agent_worker.py`: real `Agent` worker captures Core
  output and keeps the JSONL session outside the task workspace.
- `tests/benchmarks/test_trace.py`: secret/path/session/prompt redaction and loop
  fingerprint evidence.
- `tests/benchmarks/test_evaluation_cli.py`: the online command remains explicitly blocked
  and never emits `task_resolved`.
- `tests/benchmarks/test_corpus.py`: thirty-card quotas, public/private asset
  correspondence, feedback/holdout and commit-chain rejection, plus three-run
  provenance evidence for every bundled task.
- `tests/benchmarks/test_external_anchor.py`: frozen 20-card stratification and fingerprint,
  offline blocked behavior, three-run gold denominator, official result normalization,
  missing image invalidation, prediction-ID boundary, artifact redaction, environment drift,
  and five-profile calibration thresholds.
- `tests/benchmarks/test_regression_feedback.py`: pass/reject/invalid/waived decisions,
  deliberate `3/3 -> 0/3` ledger interception, self-only scope, four trace failure rules,
  infrastructure priority, signature deduplication, and reviewed holdout-to-regression retirement.
- Before handoff run focused evaluation tests, `python -m pytest -q`,
  `python -m compileall -q lion_code benchmarks tests`, and `git diff --check`.

## 7. Wrong vs Correct

### Wrong

```python
# A Git worktree is not a security boundary.
backend = HostShellBackend(worktree=agent_workspace)
result = TaskResult(
    verdict=TaskVerdict.PASSED,
    validity=ResultValidity.VALID,
    official=True,
)
```

### Correct

```python
isolation = await backend.inspect_isolation(
    request,
    verifier_workspace=verifier_workspace,
)
if not isolation.official_safe:
    return invalid_result("Agent/verifier isolation contract failed")

worker = await backend.run_agent(request)
verifier = await backend.run_verifier(verifier_request)
# Only a real container backend with supports_official_scores=True may write
# passed/failed after the verifier outcome is available.
```

### Wrong

```python
# This publishes an implementation clue and treats provenance as a score.
agent_workspace = source_repository_worktree
report.official_score = score_from_historical_patch_hashes()
```

### Correct

```python
public_card = select_one_public_task(task_id)
base_snapshot = export_base_tree(public_card.base_revision)
provenance = run_historical_preflight(public_card, private_evidence, repo_root)
assert provenance.stable
# Keep the report offline until an isolated semantic verifier runs.
```

### Wrong

```python
# A current Hugging Face row order and a Docker tag are not a frozen external baseline.
external_rate = fake_runner.score(live_dataset.sample(20))
```

### Correct

```python
gold = run_gold_preflight(manifest, runner=official_runner, output_root=host_results)
assert gold.status is AnchorRunStatus.COMPLETED
report = run_external_anchor_evaluation(
    manifest,
    runner=official_runner,
    prediction_path=prediction_json,
    output_root=host_results,
)
if report.status is AnchorRunStatus.COMPLETED:
    require_comparable_external_reports(baseline, report)
```

### Wrong

```python
# Offline evidence is not an eligible gate score, and this silently leaks a holdout sample.
candidate_rate = blocked_report.extensions["estimated_rate"]
next_catalog.tasks += [holdout_failure_as_regression]
```

### Correct

```python
decision = evaluate_regression_gate(
    baseline_report,
    candidate_report,
    declared_changes=(ChangeKind.PROMPT,),
)
if decision.gate.status is GateStatus.REJECT:
    ledger = ledger.record(decision)

admission = admit_failure_to_regression(
    triage,
    source_task=holdout_task,
    feedback_task=next_catalog_regression_task,
    active_holdout_task_ids=active_holdouts,
    retired_holdout_task_ids=(holdout_task.task_id,),
)
assert holdout_task.task_id not in admission.active_holdout_task_ids_after_feedback
```

## 8. Verified SWE-bench Execution Chain

### 1. Scope / Trigger

This contract applies to the single-task `verified-run` path that turns one
selected Git commit into a Harbor routine trial and then rechecks the exact
exported patch with the official SWE-bench Harness. It is an integration
boundary: the benchmark runner may orchestrate existing Lion worker behavior,
but it must not implement a second Agent execution loop or verifier.

### 2. Signatures

```python
class CommitArtifactBuilder:
    def build(self, commit_sha: str, output_dir: str | Path) -> CommitArtifact: ...

class HarborSingleTaskRunner:
    def run(self, request: HarborExecutionRequest) -> HarborExecutionOutput: ...

class OfficialSWEbenchHarnessRunner:
    def run(self, request: HarnessExecutionRequest) -> HarnessExecutionOutput: ...

def run_verified_evaluation(
    request: VerifiedExecutionRequest,
) -> VerifiedExecutionOutput: ...
```

The CLI entrypoint is `python -m benchmarks.agent_e2e verified-run`. It accepts
one catalog-selected task and one commit, and writes `verified-report.json`
and `verified-report.md` under the caller-provided output directory.

### 3. Contracts

- The execution order is exactly `CommitArtifactBuilder -> HarborSingleTaskRunner -> OfficialSWEbenchHarnessRunner`.
- `CommitArtifactBuilder` reads a resolved Git commit through `git archive`; a
  dirty host worktree, host `.git` directory, and untracked files are not part
  of the artifact. The wheel digest and Git tree SHA are persisted as
  provenance, and repeated builds of the same commit are byte-stable.
- Harbor is pinned to `0.22.0`, uses dataset `swebench-verified`, exactly one
  task/attempt/concurrent worker, and the fixed import path
  `benchmarks.agent_e2e.harbor_agent:LionInstalledAgent`.
- The installed agent uploads only the wheel, the allowlisted worker source,
  and the request; it invokes the existing `run_agent_worker` entrypoint. The
  manifest carries credential variable names, never credential values. Values
  are not placed in argv, JSON reports, traces, or exception summaries.
- The official recheck is SWE-bench `5.0.1`, dataset
  `SWE-bench/SWE-bench_Verified`, split `test`, and module
  `swebench.harness.run_evaluation`. It receives the exact UTF-8 patch bytes
  exported by Harbor and verifies their SHA-256 before writing prediction
  JSONL.
- Harbor reward is routine evidence only. A `PASSED`/`FAILED` official result
  may be produced only after the official Harness result is completed and the
  backend declares `supports_official_scores=True`.
- Raw Harbor/Harness job roots are deleted on success, timeout, ordinary
  errors, and unexpected failures. A cleanup failure is an invalid,
  non-official result and must not be silently ignored. Only controlled
  digests, patch, worker, trace, and final report artifacts remain.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Selected task is absent from the manifest or repeats is not `1` | Reject before backend execution; no official result |
| Commit cannot be resolved, wheel build fails, or artifact commit differs from `agent_code_sha` | `blocked` or `invalid` non-official report |
| Platform is not Linux, Harbor is unavailable/not `0.22.0`, or Docker daemon is unavailable | Harbor `unavailable`/`blocked`; do not invoke official Harness |
| Dataset, agent import path, task name, run ID, or model path contains an unsupported value | Invalid schema/path result; do not create an evaluator run |
| Required provider credential variable is missing | Harbor unavailable; do not expose the missing value in the result |
| Harbor has no controlled patch or patch digest | Blocked/non-official result; do not invoke official Harness |
| SWE-bench package is not `5.0.1`, image digest is absent, or Docker is unavailable | Harness unavailable/invalid; no official score |
| Harness report is missing, malformed, or lacks boolean `resolved` | Invalid/non-official result |
| Any raw-job cleanup fails | Invalid result with `failure_source=CLEANUP`; retain no claim of completion |

### 5. Good / Base / Bad Cases

- Good: build a wheel from the selected commit, run one isolated Harbor
  installed-agent trial, copy only its patch and controlled metadata, and pass
  that patch unchanged to the pinned official Harness.
- Base: on Windows or without credentials/Docker, stop at an explicit blocked
  report with fixed dependency provenance; this is lifecycle evidence, not an
  evaluation score.
- Bad: build from the current dirty worktree, pass a host absolute path or
  secret in Harbor argv, or treat Harbor's reward as SWE-bench `resolved`.
- Bad: run the Harness against a newly generated patch, a mutable dataset
  default, or a leftover raw job directory; those results are not comparable
  official evidence.

### 6. Tests Required

- `tests/benchmarks/test_verified_execution_chain.py`: stable Git artifact
  digest, dirty/untracked-file exclusion, patch export redaction, fixed Harbor
  argv, raw-result normalization, prediction-byte verification, cleanup,
  path validation, and the artifact-before-backend ordering.
- Existing worker/contract/CLI tests must continue to pass, including the
  assertion that `online-run` remains blocked and no fake backend can produce
  an official verdict.
- On a Linux Docker host, run one real `verified-run` smoke with Harbor
  `0.22.0` and SWE-bench `5.0.1`; assert that the Harbor-exported patch SHA,
  Harness prediction patch SHA, report revisions, image digest, and final
  cleanup state agree.
- Before handoff run targeted evaluation tests, full pytest, compileall, the
  repository quality gates, and `git diff --check`; record unrelated baseline
  failures separately from this chain.

### 7. Wrong vs Correct

#### Wrong

```python
# Harbor reward is not the official SWE-bench verifier result.
result = TaskResult(verdict=TaskVerdict.PASSED, official=True)
```

#### Correct

```python
harbor = HarborSingleTaskRunner().run(harbor_request)
if harbor.patch_path is None:
    return blocked_nonofficial_result(harbor.result)

harness = OfficialSWEbenchHarnessRunner().run(
    HarnessExecutionRequest(
        instance_id=instance_id,
        patch_path=harbor.patch_path,
        patch_sha256=harbor.result.patch_sha256,
        model_name=manifest.profile.model,
        run_id=manifest.run_id,
        output_dir=output_dir,
        timeout_seconds=manifest.timeout_seconds,
        image_digest=manifest.verifier_image_digest,
    )
)
return harness_result_to_task_result(
    harness.result,
    manifest=manifest,
    attempt=1,
    supports_official_scores=True,
)
```
