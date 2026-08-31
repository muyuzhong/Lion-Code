# Current Evaluation Contract Excerpt

Authoritative source: `.trellis/spec/backend/agent-e2e-evaluation.md`.

## Process Evidence Boundary

- `ProcessEvidenceProjector` runs inside `TraceRecorder.record()` before generic sanitization and writes a separate evidence array.
- Evidence stores only facts and digests: call identity/phase/fingerprint, error flag, target scope, validation marker, compaction and termination.
- `ProcessVerifier` is deterministic, never changes `TaskResult.verdict`, and must degrade to evidence unavailable instead of guessing when evidence is absent.
- Current process rules cover repeated calls, unrecovered tool errors, validation missing, test tampering, premature termination and post-compaction regression.

## Existing DeepEval/Opik Boundary

- DeepEval is benchmark-only post-processing over an already completed Agent run. It must not create another Agent execution or scoring route.
- Current code/spec fixes three metrics (`TaskCompletionMetric`, `StepEfficiencyMetric`, `TrajectoryQuality`) over one bounded redacted trajectory; this task intentionally replaces that fixed-three contract with the approved Phase-1 action metrics.
- Each metric failure/timeout is typed independently, successful siblings remain, and `analyze_verified_report()` may update only analysis fields.
- Opik uses the same controlled trajectory, host-only credentials, explicit flush and same-payload retry; it never changes Harness results.
- Raw prompts, tool outputs, paths, hidden reasoning and credentials are forbidden. This task narrows the rule to allow only explicitly structured safe relative targets and error facts in a separate Analysis Trace.

## Verified Composition Boundary

- Fixed execution order remains `artifact → Harbor → Harness → DeepEval → Opik`.
- Later stages consume typed results/artifacts from earlier stages and never rerun the Agent.
- DeepEval/Opik failures preserve official Harness output; missing controlled Analysis Trace must produce unavailable analysis rather than an invented score.
- Required validation remains focused benchmark tests plus static/compile/diff checks; real Linux/provider/Cloud smoke is separate evidence.

Implementation and review agents must read the authoritative source around its ProcessEvidence, Offline DeepEval Analysis, and Verified Composition sections before changing the spec itself.
