"""模型选择的最小数据层:ModelChoice + 已知模型的本地累积。

不引入 Tau 的供应商目录制(catalog.toml);Lion 的模型是自由字符串,
picker 的候选来自「用过即记住」——每次配置/切换模型时追加到
~/.lion-code/config.json 的 known_models,随使用自然长出目录。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from lion_code import config as _config

_MAX_KNOWN_MODELS = 20


@dataclass(frozen=True, slots=True)
class ModelChoice:
    """一个可选的 provider/model 组合。"""

    provider_name: str
    model: str


def load_model_choices() -> tuple[ModelChoice, ...]:
    """从本地配置合成候选:当前保存的模型优先,已知模型按最近使用排序。"""
    config = _config.load_api_config()
    choices: list[ModelChoice] = []
    provider = str(config.get("provider") or "openai")
    if config.get("model"):
        choices.append(ModelChoice(provider_name=provider, model=str(config["model"])))
    known = config.get("known_models")
    if isinstance(known, list):
        for entry in known:
            if (
                isinstance(entry, dict)
                and isinstance(entry.get("model"), str)
                and entry["model"]
            ):
                choices.append(
                    ModelChoice(
                        provider_name=str(entry.get("provider") or provider),
                        model=entry["model"],
                    )
                )
    return tuple(dict.fromkeys(choices))


def remember_model(*, provider: str, model: str) -> None:
    """把用过的模型记入 known_models(最近优先、去重、封顶)。

    只更新 known_models 键,凭证等其余字段原样保留。
    """
    if not model:
        return
    config = _config.load_api_config()
    known = [
        entry
        for entry in (config.get("known_models") or [])
        if isinstance(entry, dict) and entry.get("model") != model
    ]
    known.insert(0, {"provider": provider, "model": model})
    config["known_models"] = known[:_MAX_KNOWN_MODELS]
    _config.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _config.CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
