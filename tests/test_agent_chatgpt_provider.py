from __future__ import annotations

import copy
import types

from kady_agent import agent as agent_module


class _DummyContext:
    def __init__(self, state: dict):
        self.state = state


class _DummyRequest:
    def __init__(self, model: str | None = None):
        self.model = model


def test_override_model_stashes_chatgpt_credentials_per_request(monkeypatch):
    original = copy.deepcopy(agent_module._LITELLM_MODEL._additional_args)
    try:
        agent_module._LITELLM_MODEL._additional_args["extra_body"] = {"usage": {"include": True}}
        agent_module._LITELLM_MODEL._additional_args["extra_headers"] = {"X-Kady-Role": "orchestrator"}
        monkeypatch.setattr(
            agent_module,
            "resolve_chatgpt_runtime_credentials",
            lambda **kwargs: {
                "api_key": "chatgpt-access-token",
                "base_url": "https://chatgpt.com/backend-api/codex",
            },
        )

        llm_request = _DummyRequest(model=None)
        ctx = _DummyContext({"_model": "chatgpt/gpt-5.4", "_sessionId": "s1", "_turnId": "t1"})

        agent_module._override_model(ctx, llm_request)

        assert llm_request.model == "chatgpt/gpt-5.4"
        scoped = agent_module._REQUEST_ADDITIONAL_ARGS.get()
        assert scoped["api_key"] == "chatgpt-access-token"
        assert scoped["api_base"] == "https://chatgpt.com/backend-api/codex"
        assert scoped["custom_llm_provider"] == "chatgpt"
        assert "usage" not in scoped.get("extra_body", {})
        meta = scoped.get("metadata") or {}
        assert meta["kady_role"] == "orchestrator"
        assert meta["kady_session_id"] == "s1"
        assert meta["kady_turn_id"] == "t1"
        assert agent_module._LITELLM_MODEL._additional_args["extra_body"] == {"usage": {"include": True}}
        assert agent_module._LITELLM_MODEL._additional_args["extra_headers"] == {"X-Kady-Role": "orchestrator"}
    finally:
        agent_module._REQUEST_ADDITIONAL_ARGS.set(None)
        agent_module._LITELLM_MODEL._additional_args.clear()
        agent_module._LITELLM_MODEL._additional_args.update(original)


def test_override_model_keeps_openrouter_usage_accounting_scoped(monkeypatch):
    original = copy.deepcopy(agent_module._LITELLM_MODEL._additional_args)
    try:
        llm_request = _DummyRequest(model=None)
        ctx = _DummyContext({"_model": "openrouter/anthropic/claude-opus-4.7", "_sessionId": "s1", "_turnId": "t1"})

        agent_module._override_model(ctx, llm_request)

        assert llm_request.model == "openrouter/anthropic/claude-opus-4.7"
        scoped = agent_module._REQUEST_ADDITIONAL_ARGS.get()
        assert scoped["extra_body"]["usage"] == {"include": True}
        headers = scoped["extra_headers"]
        assert headers["X-Kady-Role"] == "orchestrator"
        assert headers["X-Kady-Session-Id"] == "s1"
        assert headers["X-Kady-Turn-Id"] == "t1"
        assert "api_key" not in scoped
    finally:
        agent_module._REQUEST_ADDITIONAL_ARGS.set(None)
        agent_module._LITELLM_MODEL._additional_args.clear()
        agent_module._LITELLM_MODEL._additional_args.update(original)
