"""Lion Core 的供应商无关活跃上下文投影。"""

from lion_code.context.compaction import (
    COMPACTION_PROMPT_TEMPLATE,
    OBJECTIVE_UNAVAILABLE_MARKER,
    SUMMARY_HEADINGS,
    SUMMARY_SYSTEM_PROMPT,
    CompactionRequest,
    ContextCompactor,
    InvalidCompactionSummary,
    ProviderContextCompactor,
    build_compaction_request,
    estimate_compaction_input_tokens,
    resolve_compaction_objective,
)
from lion_code.context.estimator import estimate_messages_tokens, estimate_text_tokens
from lion_code.context.limits import (
    ModelLimitsResolver,
    effective_window_tokens,
    fallback_context_window,
    fallback_model_limits,
)
from lion_code.context.manager import ContextManager
from lion_code.context.policy import ContextPolicy
from lion_code.context.projector import project_messages
from lion_code.context.types import (
    CompactionStatus,
    ContextAction,
    ContextActionType,
    ContextRuntimeState,
    ContextUtilization,
    ContextView,
    PreparedContext,
    ToolTrace,
)

__all__ = [
    "COMPACTION_PROMPT_TEMPLATE",
    "OBJECTIVE_UNAVAILABLE_MARKER",
    "SUMMARY_HEADINGS",
    "SUMMARY_SYSTEM_PROMPT",
    "CompactionRequest",
    "CompactionStatus",
    "ContextAction",
    "ContextActionType",
    "ContextCompactor",
    "ContextManager",
    "ContextPolicy",
    "ContextRuntimeState",
    "ContextUtilization",
    "ContextView",
    "InvalidCompactionSummary",
    "ModelLimitsResolver",
    "PreparedContext",
    "ProviderContextCompactor",
    "ToolTrace",
    "build_compaction_request",
    "effective_window_tokens",
    "estimate_compaction_input_tokens",
    "estimate_messages_tokens",
    "estimate_text_tokens",
    "fallback_context_window",
    "fallback_model_limits",
    "project_messages",
    "resolve_compaction_objective",
]
