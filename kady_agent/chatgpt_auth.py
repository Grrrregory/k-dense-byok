from __future__ import annotations

import base64
import json
import os
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

try:
    import fcntl
except Exception:  # pragma: no cover - non-POSIX fallback
    fcntl = None

CHATGPT_AUTH_BASE = "https://auth.openai.com"
CHATGPT_OAUTH_TOKEN_URL = f"{CHATGPT_AUTH_BASE}/oauth/token"
CHATGPT_DEVICE_CODE_URL = f"{CHATGPT_AUTH_BASE}/api/accounts/deviceauth/usercode"
CHATGPT_DEVICE_TOKEN_URL = f"{CHATGPT_AUTH_BASE}/api/accounts/deviceauth/token"
CHATGPT_DEVICE_VERIFY_URL = f"{CHATGPT_AUTH_BASE}/codex/device"
CHATGPT_API_BASE = "https://chatgpt.com/backend-api/codex"
CHATGPT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_REFRESH_SKEW_SECONDS = 120
AUTH_PATH_ENV = "KADY_CHATGPT_AUTH_PATH"

_LOCK = threading.RLock()


class ChatGPTAuthError(RuntimeError):
    """Raised when ChatGPT authentication state is missing or invalid."""


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@contextmanager
def _auth_lock(path: Path | None = None):
    auth_path = path or get_auth_store_path()
    lock_handle = None
    with _LOCK:
        if fcntl is not None:
            lock_path = auth_path.with_name(f"{auth_path.name}.lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_handle = lock_path.open("a+", encoding="utf-8")
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if lock_handle is not None:
                try:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                finally:
                    lock_handle.close()


def get_auth_store_path() -> Path:
    override = os.getenv(AUTH_PATH_ENV, "").strip()
    if override:
        path = Path(override).expanduser()
    else:
        path = Path(__file__).resolve().parent / ".chatgpt" / "auth.json"
    _sync_litellm_chatgpt_env(path)
    return path


def _sync_litellm_chatgpt_env(path: Path | None = None) -> None:
    auth_path = path or get_auth_store_path()
    os.environ["CHATGPT_TOKEN_DIR"] = str(auth_path.parent)
    os.environ["CHATGPT_AUTH_FILE"] = auth_path.name


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        try:
            tmp_path.chmod(0o600)
        except OSError:
            pass
        tmp_path.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _decode_jwt_claims(token: str | None) -> dict[str, Any]:
    if not isinstance(token, str) or not token.strip():
        return {}
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded.decode("utf-8"))
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}



def _token_expiry(token: str | None) -> int | None:
    exp = _decode_jwt_claims(token).get("exp")
    if isinstance(exp, (int, float)):
        return int(exp)
    return None



def fetch_chatgpt_account_id(access_token: str | None) -> str | None:
    claims = _decode_jwt_claims(access_token)
    auth_claims = claims.get("https://api.openai.com/auth")
    if isinstance(auth_claims, dict):
        account_id = auth_claims.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id.strip():
            return account_id.strip()
    return None



def chatgpt_access_token_is_expiring(access_token: str | None, skew_seconds: int = DEFAULT_REFRESH_SKEW_SECONDS) -> bool:
    expiry = _token_expiry(access_token)
    if expiry is None:
        return True
    return time.time() >= (expiry - max(0, int(skew_seconds)))



def read_chatgpt_tokens() -> dict[str, Any] | None:
    path = get_auth_store_path()
    with _auth_lock(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError):
            return None
    return data if isinstance(data, dict) else None



def save_chatgpt_tokens(tokens: dict[str, str], last_refresh: str | None = None, account_id: str | None = None) -> None:
    access_token = str(tokens.get("access_token", "") or "").strip()
    refresh_token = str(tokens.get("refresh_token", "") or "").strip()
    id_token = str(tokens.get("id_token", "") or "").strip() or None
    if not access_token or not refresh_token:
        raise ChatGPTAuthError("ChatGPT auth requires access_token and refresh_token")

    path = get_auth_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    expires_at = _token_expiry(access_token)
    resolved_account_id = account_id or fetch_chatgpt_account_id(access_token)
    payload = {
        "version": 1,
        "provider": "chatgpt",
        "auth_mode": "chatgpt-pro",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "expires_at": expires_at,
        "account_id": resolved_account_id,
        "last_refresh": last_refresh or _iso_now(),
    }
    with _auth_lock(path):
        _atomic_write_json(path, payload)



def refresh_chatgpt_tokens(tokens: dict[str, str], timeout_seconds: float = 20.0) -> dict[str, str]:
    refresh_token = str(tokens.get("refresh_token", "") or "").strip()
    if not refresh_token:
        raise ChatGPTAuthError("ChatGPT auth is missing refresh_token")

    timeout = httpx.Timeout(max(5.0, float(timeout_seconds)))
    try:
        with httpx.Client(timeout=timeout, headers={"Accept": "application/json"}) as client:
            response = client.post(
                CHATGPT_OAUTH_TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CHATGPT_CLIENT_ID,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise ChatGPTAuthError(f"ChatGPT token refresh failed with status {exc.response.status_code}") from exc
    except Exception as exc:
        raise ChatGPTAuthError(f"ChatGPT token refresh failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise ChatGPTAuthError("ChatGPT token refresh returned invalid JSON")

    access_token = str(payload.get("access_token", "") or "").strip()
    next_refresh = str(payload.get("refresh_token", "") or refresh_token).strip()
    id_token = str(payload.get("id_token", "") or tokens.get("id_token", "") or "").strip() or None
    if not access_token:
        raise ChatGPTAuthError("ChatGPT token refresh response was missing access_token")

    updated = {
        "access_token": access_token,
        "refresh_token": next_refresh,
    }
    if id_token:
        updated["id_token"] = id_token
    save_chatgpt_tokens(updated)
    return updated



def resolve_chatgpt_runtime_credentials(*, force_refresh: bool = False, refresh_if_expiring: bool = True, refresh_skew_seconds: int = DEFAULT_REFRESH_SKEW_SECONDS) -> dict[str, Any]:
    data = read_chatgpt_tokens()
    if not data:
        raise ChatGPTAuthError("No ChatGPT credentials stored")

    access_token = str(data.get("access_token", "") or "").strip()
    refresh_token = str(data.get("refresh_token", "") or "").strip()
    id_token = str(data.get("id_token", "") or "").strip()
    if not access_token or not refresh_token:
        raise ChatGPTAuthError("Stored ChatGPT credentials are incomplete")

    should_refresh = bool(force_refresh)
    if not should_refresh and refresh_if_expiring:
        should_refresh = chatgpt_access_token_is_expiring(access_token, skew_seconds=refresh_skew_seconds)
    if should_refresh:
        refreshed = refresh_chatgpt_tokens(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                **({"id_token": id_token} if id_token else {}),
            }
        )
        access_token = refreshed["access_token"]
        refresh_token = refreshed["refresh_token"]
        id_token = str(refreshed.get("id_token", "") or "")
        data = read_chatgpt_tokens() or data

    return {
        "provider": "chatgpt",
        "base_url": CHATGPT_API_BASE,
        "api_key": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token or None,
        "account_id": data.get("account_id") or fetch_chatgpt_account_id(access_token),
        "last_refresh": data.get("last_refresh"),
        "auth_mode": "chatgpt-pro",
        "source": "kady-auth-store",
    }



def request_chatgpt_device_code(timeout_seconds: float = 15.0) -> dict[str, Any]:
    timeout = httpx.Timeout(max(5.0, float(timeout_seconds)))
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                CHATGPT_DEVICE_CODE_URL,
                json={"client_id": CHATGPT_CLIENT_ID},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise ChatGPTAuthError(f"ChatGPT device-code request failed with status {exc.response.status_code}") from exc
    except Exception as exc:
        raise ChatGPTAuthError(f"ChatGPT device-code request failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise ChatGPTAuthError("ChatGPT device-code response was invalid")
    device_auth_id = str(payload.get("device_auth_id", "") or "").strip()
    user_code = str(payload.get("user_code", "") or payload.get("usercode", "") or "").strip()
    interval = int(payload.get("interval", 5) or 5)
    if not device_auth_id or not user_code:
        raise ChatGPTAuthError("ChatGPT device-code response was missing required fields")
    return {
        "device_auth_id": device_auth_id,
        "user_code": user_code,
        "interval": interval,
        "verification_uri": CHATGPT_DEVICE_VERIFY_URL,
        "requested_at": time.time(),
    }



def poll_chatgpt_device_code(device_auth_id: str, user_code: str, timeout_seconds: float = 15.0) -> dict[str, Any] | None:
    timeout = httpx.Timeout(max(5.0, float(timeout_seconds)))
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                CHATGPT_DEVICE_TOKEN_URL,
                json={"device_auth_id": device_auth_id, "user_code": user_code},
                headers={"Content-Type": "application/json"},
            )
    except Exception as exc:
        raise ChatGPTAuthError(f"ChatGPT device-code polling failed: {exc}") from exc

    if response.status_code in (403, 404):
        return None
    try:
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise ChatGPTAuthError(f"ChatGPT device-code polling failed with status {exc.response.status_code}") from exc
    except Exception as exc:
        raise ChatGPTAuthError(f"ChatGPT device-code polling returned invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ChatGPTAuthError("ChatGPT device-code polling response was invalid")
    auth_code = str(payload.get("authorization_code", "") or "").strip()
    code_verifier = str(payload.get("code_verifier", "") or "").strip()
    if not auth_code or not code_verifier:
        raise ChatGPTAuthError("ChatGPT device-code polling response was missing authorization fields")
    return {
        "authorization_code": auth_code,
        "code_verifier": code_verifier,
    }



def exchange_chatgpt_authorization_code(authorization_code: str, code_verifier: str, timeout_seconds: float = 15.0) -> dict[str, str]:
    timeout = httpx.Timeout(max(5.0, float(timeout_seconds)))
    redirect_uri = f"{CHATGPT_AUTH_BASE}/deviceauth/callback"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                CHATGPT_OAUTH_TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": redirect_uri,
                    "client_id": CHATGPT_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise ChatGPTAuthError(f"ChatGPT token exchange failed with status {exc.response.status_code}") from exc
    except Exception as exc:
        raise ChatGPTAuthError(f"ChatGPT token exchange failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise ChatGPTAuthError("ChatGPT token exchange returned invalid JSON")
    access_token = str(payload.get("access_token", "") or "").strip()
    refresh_token = str(payload.get("refresh_token", "") or "").strip()
    id_token = str(payload.get("id_token", "") or "").strip() or None
    if not access_token or not refresh_token:
        raise ChatGPTAuthError("ChatGPT token exchange response was missing required fields")
    tokens = {"access_token": access_token, "refresh_token": refresh_token}
    if id_token:
        tokens["id_token"] = id_token
    return tokens



def run_chatgpt_device_code_login(*, timeout_seconds: float = 15.0, max_wait_seconds: float = 15 * 60) -> dict[str, Any]:
    pending = request_chatgpt_device_code(timeout_seconds=timeout_seconds)
    deadline = time.time() + max_wait_seconds
    interval = max(1, int(pending.get("interval", 5) or 5))
    while time.time() < deadline:
        time.sleep(interval)
        polled = poll_chatgpt_device_code(
            pending["device_auth_id"], pending["user_code"], timeout_seconds=timeout_seconds
        )
        if not polled:
            continue
        tokens = exchange_chatgpt_authorization_code(
            polled["authorization_code"], polled["code_verifier"], timeout_seconds=timeout_seconds
        )
        save_chatgpt_tokens(tokens)
        return {
            "tokens": tokens,
            "verification_uri": pending["verification_uri"],
            "user_code": pending["user_code"],
            "last_refresh": read_chatgpt_tokens().get("last_refresh") if read_chatgpt_tokens() else None,
        }
    raise ChatGPTAuthError("ChatGPT device-code login timed out")


def _install_litellm_chatgpt_auth_patch() -> None:
    """Patch LiteLLM's ChatGPT authenticator to use locked, atomic auth I/O."""
    try:
        from litellm.llms.chatgpt.authenticator import Authenticator
    except Exception:
        return

    if getattr(Authenticator, "_kady_atomic_patch_installed", False):
        return

    def _patched_ensure_token_dir(self) -> None:
        path = Path(self.auth_file)
        _sync_litellm_chatgpt_env(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    def _patched_read_auth_file(self):
        path = Path(self.auth_file)
        _sync_litellm_chatgpt_env(path)
        with _auth_lock(path):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                return None
        return data if isinstance(data, dict) else None

    def _patched_write_auth_file(self, data) -> None:
        path = Path(self.auth_file)
        _sync_litellm_chatgpt_env(path)
        with _auth_lock(path):
            _atomic_write_json(path, data if isinstance(data, dict) else {})

    Authenticator._ensure_token_dir = _patched_ensure_token_dir
    Authenticator._read_auth_file = _patched_read_auth_file
    Authenticator._write_auth_file = _patched_write_auth_file
    Authenticator._kady_atomic_patch_installed = True


def clear_chatgpt_tokens() -> None:
    path = get_auth_store_path()
    with _auth_lock(path):
        try:
            path.unlink()
        except FileNotFoundError:
            return



def clear_codex_auth_artifacts(repo_root: Path | None = None) -> int:
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    removed = 0
    for codex_root in root.glob("projects/*/sandbox/.kady/codex-home"):
        try:
            if not codex_root.exists():
                continue
            shutil.rmtree(codex_root)
            removed += 1
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return removed



def get_chatgpt_auth_status() -> dict[str, Any]:
    data = read_chatgpt_tokens()
    if not data:
        return {
            "authenticated": False,
            "accountId": None,
            "lastRefresh": None,
            "error": None,
        }
    access_token = str(data.get("access_token", "") or "").strip()
    refresh_token = str(data.get("refresh_token", "") or "").strip()
    authenticated = bool(access_token and refresh_token)
    error = None
    if authenticated and chatgpt_access_token_is_expiring(access_token, skew_seconds=0):
        error = "stored_access_token_expired"
    return {
        "authenticated": authenticated,
        "accountId": data.get("account_id"),
        "lastRefresh": data.get("last_refresh"),
        "error": error,
    }


_install_litellm_chatgpt_auth_patch()
