from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from lion_code.core.messages import WireModel

# ─── WebSocket 上行载荷 (Client -> Server) ───────────────────────


class ClientActionModel(WireModel):
    """浏览器控制消息必须严格匹配唯一 action 变体。"""

    model_config = ConfigDict(
        strict=True,
        validate_by_name=False,
        validate_by_alias=True,
    )


class PromptAction(ClientActionModel):
    action: Literal["prompt"] = "prompt"
    prompt: str


class SteerAction(ClientActionModel):
    action: Literal["steer"] = "steer"
    prompt: str


class FollowUpAction(ClientActionModel):
    action: Literal["follow_up"] = "follow_up"
    prompt: str


class CancelAction(ClientActionModel):
    action: Literal["cancel"] = "cancel"


class ContinueAction(ClientActionModel):
    action: Literal["continue"] = "continue"


class CompactAction(ClientActionModel):
    action: Literal["compact"] = "compact"


class CommandAction(ClientActionModel):
    action: Literal["command"] = "command"
    command: str


class ConfirmResponseAction(ClientActionModel):
    action: Literal["confirm_response"] = "confirm_response"
    request_id: str
    approved: bool


class PlanApprovalResponseAction(ClientActionModel):
    action: Literal["plan_approval_response"] = "plan_approval_response"
    request_id: str
    choice: Literal["clear-and-execute", "execute", "manual-execute", "keep-planning"]
    feedback: str | None = None


type ClientAction = Annotated[
    PromptAction
    | SteerAction
    | FollowUpAction
    | CancelAction
    | ContinueAction
    | CompactAction
    | CommandAction
    | ConfirmResponseAction
    | PlanApprovalResponseAction,
    Field(discriminator="action"),
]

CLIENT_ACTION_ADAPTER: TypeAdapter[ClientAction] = TypeAdapter(ClientAction)


# ─── WebSocket 下行专有事件 (Server -> Client) ───────────────────


class ConfirmRequestEvent(WireModel):
    type: Literal["confirm_request"] = "confirm_request"
    request_id: str
    message: str


class PlanApprovalRequestEvent(WireModel):
    type: Literal["plan_approval_request"] = "plan_approval_request"
    request_id: str
    plan: str


class NoticeEvent(WireModel):
    type: Literal["notice"] = "notice"
    text: str
    role: Literal["info", "error", "status"] = "info"


class ServerErrorEvent(WireModel):
    type: Literal["server_error"] = "server_error"
    message: str


class ProtocolErrorEvent(WireModel):
    type: Literal["protocol_error"] = "protocol_error"
    message: str


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
    label: str | None = None
    startTime: str | None = None
    messageCount: int = 0
    cwd: str | None = None


class ResumeSessionRequest(BaseModel):
    session_id: str


class RenameSessionRequest(BaseModel):
    session_id: str
    label: str = Field(min_length=1, max_length=80)


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
    error: str | None = None
    createdAt: str | None = None
