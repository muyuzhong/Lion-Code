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
- `PairedExperiment.build` pairs two complete official reports on `(task_id, attempt)` — the
  attempt is the seed dimension under the manifest-level seed/repeats contract, no per-task seed
  mechanism. Comparability before pairing reuses the gate's invariant fields sets: distinct run
  IDs, identical catalog locks, identical manifest/profile invariants, and the actual profile
  variation differences must equal the declared `ChangeKind` set. A broken pair, missing task,
  or non-official result is an `invalid` trial, never a half-built pairing. `PairedTrialOutcome`
  is the five-cell fail→pass / pass→fail / pass→pass / fail→fail / invalid mapping; statistical
  significance (bootstrap / McNemar) is a later layer, not part of the report.
- `HarnessVariant` is the first-class changeable surface of a Harness configuration: prompt,
  compression, and tool-policy versions only. Model, provider, seed, budget, and environment
  invariants are deliberately outside its surface; `from_profile` extracts exactly the three
  changeable fields.
- `ProcessEvidenceProjector` runs inside `TraceRecorder.record`, before sanitization, and emits a
  separate `evidence` array alongside `events` in `harbor-trace.json`; `TraceEvent` schema is
  untouched. Evidence carries only facts plus digests: `tool_call_id`, `tool_phase`,
  `tool_fingerprint` (taken from the argument-carrying start/update phase), `is_error` (from
  `tool_execution_end`), `target_scope` (source / test / verifier / other classified before path
  hashing), `validation_command` booleans matched against the task card's commands before
  hashing, compaction, and termination markers. Full commands, raw paths, and tool outputs are
  never persisted.
- `ProcessVerifier` runs deterministically on every trace, including passed ones, and consumes
  `ProcessEvidence`; it is a separate judging layer that never changes `TaskResult.verdict` and
  does not call `classify_failure`. `ProcessVerification.status` aggregates to `critical_veto`
  when any violation is critical (validation missing / test tampering), else `violation` when any
  rule fires, else `valid`. Traces without evidence (legacy format) degrade explicitly to
  `evidence_unavailable` instead of guessing from redacted text. Rules: `repeated_tool_call`
  (call-level fingerprints, start/update/end lifecycle never counts as repetition),
  `tool_error_not_recovered` (only `is_error=true` end evidence), `validation_missing` (only
  `PASSED` results with non-empty validation commands), `test_tampering` (write tools touching
  test/verifier scope), `premature_termination`, and `context_regression` (first tool call after
  a compaction repeating a pre-compaction failed fingerprint). Thresholds and tool lists are
  constructor parameters. The committed calibration fixtures
  (`tests/benchmarks/fixtures/agent_e2e/calibration/`) pin recall (violations detected) and
  precision (clean traces never vetoed).
- `PairedExperiment` distinguishes three experiment kinds. `CONTROLLED` requires equal
  `agent_code_sha` between baseline and candidate **and verified treatment at run
  granularity**: each side must validate as a single consistent `RunInjectionEvidence`
  (every `task × attempt` carries `InjectionEvidence` whose `requested` matches the
  manifest profile and whose `resolved_variant`/fingerprint are identical across the
  run — one missing or divergent result invalidates the whole run), and **every declared
  `ChangeKind`** must be hit on both sides with different injected content (per-dimension
  `prompt_sha256` / `tool_policy_sha256`). A declared `PROMPT` change is not verified by a
  `tool_policy` hit; the evidence must prove the declared treatment, not merely that some
  injection happened. Its paired deltas may be attributed to the declared mechanism.
  `REGRESSION` allows different agent code and only supports "this version regressed as a
  whole" claims. `UNSUPPORTED_TREATMENT` covers same-code pairs where the variable has no
  runtime switch (e.g. `compression_version`), injection did not resolve (missing maps,
  identical fingerprints, no evidence), or run-level evidence is inconsistent: the report
  must state the delta is not attributable to that mechanism. `compression_version` remains
  a declared field with no runtime switch and must never produce `CONTROLLED`; this
  limitation is recorded in the profile, not hidden.
- `VariantInjectionSpec` travels with the `ExperimentManifest` (its `extensions`
  `variant_injection_spec` key is part of the frozen manifest) from host to the Harbor
  installed-agent, so `worker_entrypoint` resolves and applies the same mapping table on the
  container side. The manifest is the **single source of truth** for the spec:
  `HarborExecutionRequest` does not carry a separate `injection_spec` (no dual source);
  `request_variant=True` only asserts that the manifest carries one. A
  `ToolPolicyVariantMap` must name at least one tool (`tool_names` is non-empty), so a hit
  always means a real registry filter — empty whitelists that claim a hit without injecting
  are rejected at construction. `harbor_agent._SOURCE_FILES` must include every module the
  worker chain imports (`evidence.py`, `variant_injection.py`).
- `ControlledExperimentRunner` is the formal host entry that creates a controlled
  experiment: one shared `VariantInjectionSpec` plus a frozen template and two profiles
  (`build_manifests`) produce the two frozen manifests, and `run_pair` executes both runs
  by reusing the **Verified official chain** (`run_verified_evaluation`: artifact → Harbor
  → SWE-bench Harness), looping every `task × attempt` and handing the assembled reports to
  `PairedExperiment.build`. It does not depend on the foundation
  `SingleTaskOrchestrator`/`ContainerBackend`; there is a single official execution chain.
  The Verified chain forwards `WorkerResult.injection_evidence` into
  `TaskResult.extensions["injection_evidence"]` (via `_merge_worker_result`) and sets
  `request_variant=True` on the Harbor request whenever the manifest carries
  `variant_injection_spec`, so real Harbor runs surface the evidence and the variant
  declaration that `PairedExperiment` consumes. `run_pair` validates the **execution
  context invariant** before running: `commit_sha`, `repository_root`,
  `python_executable`, `harness_python`, and `harbor_executable` must be identical
  between baseline and candidate (manifest comparability alone only constrains the
  declared surface, and `agent_code_sha` is a 7-char prefix match — drifting host inputs
  would otherwise mask fake causality behind identical code + valid evidence). `run_pair`
  derives declared changes from the actual profile version differences, so a run that
  does not change any gate-controlled version fails before execution.
- `comparison.py` turns a `PairedExperimentReport` into a publishable conclusion.
  `OutcomeComparison` consumes the four-grid: `net_improvement = fail→pass − pass→fail`,
  `delta_success_rate = net / valid_pairs`, a McNemar **exact** two-sided p-value on the
  discordant cells, and a deterministic-seed paired-bootstrap percentile CI for the delta.
  The signal is **asymmetric**: regression is caught sensitively by a deterministic
  catastrophe rule (winning discordant cell ≥ `min_discordant` and margin ≥
  `min_discordant`, e.g. `pass→fail=6, fail→pass=1` → REGRESSED) or McNemar `p < alpha`;
  improvement requires **statistical evidence only** — McNemar `p < alpha` with `fail→pass`
  dominating (the bootstrap CI is reported as effect size, never a standalone IMPROVED
  trigger, so tiny samples like `fail→pass=4, pass→fail=0` stay a positive-signal NEUTRAL
  instead of claiming IMPROVED). `p` is never the sole gate criterion for regression
  because small samples make it meaningless.
  `ProcessComparison` consumes `#144`'s `ProcessVerification` supplied by the caller as
  `(task_id, attempt)` maps (the execution chain does **not** persist it on `TaskResult`;
  comparison does not extend the chain). Severity order VALID < VIOLATION < CRITICAL_VETO;
  `EVIDENCE_UNAVAILABLE` or a missing pair is not comparable. It records new critical
  vetoes / new violations / resolved violations per pair. `EfficiencyComparison` only
  observes mean turns/tokens/cost/wall-time (`AgentRunSummary`; there is no tool-call count
  on `TaskResult` in V1) and raises a guardrail only when outcome and process are not
  degraded: cost ≥ +35% / wall-time ≥ +40% default to WARN, huge thresholds (default
  +200~300%) to BLOCKED. It never claims "fewer tool calls = better".
- `gate.py` applies the fixed `GateV2` priority to a `ComparisonResult`:
  (1) `UNSUPPORTED_TREATMENT` → BLOCKED (not attributable); (2) any new critical process
  veto → BLOCKED; (3) clear outcome regression → REGRESSED; (4) process-not-degraded with
  an efficiency BLOCKED guardrail → BLOCKED (an efficiency catastrophe must not be
  bypassed by outcome improvement); (5) outcome IMPROVED **and process fully comparable**
  (gated, `unavailable == 0`, no regressed pair) → IMPROVED — process missing or partially
  unavailable downgrades to NEUTRAL, because "no degradation observed" is not "not
  tested"; (6) otherwise NEUTRAL, with efficiency WARN recorded but never changing the
  decision. Outcome IMPROVED with process regression → NEUTRAL (fails the "process not
  degraded" precondition). The decision is `GateDecision` ∈
  {IMPROVED, NEUTRAL, REGRESSED, BLOCKED}, wrapped with reasons in `GateV2Result`.
- `first_error.attribute_first_error` locates the first causally meaningful deviation on a
  pair of trajectories (baseline/candidate `ProcessEvidence[]`). It aggregates evidence
  into **call-level** records (fingerprint taken from the first argument-carrying
  start/update phase), aligns by `(tool_name, fingerprint)` common prefix to find the first
  divergence, then promotes it to a first error only when candidate-side failure evidence
  exists. It reuses `ProcessVerifier` on the candidate evidence and picks the strongest
  violation by a fixed priority: critical veto (test tampering) → `PROCESS_VIOLATION`,
  unrecovered tool error → `ERROR_RECOVERY`, validation missing → `VALIDATION`, compaction
  regression → `CONTEXT`, premature termination → `TERMINATION`, behavior divergence →
  `TOOL_SELECTION`/`TOOL_ARGUMENT`/`UNKNOWN`. Confidence is 1.0 for a candidate-only
  violation (0.7 if baseline has the same kind), and a bare divergence without any
  violation only yields a low-confidence candidate (0.6) when baseline PASSES while the
  candidate FAILS — a PASS→PASS divergence is a different implementation path, **not** a
  first error, and returns `None` so harmless tool-selection differences never pollute the
  regression corpus. Evidence aggregation sorts by `sequence`
  before building calls (order-independent), and empty evidence on either side (legacy /
  unavailable trace) returns an explicit `evidence_available=False` attribution with
  confidence 0 instead of fabricating an insertion/deletion divergence. The output carries
  a short redacted causal snippet (`baseline_events`/`candidate_events`; sequence + tool +
  phase + fp-prefix + error/validation/termination markers only — no paths or command
  text, and tool-bearing validation events keep their `validation` marker) that the next
  `regression_probe` layer can minimize.
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
## 9. Offline DeepEval Analysis and Opik Post-Processing

### 1. Scope / Trigger

This contract applies when a completed Verified report is analyzed after the
Agent run. It is a benchmark-only integration boundary: analysis and
observability consume existing redacted evidence and never become a second
execution or scoring path.

### 2. Signatures

```python
def analyze_deepeval_case(
    case: DeepEvalCase,
    *,
    judge_model: str,
    judge: DeepEvalJudge | None = None,
    timeout_seconds: float | None = 120.0,
) -> DeepEvalAnalysis: ...

def analyze_verified_report(
    report: VerifiedEvaluationReport,
    *,
    input_digest: str,
    trajectory: DeepEvalTrajectory,
    judge_model: str,
    judge: DeepEvalJudge | None = None,
    timeout_seconds: float | None = 120.0,
) -> VerifiedEvaluationReport: ...

def build_opik_trace_payload(...) -> OpikTracePayload: ...

def publish_opik_trace(
    payload: OpikTracePayload,
    *,
    client: object | None = None,
    timeout_seconds: float = 30.0,
    export_attempt: int = 1,
) -> OpikExportResult: ...
```

### 3. Contracts

- DeepEval always evaluates the fixed metrics `TaskCompletionMetric`,
  `StepEfficiencyMetric`, and `TrajectoryQuality`; the SDK is optional and
  pinned in the `benchmark-online` extra, never imported by `lion_code`.
- The project analyzer and the optional standard pytest entry both consume the
  same `DeepEvalCase` built from one bounded, redacted trajectory. They must
  not call the Agent, generate a new dataset, or use hidden reasoning,
  credentials, raw tool output, or private verifier data.
- Each metric observation carries the same input digest as the case. A score
  is persisted only when it is finite and in `[0, 1]`; a single failure or
  timeout is typed and does not discard successful sibling metrics.
- `analyze_verified_report` may update only the `deepeval` field. The existing
  `task_result` and its official Harness verdict remain unchanged.
- Opik payloads contain a parent agent span, redacted event spans with stable
  timestamps/digests, and feedback for completed DeepEval metrics plus the
  Harness verdict. `PASSED`/`FAILED` feedback is emitted only for an official,
  valid result; blocked/offline results remain metadata/reason only.
- Opik credentials are read only by the host publisher from environment
  variables. The publisher explicitly flushes the short-lived client, and a
  retry reuses the existing payload without rerunning Agent or DeepEval.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Trajectory/report task IDs or analysis digest do not match | Reject before analysis/export; preserve the original report |
| DeepEval SDK is absent or its pinned API is incompatible | `DeepEvalAnalysisStatus.UNAVAILABLE`; no official verdict change |
| One metric fails, times out, or returns an invalid score | Typed metric failure; retain other scores and mark aggregate partial/timeout/failed |
| Metric input digest differs from the case digest | Invalid metric observation; do not persist its score |
| Trajectory contains unbounded or sensitive text | Redact and bound the projection; never publish the raw value |
| Opik host credentials or SDK are unavailable | `OpikExportStatus.UNAVAILABLE`; no Agent/Harness rerun |
| Opik flush or network export fails | Typed timeout/failed result with the same payload digest; allow retry |
| Task result is blocked/offline/non-official | Do not emit a numeric Harness feedback score |

### 5. Good / Base / Bad Cases

- Good: load one frozen Verified report and trajectory, calculate the three
  metrics through the shared analyzer, then publish that same redacted data as
  a post-run Opik tree.
- Base: on Windows or without optional credentials, record typed unavailable
  analysis/export state while retaining the deterministic official result.
- Bad: rerun the Agent for DeepEval, let a judge decide pass/fail, or publish
  raw prompts, tool output, paths, hidden reasoning, or credentials.
- Bad: treat an Opik upload failure as a Harness failure or retry by executing
  the benchmark again instead of reusing the payload.

### 6. Tests Required

- `tests/benchmarks/test_eval_analysis_observability.py`: fixed metrics and
  shared digest, partial failure, timeout, verdict immutability, span tree,
  timestamps, feedback, redaction, flush, and retry.
- `tests/benchmarks/evals/test_lion_swebench_verified.py`: standard pytest
  composition over precomputed trajectory/report; assert three metric names,
  completed analysis, and unchanged `task_result`.
- On a Linux host with the pinned optional dependencies and credentials, run
  one existing Verified result through DeepEval and Opik, then verify the
  `run_id` trace, three metric feedback entries, Harness metadata, and flush
  state. This smoke is separate from offline CI tests.
- Before handoff run the targeted benchmark tests, targeted lint/compile
  checks, and `git diff --check`; do not use unavailable optional services as
  a reason to invent a score.

### 7. Wrong vs Correct

#### Wrong

```python
# Analysis must not replace the official result or rerun the Agent.
report.task_result = judge_agent_again(case)
publish_raw_trajectory_to_opik(report)
```

#### Correct

```python
analyzed = analyze_verified_report(
    report,
    input_digest=input_digest,
    trajectory=trajectory,
    judge_model=judge_model,
)
payload = build_opik_trace_payload(
    run_id=analyzed.manifest.run_id,
    task_id=analyzed.task_result.task_id,
    attempt=analyzed.task_result.attempt,
    commit_sha=analyzed.manifest.agent_code_sha,
    profile_fingerprint=analyzed.manifest.profile_fingerprint,
    trajectory=trajectory,
    analysis=analyzed.deepeval,
    task_result=analyzed.task_result,
)
export = publish_opik_trace(payload)
assert analyzed.task_result == report.task_result
```

## 10. Verified Composition CLI

### 1. Scope / Trigger

This contract applies to the single-run composition added on top of Sections 8
and 9. It owns only argument parsing, stage ordering, report writing, and exit
codes; it must not add another Agent loop, scorer, or publisher.

### 2. Signatures

```python
def run_verified_evaluation(
    request: VerifiedExecutionRequest,
) -> VerifiedExecutionOutput: ...

def verified_exit_code(report: VerifiedEvaluationReport) -> int: ...
```

The command is `python -m benchmarks.agent_e2e verified-run` with required
`--catalog`, `--manifest`, `--task-id`, and `--commit`; `--run-id` is optional
but, when supplied, must equal `manifest.run_id`.

### 3. Contracts

- A run has one catalog task and one output directory. The fixed order is
  `artifact -> Harbor -> Harness -> DeepEval -> Opik`; later stages consume
  typed results or controlled artifacts from earlier stages.
- The DeepEval input digest is the SHA-256 of the public prompt sent to the
  worker. A Harbor `harbor-trace.json` is projected into a bounded, redacted
  trajectory; no stage invokes the Agent a second time.
- Harness may return the external SWE-bench instance ID; the composition maps
  it back to the selected catalog task ID before building `TaskResult`.
- `verified-report.json` and `verified-report.md` are always written when a
  report exists. DeepEval or Opik failures update only their own typed fields;
  they never replace an official Harness result.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Task is not selected, repeats is not `1`, digest/timeout is invalid, or `--run-id` mismatches | Reject before backend execution; no official result |
| Artifact/Harbor fails or Harbor exports no patch | Blocked/non-official report; do not invoke Harness, and never emit an official score |
| Harness returns an unknown task ID or malformed official result | Invalid/non-official report |
| No controlled trajectory is available | Retain the Harbor/Harness report; do not run DeepEval or Opik |
| DeepEval or Opik fails after official scoring | Typed failure in that stage; preserve the official task result |
| Trial is subject-failed, infra-failed, indeterminate, or an official task fails | Exit `1`, `2`, `3`, or `1` respectively; completed official pass exits `0` |

### 5. Good / Base / Bad Cases

- Good: invoke the shared function once, pass the exact Harbor patch to
  Harness, analyze the same redacted trajectory, and write both report forms.
- Base: on Windows or without a trajectory/optional service, record blocked or
  unavailable stage state without inventing a score.
- Bad: rerun the Agent for DeepEval, use Harbor reward as an official verdict,
  or turn an infrastructure failure into a zero score.

### 6. Tests Required

- `tests/benchmarks/test_verified_cli_composition.py` must assert stage order,
  public-prompt digest, task-ID normalization, fixed report paths, stable exit
  codes, redaction, and preservation of the official result when post-processing
  fails.
- Existing Verified execution, analysis, and CLI tests must continue to pass;
  the real Linux smoke is a separate single-task acceptance check.

### 7. Wrong vs Correct

#### Wrong

```python
# Judge output is not an official SWE-bench result.
report.task_result = judge_result_to_task_result(judge_output)
```

#### Correct

```python
execution = run_verified_evaluation(request)
assert execution.report.task_result == official_task_result
json_path, markdown_path = write_verified_report(execution.report, output_dir)
```
