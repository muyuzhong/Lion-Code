"""Lion Code 的 Textual TUI(vendored 自 tau_coding/tui,迁移中)。

阶段 2:迁入显示状态、事件适配、小组件、主题、补全、终端集成等素材;
主应用 app.py 按迁移计划在阶段 3 面向 LionCodingSession 重构后迁入。
"""

from .adapter import TuiEventAdapter
from .autocomplete import CompletionOption
from .config import (
    BUILTIN_TUI_THEME_NAMES,
    HIGH_CONTRAST_THEME,
    TAU_DARK_THEME,
    TAU_LIGHT_THEME,
    TuiConfigError,
    TuiKeybindings,
    TuiRoleStyle,
    TuiSettings,
    TuiTheme,
    TuiThemeName,
    TurnNotificationMode,
    get_tui_theme,
    load_tui_settings,
    save_tui_settings,
    tui_settings_path,
)
from .state import ChatItem, TuiState
from .widgets import (
    CompactSessionInfo,
    SessionSidebar,
    StreamingTranscriptMessageWidget,
    TranscriptMessageWidget,
    TranscriptView,
    render_chat_item,
    render_compact_session_info,
    render_session_sidebar,
    transcript_item_selection_text,
)

__all__ = [
    "BUILTIN_TUI_THEME_NAMES",
    "ChatItem",
    "CompactSessionInfo",
    "CompletionOption",
    "HIGH_CONTRAST_THEME",
    "SessionSidebar",
    "StreamingTranscriptMessageWidget",
    "TAU_DARK_THEME",
    "TAU_LIGHT_THEME",
    "TranscriptMessageWidget",
    "TranscriptView",
    "TuiConfigError",
    "TuiEventAdapter",
    "TuiKeybindings",
    "TuiRoleStyle",
    "TuiSettings",
    "TuiState",
    "TuiTheme",
    "TuiThemeName",
    "TurnNotificationMode",
    "get_tui_theme",
    "load_tui_settings",
    "render_chat_item",
    "render_compact_session_info",
    "render_session_sidebar",
    "save_tui_settings",
    "transcript_item_selection_text",
    "tui_settings_path",
]
