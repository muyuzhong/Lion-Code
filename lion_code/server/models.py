from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ─── WebSocket 上行载荷 (Client -> Server) ───────────────────────

class PromptAction(BaseModel):
    action: Literal["prompt"] = "prompt"
    prompt: str
    streaming_behavior: Literal["steer", "follow_up"] | None = None


class CancelAction(BaseModel):
    action: Literal["cancel"] = "cancel"


class ContinueAction(BaseModel):
    action: Literal["continue"] = "continue"


class CompactAction(BaseModel):
    action: Literal["compact"] = "compact"


class CommandAction(BaseModel):
    action: Literal["command"] = "command"
    command: str


class ConfirmResponseAction(BaseModel):
    action: Literal["confirm_response"] = "confirm_response"
    request_id: str
    approved: bool


class PlanApprovalResponseAction(BaseModel):
    action: Literal["plan_approval_response"] = "plan_approval_response"
    request_id: str
    choice: Literal["clear-and-execute", "execute", "manual-execute", "keep-planning"]
    feedback: str | None = None


# ─── WebSocket 下行专有事件 (Server -> Client) ───────────────────

class ConfirmRequestEvent(BaseModel):
    type: Literal["confirm_request"] = "confirm_request"
    request_id: str
    message: str


class PlanApprovalRequestEvent(BaseModel):
    type: Literal["plan_approval_request"] = "plan_approval_request"
    request_id: str
    plan: str


class NoticeEvent(BaseModel):
    type: Literal["notice"] = "notice"
    text: str
    role: Literal["info", "error", "status"] = "info"


class ServerErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    error: str


# ─── REST 接口模型 ───────────────────────────────────────────────

class ServerStatusResponse(BaseModel):
    session_id: str
    model: str
    provider_name: str
    permission_mode: str
    api_configured: bool
    cwd: str
    thinking_level: str
    available_thinking_levels: list[str]
    input_tokens: int = 0
    output_tokens: int = 0
    is_running: bool = False


class ProviderConfigRequest(BaseModel):
    model: str | None = None
    api_key: str | None = None
    provider: Literal["openai", "anthropic"] | None = None
    base_url: str | None = None


class ThinkingLevelRequest(BaseModel):
    level: str


class ModelChoiceItem(BaseModel):
    provider_name: str
    model: str


class SkillItem(BaseModel):
    name: str
    description: str | None = None


class SessionSummaryItem(BaseModel):
    id: str
    startTime: str | None = None
    messageCount: int = 0
    cwd: str | None = None


class ResumeSessionRequest(BaseModel):
    session_id: str


class ToolCallDTO(BaseModel):
    id: str
    toolName: str
    args: Any = None
    status: Literal["running", "completed", "error"] = "completed"
    result: str | None = None


class ChatMessageDTO(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    reasoning: str | None = None
    tools: list[ToolCallDTO] = Field(default_factory=list)
    createdAt: str | None = None
