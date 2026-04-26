from __future__ import annotations

import uuid

import pytest


pytestmark = pytest.mark.integration


async def test_chatgpt_status_unauthenticated(asgi_client, monkeypatch):
    monkeypatch.setattr(
        "server.get_chatgpt_auth_status",
        lambda: {
            "authenticated": False,
            "accountId": None,
            "lastRefresh": None,
            "error": None,
        },
    )
    monkeypatch.setattr("server.list_chatgpt_models", lambda: [])

    resp = await asgi_client.get("/settings/chatgpt/status")
    assert resp.status_code == 200
    assert resp.json() == {
        "authenticated": False,
        "accountId": None,
        "lastRefresh": None,
        "modelsAvailable": 0,
        "error": None,
    }


async def test_chatgpt_status_authenticated_counts_models(asgi_client, monkeypatch):
    calls = {"count": 0}

    def _status():
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "authenticated": True,
                "accountId": "acct_123",
                "lastRefresh": "2026-04-22T02:00:00Z",
                "error": "stored_access_token_expired",
            }
        return {
            "authenticated": True,
            "accountId": "acct_123",
            "lastRefresh": "2026-04-22T02:00:01Z",
            "error": None,
        }

    monkeypatch.setattr("server.get_chatgpt_auth_status", _status)
    monkeypatch.setattr(
        "server.list_chatgpt_models",
        lambda strict=False: [{"id": "chatgpt/gpt-5.4"}, {"id": "chatgpt/gpt-5.4-mini"}],
    )

    resp = await asgi_client.get("/settings/chatgpt/status")
    assert resp.status_code == 200
    assert resp.json() == {
        "authenticated": True,
        "accountId": "acct_123",
        "lastRefresh": "2026-04-22T02:00:01Z",
        "modelsAvailable": 2,
        "error": None,
    }


async def test_chatgpt_models_unavailable_when_unauthenticated(asgi_client, monkeypatch):
    monkeypatch.setattr(
        "server.get_chatgpt_auth_status",
        lambda: {
            "authenticated": False,
            "accountId": None,
            "lastRefresh": None,
            "error": None,
        },
    )

    resp = await asgi_client.get("/chatgpt/models")
    assert resp.status_code == 200
    assert resp.json() == {"available": False, "models": []}


async def test_chatgpt_models_available_when_authenticated(asgi_client, monkeypatch):
    monkeypatch.setattr(
        "server.get_chatgpt_auth_status",
        lambda: {
            "authenticated": True,
            "accountId": "acct_123",
            "lastRefresh": "2026-04-22T02:00:00Z",
            "error": None,
        },
    )
    monkeypatch.setattr(
        "server.list_chatgpt_models",
        lambda strict=False: [{"id": "chatgpt/gpt-5.4", "label": "GPT-5.4"}],
    )

    resp = await asgi_client.get("/chatgpt/models")
    assert resp.status_code == 200
    assert resp.json() == {
        "available": True,
        "models": [{"id": "chatgpt/gpt-5.4", "label": "GPT-5.4"}],
    }


async def test_chatgpt_models_unavailable_when_discovery_fails(asgi_client, monkeypatch):
    monkeypatch.setattr(
        "server.get_chatgpt_auth_status",
        lambda: {
            "authenticated": True,
            "accountId": "acct_123",
            "lastRefresh": "2026-04-22T02:00:00Z",
            "error": None,
        },
    )

    def _models(strict=False):
        if strict:
            raise RuntimeError("model discovery failed")
        return [{"id": "chatgpt/gpt-5.4", "label": "GPT-5.4"}]

    monkeypatch.setattr("server.list_chatgpt_models", _models)

    resp = await asgi_client.get("/chatgpt/models")
    assert resp.status_code == 200
    assert resp.json() == {
        "available": True,
        "models": [{"id": "chatgpt/gpt-5.4", "label": "GPT-5.4"}],
        "error": "model discovery failed",
        "degraded": True,
    }


async def test_chatgpt_status_reports_discovery_error(asgi_client, monkeypatch):
    monkeypatch.setattr(
        "server.get_chatgpt_auth_status",
        lambda: {
            "authenticated": True,
            "accountId": "acct_123",
            "lastRefresh": "2026-04-22T02:00:00Z",
            "error": None,
        },
    )

    def _models(strict=False):
        if strict:
            raise RuntimeError("model discovery failed")
        return [{"id": "chatgpt/gpt-5.4", "label": "GPT-5.4"}]

    monkeypatch.setattr("server.list_chatgpt_models", _models)

    resp = await asgi_client.get("/settings/chatgpt/status")
    assert resp.status_code == 200
    assert resp.json() == {
        "authenticated": True,
        "accountId": "acct_123",
        "lastRefresh": "2026-04-22T02:00:00Z",
        "modelsAvailable": 1,
        "error": "model discovery failed",
    }


async def test_chatgpt_login_start_returns_device_code(asgi_client, monkeypatch):
    monkeypatch.setattr(
        "server.request_chatgpt_device_code",
        lambda timeout_seconds=15.0: {
            "device_auth_id": "dev-123",
            "user_code": "ABCD-1234",
            "interval": 5,
            "verification_uri": "https://auth.openai.com/codex/device",
            "requested_at": __import__("time").time(),
        },
    )
    monkeypatch.setattr("server._CHATGPT_LOGIN_SESSIONS", {})

    resp = await asgi_client.post("/settings/chatgpt/login/start")
    assert resp.status_code == 200
    body = resp.json()
    assert body["verificationUri"] == "https://auth.openai.com/codex/device"
    assert body["userCode"] == "ABCD-1234"
    assert body["pollIntervalSeconds"] == 5
    assert uuid.UUID(body["loginSessionId"])


async def test_chatgpt_login_poll_returns_pending_then_authenticated(asgi_client, monkeypatch):
    monkeypatch.setattr("server._CHATGPT_LOGIN_SESSIONS", {})
    monkeypatch.setattr(
        "server.request_chatgpt_device_code",
        lambda timeout_seconds=15.0: {
            "device_auth_id": "dev-123",
            "user_code": "ABCD-1234",
            "interval": 5,
            "verification_uri": "https://auth.openai.com/codex/device",
            "requested_at": __import__("time").time(),
        },
    )

    start = await asgi_client.post("/settings/chatgpt/login/start")
    login_session_id = start.json()["loginSessionId"]

    state = {"calls": 0, "saved": None}

    def _poll(device_auth_id, user_code, timeout_seconds=15.0):
        state["calls"] += 1
        if state["calls"] == 1:
            return None
        return {"authorization_code": "auth-1", "code_verifier": "verifier-1"}

    monkeypatch.setattr("server.poll_chatgpt_device_code", _poll)
    monkeypatch.setattr(
        "server.exchange_chatgpt_authorization_code",
        lambda authorization_code, code_verifier, timeout_seconds=15.0: {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
        },
    )
    monkeypatch.setattr(
        "server.save_chatgpt_tokens",
        lambda tokens, last_refresh=None, account_id=None: state.__setitem__("saved", tokens),
    )
    monkeypatch.setattr(
        "server.get_chatgpt_auth_status",
        lambda: {
            "authenticated": True,
            "accountId": "acct_123",
            "lastRefresh": "2026-04-22T03:00:00Z",
            "error": None,
        },
    )

    pending = await asgi_client.post(
        "/settings/chatgpt/login/poll", json={"loginSessionId": login_session_id}
    )
    assert pending.status_code == 200
    assert pending.json() == {"status": "pending"}

    complete = await asgi_client.post(
        "/settings/chatgpt/login/poll", json={"loginSessionId": login_session_id}
    )
    assert complete.status_code == 200
    assert complete.json() == {
        "status": "authenticated",
        "auth": {
            "authenticated": True,
            "accountId": "acct_123",
            "lastRefresh": "2026-04-22T03:00:00Z",
            "error": None,
        },
    }
    assert state["saved"] == {"access_token": "access-1", "refresh_token": "refresh-1"}


async def test_chatgpt_login_poll_404_for_unknown_session(asgi_client, monkeypatch):
    monkeypatch.setattr("server._CHATGPT_LOGIN_SESSIONS", {})

    resp = await asgi_client.post(
        "/settings/chatgpt/login/poll", json={"loginSessionId": "missing-session"}
    )
    assert resp.status_code == 404


async def test_chatgpt_login_poll_expires_stale_session(asgi_client, monkeypatch):
    monkeypatch.setattr(
        "server._CHATGPT_LOGIN_SESSIONS",
        {
            "stale": {
                "device_auth_id": "dev-1",
                "user_code": "CODE-1",
                "interval": 5,
                "verification_uri": "https://auth.openai.com/codex/device",
                "requested_at": 0.1,
            }
        },
    )
    monkeypatch.setattr("server._CHATGPT_LOGIN_MAX_AGE_SECONDS", 1)

    resp = await asgi_client.post(
        "/settings/chatgpt/login/poll", json={"loginSessionId": "stale"}
    )
    assert resp.status_code == 410


async def test_chatgpt_logout_clears_tokens(asgi_client, monkeypatch):
    state = {"cleared": False, "artifacts": False}
    monkeypatch.setattr("server.clear_chatgpt_tokens", lambda: state.__setitem__("cleared", True))
    monkeypatch.setattr("server.clear_codex_auth_artifacts", lambda: state.__setitem__("artifacts", True))

    resp = await asgi_client.delete("/settings/chatgpt/auth")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert state["cleared"] is True
    assert state["artifacts"] is True
