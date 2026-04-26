from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import httpx
import pytest


CHATGPT_AUTH_ENV = "KADY_CHATGPT_AUTH_PATH"


def _jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).rstrip(b"=").decode()
    return f"{header}.{body}.sig"


@pytest.fixture
def auth_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".chatgpt" / "auth.json"
    monkeypatch.setenv(CHATGPT_AUTH_ENV, str(path))
    return path


def test_get_auth_store_path_uses_env_override(auth_path: Path):
    from kady_agent.chatgpt_auth import get_auth_store_path

    assert get_auth_store_path() == auth_path


def test_read_chatgpt_tokens_returns_none_when_missing(auth_path: Path):
    from kady_agent.chatgpt_auth import read_chatgpt_tokens

    assert read_chatgpt_tokens() is None


def test_save_and_read_chatgpt_tokens_roundtrip(auth_path: Path):
    from kady_agent.chatgpt_auth import read_chatgpt_tokens, save_chatgpt_tokens

    access_token = _jwt(
        {
            "exp": int(time.time()) + 3600,
            "https://api.openai.com/auth": {"chatgpt_account_id": "acct_123"},
        }
    )
    save_chatgpt_tokens(
        {
            "access_token": access_token,
            "refresh_token": "refresh-1",
            "id_token": _jwt({"exp": int(time.time()) + 3600}),
        },
        last_refresh="2026-04-22T01:00:00Z",
    )

    data = read_chatgpt_tokens()
    assert data is not None
    assert data["version"] == 1
    assert data["provider"] == "chatgpt"
    assert data["auth_mode"] == "chatgpt-pro"
    assert data["access_token"] == access_token
    assert data["refresh_token"] == "refresh-1"
    assert data["account_id"] == "acct_123"
    assert isinstance(data["expires_at"], int)
    assert data["last_refresh"] == "2026-04-22T01:00:00Z"


def test_fetch_chatgpt_account_id_extracts_claim():
    from kady_agent.chatgpt_auth import fetch_chatgpt_account_id

    token = _jwt(
        {
            "exp": int(time.time()) + 3600,
            "https://api.openai.com/auth": {"chatgpt_account_id": "acct_abc"},
        }
    )
    assert fetch_chatgpt_account_id(token) == "acct_abc"


def test_chatgpt_access_token_is_expiring(auth_path: Path):
    from kady_agent.chatgpt_auth import chatgpt_access_token_is_expiring

    fresh = _jwt({"exp": int(time.time()) + 3600})
    stale = _jwt({"exp": int(time.time()) - 5})

    assert chatgpt_access_token_is_expiring(fresh, skew_seconds=60) is False
    assert chatgpt_access_token_is_expiring(stale, skew_seconds=60) is True


def test_resolve_chatgpt_runtime_credentials_returns_access_token(auth_path: Path):
    from kady_agent.chatgpt_auth import resolve_chatgpt_runtime_credentials, save_chatgpt_tokens

    access_token = _jwt({"exp": int(time.time()) + 3600})
    save_chatgpt_tokens({"access_token": access_token, "refresh_token": "refresh-1"})

    creds = resolve_chatgpt_runtime_credentials()
    assert creds["provider"] == "chatgpt"
    assert creds["base_url"] == "https://chatgpt.com/backend-api/codex"
    assert creds["api_key"] == access_token
    assert creds["auth_mode"] == "chatgpt-pro"


def test_resolve_chatgpt_runtime_credentials_refreshes_expiring_token(
    auth_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from kady_agent.chatgpt_auth import resolve_chatgpt_runtime_credentials, save_chatgpt_tokens

    expired_access = _jwt({"exp": int(time.time()) - 5})
    refreshed_access = _jwt({"exp": int(time.time()) + 7200})
    save_chatgpt_tokens(
        {
            "access_token": expired_access,
            "refresh_token": "refresh-1",
            "id_token": _jwt({"exp": int(time.time()) + 7200}),
        }
    )

    monkeypatch.setattr(
        "kady_agent.chatgpt_auth.refresh_chatgpt_tokens",
        lambda tokens, timeout_seconds=20.0: {
            "access_token": refreshed_access,
            "refresh_token": tokens["refresh_token"],
            "id_token": _jwt({"exp": int(time.time()) + 7200}),
        },
    )

    creds = resolve_chatgpt_runtime_credentials()
    assert creds["api_key"] == refreshed_access


def test_refresh_chatgpt_tokens_updates_store(auth_path: Path, monkeypatch: pytest.MonkeyPatch):
    from kady_agent.chatgpt_auth import read_chatgpt_tokens, refresh_chatgpt_tokens, save_chatgpt_tokens

    old_access = _jwt({"exp": int(time.time()) - 5})
    new_access = _jwt(
        {
            "exp": int(time.time()) + 7200,
            "https://api.openai.com/auth": {"chatgpt_account_id": "acct_new"},
        }
    )
    new_id = _jwt({"exp": int(time.time()) + 7200})
    save_chatgpt_tokens({"access_token": old_access, "refresh_token": "refresh-1"})

    class _MockResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "access_token": new_access,
                "refresh_token": "refresh-2",
                "id_token": new_id,
            }

    class _MockClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, headers=None, data=None):
            assert url == "https://auth.openai.com/oauth/token"
            assert data["grant_type"] == "refresh_token"
            assert data["refresh_token"] == "refresh-1"
            return _MockResponse()

    monkeypatch.setattr("kady_agent.chatgpt_auth.httpx.Client", lambda *a, **kw: _MockClient())

    refreshed = refresh_chatgpt_tokens({"access_token": old_access, "refresh_token": "refresh-1"})
    assert refreshed["access_token"] == new_access
    assert refreshed["refresh_token"] == "refresh-2"
    assert refreshed["id_token"] == new_id

    stored = read_chatgpt_tokens()
    assert stored is not None
    assert stored["access_token"] == new_access
    assert stored["refresh_token"] == "refresh-2"
    assert stored["account_id"] == "acct_new"


def test_save_chatgpt_tokens_writes_atomically(auth_path: Path, monkeypatch: pytest.MonkeyPatch):
    from kady_agent.chatgpt_auth import save_chatgpt_tokens

    calls: list[tuple[str, str]] = []
    original_replace = Path.replace

    def _record_replace(self: Path, target: Path):
        calls.append((str(self), str(target)))
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", _record_replace)

    save_chatgpt_tokens(
        {
            "access_token": _jwt({"exp": int(time.time()) + 3600}),
            "refresh_token": "refresh-1",
        }
    )

    assert calls, "save_chatgpt_tokens should atomically replace the auth file"
    assert calls[-1][1] == str(auth_path)


def test_request_chatgpt_device_code_parses_response(monkeypatch: pytest.MonkeyPatch, auth_path: Path):
    from kady_agent.chatgpt_auth import request_chatgpt_device_code

    class _MockResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "device_auth_id": "dev-123",
                "user_code": "ABCD-1234",
                "interval": 7,
            }

    class _MockClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None, headers=None):
            assert url == "https://auth.openai.com/api/accounts/deviceauth/usercode"
            assert json["client_id"]
            return _MockResponse()

    monkeypatch.setattr("kady_agent.chatgpt_auth.httpx.Client", lambda *a, **kw: _MockClient())

    pending = request_chatgpt_device_code()
    assert pending["device_auth_id"] == "dev-123"
    assert pending["user_code"] == "ABCD-1234"
    assert pending["interval"] == 7
    assert pending["verification_uri"] == "https://auth.openai.com/codex/device"


def test_refresh_chatgpt_tokens_raises_on_non_200(auth_path: Path, monkeypatch: pytest.MonkeyPatch):
    from kady_agent.chatgpt_auth import ChatGPTAuthError, refresh_chatgpt_tokens

    request = httpx.Request("POST", "https://auth.openai.com/oauth/token")

    class _MockClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, headers=None, data=None):
            response = httpx.Response(401, request=request, json={"error": "invalid_grant"})
            raise httpx.HTTPStatusError("boom", request=request, response=response)

    monkeypatch.setattr("kady_agent.chatgpt_auth.httpx.Client", lambda *a, **kw: _MockClient())

    with pytest.raises(ChatGPTAuthError):
        refresh_chatgpt_tokens({"access_token": "bad", "refresh_token": "bad"})
