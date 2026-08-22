# Current Tool Runtime Boundary

## Evidence inspected

- `lion_code/tooling/runtime.py::ToolRuntime.execute` resolves one registered
  `LionTool`, runs declared pre middleware, invokes the tool, then runs declared
  post middleware. Unknown tools and uncaught tool/middleware failures become
  `ToolResult(is_error=True)`.
- `lion_code/tooling/types.py::ToolCapabilities` already has the two routing
  signals required by PR-S1: `mutates_workspace` and `executes_process`.
- `lion_code/tooling/builtin.py` marks `write_file` and `edit_file` as
  `mutates_workspace=True` and binds `run_shell` to the profile-selected
  `CommandExecutionBackend` with `executes_process=True`.
- `lion_code/tooling/context.py::ToolContext` is the per-agent dependency seam;
  it already carries the audit callback used by `AuditMiddleware`.
- `lion_code/composition/agent_builder.py::_build_tooling_graph` is the only
  current construction point for ToolContext and the middleware list. Tool
  infrastructure belongs in `ToolBindings`, not in Profiles or Agent Runtime.
- `lion_code/adapters/tool_adapter.py::to_core_result` copies `ToolResult.details`
  into `AgentToolResult.details`.
- `lion_code/core/loop.py::_execute_tool_call` copies result content/details into
  `ToolResultMessage`; Anthropic and OpenAI provider adapters send the textual
  `ToolResultMessage.text` to the next provider request. The rollback sentence
  must therefore be in result content, not only in structured details.

## Boundary conclusion

PR-S1 can be implemented entirely in `lion_code/tooling/` plus composition
bindings/wiring and tests. It does not require a Core message change or a
conversation-runtime injection channel. The existing ToolRuntime middleware
chain remains the only execution route.

