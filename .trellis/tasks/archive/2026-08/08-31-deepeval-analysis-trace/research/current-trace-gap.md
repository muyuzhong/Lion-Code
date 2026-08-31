# Current Trace Gap

## Repository Evidence

- `benchmarks/agent_e2e/trace.py:41-54` defines `TraceEvent` with summary/digests/tool name only.
- `benchmarks/agent_e2e/trace.py:104-154` sanitizes the raw event before persisting `TraceEvent`; arguments become a digest and arbitrary tool output is excluded from the summary.
- `benchmarks/agent_e2e/evidence.py:80-96` defines the separate fact/digest-only `ProcessEvidence` contract.
- `benchmarks/agent_e2e/models.py:488-510` defines the current DeepEval projection without semantic parameters/results.
- `benchmarks/agent_e2e/deepeval_metrics.py:81-97` creates DeepEval `ToolCall` objects with only `name`.
- `benchmarks/agent_e2e/deepeval_metrics.py:225-262` serializes event type/tool name/digests/timestamps into the Judge output.
- `benchmarks/agent_e2e/verified_runner.py:672-716` loads only `harbor-trace.json.events` and rebuilds the digest-only trajectory; it ignores `ProcessEvidence` for DeepEval.
- `lion_code/core/events.py:51-71` already emits typed tool start/update/end events with raw args, structured result and error state. Projection can happen in the benchmark worker without changing Runtime.
- `lion_code/core/loop.py:396-437` correlates the same `tool_call_id` across start/update/end; start/update carry args and end carries result/error.
- `lion_code/tooling/builtin.py:78-238` provides the finite built-in tool schemas needed for a narrow semantic projection.

## Consequence

The current persisted files cannot reconstruct paths, commands or arguments from their digests. Existing successful run IDs remain useful scenario baselines, but the three trajectories must be rerun after the new projector exists before they can validate semantic DeepEval behavior.
