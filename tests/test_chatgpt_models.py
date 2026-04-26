from __future__ import annotations

import pytest


class _StubResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


def test_get_chatgpt_model_ids_filters_hidden_and_unsupported(monkeypatch: pytest.MonkeyPatch):
    from kady_agent.chatgpt_models import get_chatgpt_model_ids

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, headers=None):
            assert headers["Authorization"].startswith("Bearer ")
            return _StubResponse(
                200,
                {
                    "models": [
                        {"slug": "gpt-5.4", "priority": 1, "supported_in_api": True},
                        {"slug": "gpt-5.4-mini", "priority": 2, "supported_in_api": True},
                        {"slug": "gpt-hidden", "priority": 3, "visibility": "hidden", "supported_in_api": True},
                        {"slug": "gpt-no-api", "priority": 4, "supported_in_api": False},
                    ]
                },
            )

    monkeypatch.setattr("kady_agent.chatgpt_models.httpx.Client", lambda *a, **kw: _Client())

    assert get_chatgpt_model_ids(access_token="token-1") == ["gpt-5.4", "gpt-5.4-mini"]


def test_get_chatgpt_model_ids_falls_back_when_api_fails(monkeypatch: pytest.MonkeyPatch):
    from kady_agent.chatgpt_models import DEFAULT_CHATGPT_MODELS, get_chatgpt_model_ids

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, headers=None):
            raise RuntimeError("boom")

    monkeypatch.setattr("kady_agent.chatgpt_models.httpx.Client", lambda *a, **kw: _Client())

    assert get_chatgpt_model_ids(access_token="token-1") == DEFAULT_CHATGPT_MODELS


def test_get_chatgpt_model_ids_raises_when_fallback_disabled(monkeypatch: pytest.MonkeyPatch):
    from kady_agent.chatgpt_models import get_chatgpt_model_ids

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, headers=None):
            raise RuntimeError("boom")

    monkeypatch.setattr("kady_agent.chatgpt_models.httpx.Client", lambda *a, **kw: _Client())

    with pytest.raises(RuntimeError, match="boom"):
        get_chatgpt_model_ids(access_token="token-1", allow_fallback=False)


def test_build_chatgpt_model_entries_shape():
    from kady_agent.chatgpt_models import build_chatgpt_model_entries

    entries = build_chatgpt_model_entries(["gpt-5.4", "gpt-5.4-mini"])
    assert entries[0]["id"] == "chatgpt/gpt-5.4"
    assert entries[0]["provider"] == "ChatGPT Pro"
    assert entries[0]["pricing"] == {"prompt": 0.0, "completion": 0.0}
    assert entries[1]["id"] == "chatgpt/gpt-5.4-mini"


def test_list_chatgpt_models_uses_resolved_credentials(monkeypatch: pytest.MonkeyPatch):
    from kady_agent.chatgpt_models import list_chatgpt_models

    monkeypatch.setattr(
        "kady_agent.chatgpt_models.resolve_chatgpt_runtime_credentials",
        lambda **kwargs: {"api_key": "token-1"},
    )
    monkeypatch.setattr(
        "kady_agent.chatgpt_models.get_chatgpt_model_ids",
        lambda access_token=None, allow_fallback=True: ["gpt-5.4"],
    )

    entries = list_chatgpt_models()
    assert entries == [
        {
            "id": "chatgpt/gpt-5.4",
            "label": "GPT-5.4",
            "provider": "ChatGPT Pro",
            "tier": "high",
            "context_length": 0,
            "pricing": {"prompt": 0.0, "completion": 0.0},
            "modality": "text+image->text",
            "description": "Authenticated via ChatGPT Pro account.",
        }
    ]
