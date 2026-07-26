"""provider_settings 最小数据层测试:已知模型的累积、去重、封顶与配置保留。"""

from __future__ import annotations

import json

import pytest

from lion_code import config as config_module
from lion_code.application.provider_settings import (
    ModelChoice,
    load_model_choices,
    remember_model,
)


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    return path


def test_remember_and_load_round_trip(isolated_config) -> None:
    remember_model(provider="openai", model="m-a")
    remember_model(provider="openai", model="m-b")

    choices = load_model_choices()
    assert choices == (
        ModelChoice(provider_name="openai", model="m-b"),
        ModelChoice(provider_name="openai", model="m-a"),
    )


def test_remember_dedupes_and_moves_to_front(isolated_config) -> None:
    remember_model(provider="openai", model="m-a")
    remember_model(provider="openai", model="m-b")
    remember_model(provider="openai", model="m-a")

    models = [choice.model for choice in load_model_choices()]
    assert models == ["m-a", "m-b"]


def test_remember_caps_history(isolated_config) -> None:
    for index in range(25):
        remember_model(provider="openai", model=f"m-{index}")
    assert len(load_model_choices()) == 20


def test_saved_active_model_listed_first(isolated_config) -> None:
    remember_model(provider="openai", model="m-old")
    config_module.save_api_config(
        provider="openai", model="m-active", api_key="k", base_url="https://x/v1"
    )

    choices = load_model_choices()
    assert choices[0] == ModelChoice(provider_name="openai", model="m-active")
    assert ModelChoice(provider_name="openai", model="m-old") in choices


def test_save_api_config_preserves_known_models(isolated_config) -> None:
    remember_model(provider="openai", model="m-keep")
    config_module.save_api_config(
        provider="openai", model="m-new", api_key="k", base_url=""
    )

    data = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert data["model"] == "m-new"
    assert [entry["model"] for entry in data["known_models"]] == ["m-keep"]
