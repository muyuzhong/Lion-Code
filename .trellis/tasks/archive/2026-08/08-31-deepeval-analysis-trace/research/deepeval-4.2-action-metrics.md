# DeepEval 4.2.0 Action-Metric Evidence

## Version-Specific Source Check

The repository pins `deepeval==4.2.0` in `pyproject.toml:25`. The exact wheel was inspected outside the workspace during planning.

- `ArgumentCorrectnessMetric._required_params` contains `INPUT` and `TOOLS_CALLED`; it is LLM-judged and does not require expected tools.
- `ToolCorrectnessMetric._required_params` contains `INPUT`, `TOOLS_CALLED`, and `EXPECTED_TOOLS`, even when `available_tools` is supplied. Production SWE-bench traces therefore cannot use it honestly without annotations.
- 4.2.0 exposes `update_current_span`, `update_current_trace`, and `next_llm_span`, and supports metrics on component spans. The project may keep a direct pinned adapter rather than instrumenting Lion Runtime.
- `ArgumentCorrectnessMetric` gives a default score of 1 when no tool calls are present. The adapter must represent “not evaluated/no calls” explicitly instead of presenting this as evidence of perfect arguments.

## Current Official Documentation

- Agent metric layers and scopes: https://deepeval.com/guides/guides-ai-agent-evaluation-metrics
- Argument Correctness: https://deepeval.com/docs/metrics-argument-correctness
- Tool Correctness: https://deepeval.com/docs/metrics-tool-correctness
- Plan Adherence default behavior: https://deepeval.com/docs/metrics-plan-adherence

Current guidance places Tool/Argument metrics at component/action scope and planning/execution metrics at trajectory scope. It also documents a default score of 1 when no plan is detectable. The task therefore limits Phase 1 to action diagnostics and defers plan metrics.

## Decision

- Use `ArgumentCorrectnessMetric` with safe semantic tool parameters.
- Use a narrow custom `ToolDecisionQuality` GEval for referenceless tool-choice/order/recovery diagnosis.
- Do not fake expected tools, do not enable planning metrics, and do not interpret empty calls as a perfect result.
