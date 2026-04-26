from __future__ import annotations

from pathlib import Path

import yaml


def test_litellm_config_contains_chatgpt_wildcard():
    config = yaml.safe_load(Path("litellm_config.yaml").read_text(encoding="utf-8"))
    model_list = config["model_list"]
    entry = next((item for item in model_list if item.get("model_name") == "chatgpt/*"), None)
    assert entry is not None
    assert entry["litellm_params"]["model"] == "chatgpt/*"
    assert entry["litellm_params"]["timeout"] == 600
    assert entry["litellm_params"]["stream_timeout"] == 600


def test_litellm_config_keeps_existing_wildcards():
    config = yaml.safe_load(Path("litellm_config.yaml").read_text(encoding="utf-8"))
    model_names = {item.get("model_name") for item in config["model_list"]}
    assert "openrouter/*" in model_names
    assert "ollama/*" in model_names
