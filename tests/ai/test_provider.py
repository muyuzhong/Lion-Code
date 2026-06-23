import pytest

from nanoagent.ai import Context
from nanoagent.ai.provider import clear_providers, get_provider, register_provider, stream
from nanoagent.ai.providers.mock import create_mock_model, register_mock


@pytest.mark.asyncio
async def test_dispatch_by_api():
    clear_providers()
    register_mock()
    mock = create_mock_model(responses=[{"content": ["ok"]}])
    events = [e async for e in stream(mock, Context(), None)]
    assert events[-1].message.content[0].text == "ok"


def test_get_provider_unknown_raises():
    clear_providers()
    with pytest.raises(KeyError):
        get_provider("nope")


def test_register_provider_rejects_empty_api():
    clear_providers()
    with pytest.raises(ValueError, match="api must not be empty"):
        register_provider("", object())


def test_registered_provider_apis_returns_sorted_snapshot():
    from nanoagent.ai import registered_provider_apis

    clear_providers()
    register_provider("z-api", object())
    register_provider("a-api", object())

    apis = registered_provider_apis()

    assert apis == ("a-api", "z-api")
