"""Provider-neutral active-context projection for Lion Core."""

from lion_code.context.estimator import estimate_messages_tokens
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
    ContextAction,
    ContextActionType,
    ContextRuntimeState,
    PreparedContext,
)

__all__ = [
    "ContextAction",
    "ContextActionType",
    "ContextManager",
    "ContextPolicy",
    "ContextRuntimeState",
    "ModelLimitsResolver",
    "PreparedContext",
    "effective_window_tokens",
    "estimate_messages_tokens",
    "fallback_context_window",
    "fallback_model_limits",
    "project_messages",
]
