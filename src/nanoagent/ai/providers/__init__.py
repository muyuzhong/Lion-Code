"""nanoagent.ai.providers — concrete provider adapters (mock, openai)."""

from nanoagent.ai.providers.mock import MockModel, create_mock_model, register_mock

__all__ = ["MockModel", "create_mock_model", "register_mock"]
