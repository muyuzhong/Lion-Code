# Agent E2E Evaluation Boundaries

## 1. Scope / Trigger

Apply this contract when adding a coding-Agent evaluation task, changing an
evaluation manifest/result schema, wiring an Agent worker, or implementing a
container backend. The evaluation system is a separate orchestration boundary:
it reuses `Agent.run()` and typed Core events but must not create a second Agent
history, session writer, provider path, or stdout-log parser.

The current `benchmarks/agent_e2e/` foundation is deliberately offline-only.
It contains a backend protocol and test fakes, not a Docker scheduler or a real
provider invocation. A host process or a Git worktree alone is never an official
evaluation isolation boundary.

## 2. Signatures

```python
class Agent:
    def __init__(..., mcp_enabled: bool = True) -> None: ...

async def run_agent_worker(
    request: AgentExecutionRequest,
    *,
    agent_factory: AgentFactory = Agent,
    trace_recorder: TraceRecorder | None = None,
) -> WorkerResult: ...

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
- An evaluation worker must call `Agent.run()` with `mcp_enabled=False`, subscribe
  through `agent.core_runtime`, and construct `SessionRepository` under a path
  outside the Agent workspace. The product default remains `mcp_enabled=True`.
- `IsolationReport.official_safe` requires workspaces that do not overlap in
  either direction and `private_assets_visible_to_agent=False`. Equal or nested
  Agent/verifier paths are unsafe because the Agent could read verifier files.
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
| `mcp_enabled=True` reaches `run_agent_worker` | Raise `ValueError`; a worker must not discover machine/project MCP servers |
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
- Bad: treating two paths as isolated merely because their strings differ. A
  verifier directory inside the Agent workspace is still visible to the Agent.
- Bad: using a host worktree plus `bypassPermissions` as an official run; the
  Agent can access paths outside the worktree and the verifier assets are not
  protected by a container boundary.

## 6. Tests Required

- `tests/benchmarks/test_models_catalog.py`: version round-trip, unknown fields,
  catalog/lock mismatches, and official verdict/score consistency.
- `tests/benchmarks/test_orchestrator.py`: unavailable/fake backend, worker and
  verifier errors, cleanup, checkpoint resume, equal/nested workspace rejection.
- `tests/benchmarks/test_agent_worker.py`: real `Agent` worker has MCP disabled,
  Core output is captured, and the JSONL session remains outside the task workspace.
- `tests/benchmarks/test_trace.py`: secret/path/session/prompt redaction and loop
  fingerprint evidence.
- `tests/benchmarks/test_cli.py`: the online command remains explicitly blocked
  and never emits `task_resolved`.
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
