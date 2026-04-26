from __future__ import annotations

from typing import Any

import httpx

from .chatgpt_auth import resolve_chatgpt_runtime_credentials

CHATGPT_MODELS_URL = "https://chatgpt.com/backend-api/codex/models?client_version=1.0.0"
DEFAULT_CHATGPT_MODELS = [
    "gpt-5.4-mini",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.2-codex",
]


def _fetch_models_from_api(access_token: str, timeout_seconds: float = 10.0) -> list[dict[str, Any]]:
    timeout = httpx.Timeout(max(5.0, float(timeout_seconds)))
    with httpx.Client(timeout=timeout) as client:
        response = client.get(
            CHATGPT_MODELS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        return []
    models = payload.get("models")
    return models if isinstance(models, list) else []



def get_chatgpt_model_ids(access_token: str | None = None, *, allow_fallback: bool = True) -> list[str]:
    ordered: list[str] = []
    try:
        if access_token:
            entries = _fetch_models_from_api(access_token)
            sortable: list[tuple[int, str]] = []
            for item in entries:
                if not isinstance(item, dict):
                    continue
                slug = item.get("slug")
                if not isinstance(slug, str) or not slug.strip():
                    continue
                if item.get("supported_in_api") is False:
                    continue
                visibility = str(item.get("visibility", "") or "").strip().lower()
                if visibility in {"hidden", "hide"}:
                    continue
                priority = item.get("priority")
                rank = int(priority) if isinstance(priority, (int, float)) else 10_000
                sortable.append((rank, slug.strip()))
            sortable.sort(key=lambda item: (item[0], item[1]))
            for _, slug in sortable:
                if slug not in ordered:
                    ordered.append(slug)
    except Exception:
        if not allow_fallback:
            raise
        ordered = []

    if not ordered and allow_fallback:
        ordered.extend(DEFAULT_CHATGPT_MODELS)

    return ordered



def _model_label(model_id: str) -> str:
    label = model_id.replace("-", " ").upper()
    label = label.replace("GPT ", "GPT-")
    label = label.replace("CODEX", "Codex")
    label = label.replace("MINI", "Mini")
    return label



def _model_tier(model_id: str) -> str:
    lower = model_id.lower()
    if "mini" in lower:
        return "mid"
    if "nano" in lower:
        return "budget"
    if model_id.startswith("gpt-5.4"):
        return "high"
    return "high"



def build_chatgpt_model_entries(model_ids: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for model_id in model_ids:
        model_id = str(model_id or "").strip()
        if not model_id:
            continue
        lower = model_id.lower()
        modality = "text+image->text" if lower.startswith("gpt-") else "text->text"
        entries.append(
            {
                "id": f"chatgpt/{model_id}",
                "label": _model_label(model_id),
                "provider": "ChatGPT Pro",
                "tier": _model_tier(model_id),
                "context_length": 0,
                "pricing": {"prompt": 0.0, "completion": 0.0},
                "modality": modality,
                "description": "Authenticated via ChatGPT Pro account.",
            }
        )
    return entries



def list_chatgpt_models(*, strict: bool = False) -> list[dict[str, Any]]:
    creds = resolve_chatgpt_runtime_credentials()
    model_ids = get_chatgpt_model_ids(access_token=creds["api_key"], allow_fallback=not strict)
    return build_chatgpt_model_entries(model_ids)
