# Opik Cloud trace export 调研

## 结论

- Opik Cloud 官方 Python SDK 的 `@track` 支持同步、异步、生成器和嵌套 span；`Opik.trace()`、
  `Trace.span()` 也支持显式 start/end timestamp，适合发布已经完成的隔离任务轨迹。
- DeepEval scores 可通过 `opik_context.update_current_trace(feedback_scores=...)` 或 client feedback API
  写入 trace；短命脚本应在跟踪函数外调用 `opik.flush_tracker()`，或使用 `flush=True`。
- DeepEval tracing 官方默认云端是 Confident AI；未发现公开、稳定的 DeepEval native trace 到 Opik
  的直接 exporter。
- Lion `OpenAICompatibleProvider` 与 `AnthropicProvider` 当前都直接使用 `httpx.AsyncClient`
  （`lion_code/providers/openai_compatible.py:155`、`lion_code/providers/anthropic.py:135`）；Opik
  `track_openai` 只接受 OpenAI/AsyncOpenAI client，因此不能用于当前 Provider。
- 因此采用同源双输出：Lion typed events 生成一次脱敏 trajectory，DeepEval Python SDK 用它评分，
  Linux 宿主再用 Opik Python SDK 发布等价 agent/llm/tool span tree 和 DeepEval feedback。
- 不在 Harbor Agent 容器内直接使用 `@track` 上传：被测 Agent 具备 shell 权限，直接注入
  `OPIK_API_KEY` 会扩大凭证泄露面。用户已确认 MVP 采用任务结束后宿主批量发布；实时 trace 需要
  额外宿主 relay，留到后续任务。
- 不依赖 `deepeval.tracing.otel.*` 私有实现；Opik export failure 与评分结果解耦。

## 官方依据

- Opik `track`：
  https://www.comet.com/docs/opik/python-sdk-reference/track.html
- Opik client trace/span API：
  https://www.comet.com/docs/opik/python-sdk-reference/Opik.html
- Opik feedback：
  https://www.comet.com/docs/opik/tracing/advanced/annotate_traces
- Opik OpenAI integration：
  https://www.comet.com/docs/opik/python-sdk-reference/integrations/openai/track_openai.html
- DeepEval tracing：
  https://deepeval.com/docs/evaluation-llm-tracing
- DeepEval trajectory evaluation：
  https://deepeval.com/docs/evaluation-trajectory-based-llm-evals

## 安全边界

- Opik publisher 位于 Linux evaluation host，不在 Harbor task/Agent 容器。
- Opik API key 只从环境读取，不写入 manifest、trajectory、report 或命令行参数。
- 上传仅包含 bounded/redacted summary、结构、状态、时长、token/cost、run/task/commit/profile 关联值；
  不包含 hidden reasoning、完整 session、完整工具输出或 verifier 私有内容。
