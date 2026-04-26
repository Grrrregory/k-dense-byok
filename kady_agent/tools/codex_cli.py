from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv
from google.adk.tools.tool_context import ToolContext

from ..chatgpt_auth import resolve_chatgpt_runtime_credentials
from ..cost_ledger import check_project_budget, record_cost
from ..gemini_settings import build_default_settings, load_custom_mcps
from ..manifest import attach_delegation, session_seed
from ..projects import active_paths, get_project
from ..utils import load_instructions

REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / "kady_agent" / ".env")

_EXCLUDED_DELIVERABLE_DIRS = {".git", ".gemini", ".kady", ".venv", "__pycache__"}
_SKILL_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_SKILL_LINK_DIRS = ("references", "templates", "scripts", "assets")


def _resolve_cwd(paths, working_directory: Optional[str]) -> Path:
    if working_directory is None or not working_directory.strip():
        cwd = paths.sandbox
    else:
        wd = Path(working_directory)
        if not wd.is_absolute():
            cwd = (paths.sandbox / wd).resolve()
        else:
            cwd = wd.resolve()
        if not cwd.is_relative_to(paths.sandbox):
            cwd = paths.sandbox
    cwd.mkdir(parents=True, exist_ok=True)
    return cwd


def _snapshot_workspace(cwd: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for root, dirs, files in os.walk(cwd):
        root_path = Path(root)
        dirs[:] = [
            name
            for name in dirs
            if name not in _EXCLUDED_DELIVERABLE_DIRS
            and not name.startswith(".codex")
        ]
        for name in files:
            if name.startswith(".codex"):
                continue
            path = root_path / name
            try:
                rel = str(path.relative_to(cwd))
                stat = path.stat()
            except OSError:
                continue
            snapshot[rel] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def _collect_deliverables(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    changed: list[str] = []
    for rel, meta in after.items():
        if rel.startswith(".kady/") or rel.startswith(".gemini/") or rel.startswith(".venv/"):
            continue
        if before.get(rel) != meta:
            changed.append(rel)
    return sorted(changed)


def _discover_skill_entries() -> list[dict[str, Any]]:
    sandbox = active_paths().sandbox
    skills_root = active_paths().gemini_settings_dir / "skills"
    if not skills_root.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for child in sorted(skills_root.iterdir(), key=lambda p: p.name.lower()):
        skill_file = child / "SKILL.md"
        if not child.is_dir() or not skill_file.is_file():
            continue

        name = child.name
        description = ""
        try:
            text = skill_file.read_text(encoding="utf-8", errors="replace")
            match = _SKILL_FRONTMATTER_RE.match(text)
            if match:
                meta = yaml.safe_load(match.group(1)) or {}
                if isinstance(meta, dict):
                    name = str(meta.get("name") or child.name)
                    description = str(meta.get("description") or "")
        except Exception:
            pass

        linked_files: list[str] = []
        for dirname in _SKILL_LINK_DIRS:
            linked_dir = child / dirname
            if not linked_dir.is_dir():
                continue
            for linked in sorted(p for p in linked_dir.rglob("*") if p.is_file()):
                try:
                    linked_files.append(str(linked.relative_to(sandbox)))
                except ValueError:
                    linked_files.append(str(linked))

        try:
            skill_path = str(skill_file.relative_to(sandbox))
        except ValueError:
            skill_path = str(skill_file)

        entries.append(
            {
                "id": child.name,
                "name": name,
                "description": description,
                "skill_path": skill_path,
                "linked_files": linked_files,
            }
        )
    return entries


def _resolve_selected_skills(selected_skills: list[str] | None) -> list[dict[str, Any]]:
    if not selected_skills:
        return []
    wanted = [str(item).strip() for item in selected_skills if str(item).strip()]
    if not wanted:
        return []

    entries = _discover_skill_entries()
    by_key: dict[str, dict[str, Any]] = {}
    for entry in entries:
        by_key[entry["id"].casefold()] = entry
        by_key[entry["name"].casefold()] = entry

    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in wanted:
        entry = by_key.get(item.casefold())
        if not entry:
            continue
        dedupe_key = entry["id"].casefold()
        if dedupe_key in seen:
            continue
        resolved.append(entry)
        seen.add(dedupe_key)
    return resolved


def _build_selected_skill_prompt_prefix(selected_skills: list[str] | None) -> str:
    resolved = _resolve_selected_skills(selected_skills)
    if not resolved:
        return ""

    lines = [
        "MANDATORY SKILL LOADING",
        "",
        "Before doing anything else, open and follow these skill files exactly:",
    ]
    linked_files: list[str] = []
    for entry in resolved:
        lines.append(
            f"- `{entry['skill_path']}` — skill `{entry['name']}`"
        )
        linked_files.extend(entry.get("linked_files") or [])

    if linked_files:
        lines.append("")
        lines.append("Also inspect these linked helper files before continuing:")
        for rel in linked_files:
            lines.append(f"- `{rel}`")

    lines.extend(
        [
            "",
            "Do not approximate these skills from memory. Read the actual files from disk and follow them.",
        ]
    )
    return "\n".join(lines)


def _format_codex_skill_reference(skills: list[dict[str, Any]]) -> str:
    if not skills:
        return ""
    lines = [
        "",
        "## Available K-Dense expert skills",
        "",
        "Start every task by scanning `.gemini/skills/`. If the prompt names a skill, open that exact `SKILL.md` before doing anything else. If a skill has helper files under `references/`, `templates/`, `scripts/`, or `assets/`, open those too.",
        "",
        "| Skill name | Skill file | Description |",
        "|---|---|---|",
    ]
    for skill in skills:
        desc = (skill.get("description") or "").replace("\n", " ").strip()
        if len(desc) > 160:
            desc = desc[:157] + "..."
        lines.append(
            f"| `{skill.get('name')}` | `{skill.get('skill_path')}` | {desc} |"
        )
    lines.append("")
    return "\n".join(lines)


def _ensure_agents_md(cwd: Path) -> Path:
    content = load_instructions("codex_cli") + _format_codex_skill_reference(
        _discover_skill_entries()
    )
    path = cwd / "AGENTS.md"
    if not path.exists() or path.read_text(encoding="utf-8", errors="replace") != content:
        path.write_text(content, encoding="utf-8")
    return path


def _build_exec_prompt(prompt: str, selected_skills: list[str] | None) -> str:
    prefix = _build_selected_skill_prompt_prefix(selected_skills)
    if not prefix:
        return prompt
    return f"{prefix}\n\n{prompt}"


def _codex_model_name(model_name: str | None) -> str:
    if isinstance(model_name, str) and model_name.startswith("chatgpt/"):
        return model_name.split("/", 1)[1]
    if isinstance(model_name, str) and model_name.strip():
        return model_name.strip()
    return "gpt-5.4"


def _write_codex_auth(codex_home: Path) -> None:
    creds = resolve_chatgpt_runtime_credentials(force_refresh=True)
    payload = {
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": creds.get("id_token"),
            "access_token": creds["api_key"],
            "refresh_token": creds["refresh_token"],
            "account_id": creds.get("account_id"),
        },
        "last_refresh": creds.get("last_refresh"),
    }
    codex_home.mkdir(parents=True, exist_ok=True)
    try:
        codex_home.chmod(0o700)
    except OSError:
        pass
    auth_path = codex_home / "auth.json"
    auth_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        auth_path.chmod(0o600)
    except OSError:
        pass


def _remove_codex_auth(codex_home: Path) -> None:
    try:
        (codex_home / "auth.json").unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _toml_quote(value: str) -> str:
    return json.dumps(value)


def _render_toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_render_toml_scalar(item) for item in value) + "]"
    if value is None:
        return '""'
    return _toml_quote(str(value))


def _append_table(lines: list[str], table_name: str, payload: dict[str, Any]) -> None:
    scalars: dict[str, Any] = {}
    nested: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            nested[key] = value
        elif value is not None:
            scalars[key] = value
    lines.append(f"[{table_name}]")
    for key, value in scalars.items():
        lines.append(f"{key} = {_render_toml_scalar(value)}")
    lines.append("")
    for key, value in nested.items():
        _append_table(lines, f"{table_name}.{key}", value)


def _codex_mcp_config() -> dict[str, dict[str, Any]]:
    settings = build_default_settings()
    settings["mcpServers"].update(load_custom_mcps())
    config: dict[str, dict[str, Any]] = {}
    for name, spec in settings.get("mcpServers", {}).items():
        if not isinstance(spec, dict):
            continue
        if spec.get("command"):
            entry: dict[str, Any] = {
                "command": spec["command"],
                "startup_timeout_sec": int(spec.get("startup_timeout_sec") or 30),
                "tool_timeout_sec": int(spec.get("tool_timeout_sec") or 300),
            }
            if spec.get("args"):
                entry["args"] = list(spec["args"])
            if spec.get("env"):
                entry["env"] = {str(k): str(v) for k, v in spec["env"].items()}
            config[name] = entry
            continue
        if spec.get("httpUrl"):
            entry = {
                "url": str(spec["httpUrl"]),
                "startup_timeout_sec": int(spec.get("startup_timeout_sec") or 30),
                "tool_timeout_sec": int(spec.get("tool_timeout_sec") or 300),
            }
            headers = spec.get("headers")
            if isinstance(headers, dict) and headers:
                entry["http_headers"] = {str(k): str(v) for k, v in headers.items()}
            config[name] = entry
    return config


def _write_codex_config(codex_home: Path, cwd: Path, model_name: str) -> None:
    lines = [
        f"model = {_toml_quote(model_name)}",
        'model_reasoning_effort = "high"',
        "",
        "[shell_environment_policy]",
        'inherit = "all"',
        "",
        f"[projects.{_toml_quote(str(cwd))}]",
        'trust_level = "trusted"',
        "",
    ]
    for name, spec in _codex_mcp_config().items():
        _append_table(lines, f"mcp_servers.{name}", spec)
    (codex_home / "config.toml").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _parse_exec_json(raw: str) -> dict[str, Any]:
    response_parts: list[str] = []
    tools_used: dict[str, int] = {}
    usage: dict[str, int] | None = None
    thread_id: str | None = None
    error_message: str | None = None

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type")
        if etype == "thread.started":
            tid = event.get("thread_id")
            if isinstance(tid, str) and tid:
                thread_id = tid
        elif etype == "item.completed":
            item = event.get("item") or {}
            item_type = item.get("type")
            if item_type == "agent_message":
                text = item.get("text")
                if isinstance(text, str) and text:
                    response_parts.append(text)
            elif isinstance(item_type, str) and item_type:
                tools_used[item_type] = tools_used.get(item_type, 0) + 1
        elif etype == "turn.completed":
            raw_usage = event.get("usage") or {}
            if isinstance(raw_usage, dict):
                prompt_tokens = int(raw_usage.get("input_tokens") or 0)
                completion_tokens = int(raw_usage.get("output_tokens") or 0)
                cached_prompt_tokens = int(raw_usage.get("cached_input_tokens") or 0)
                usage = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "cached_prompt_tokens": cached_prompt_tokens,
                }
        elif etype == "turn.failed":
            error = event.get("error") or {}
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str) and message:
                    error_message = message
        elif etype == "error" and not error_message:
            message = event.get("message")
            if isinstance(message, str) and message:
                error_message = message

    return {
        "result": "".join(response_parts),
        "skills_used": [],
        "tools_used": tools_used,
        "usage": usage,
        "thread_id": thread_id,
        "error_message": error_message,
    }


def _freeze_env_lock(cwd: Path, env: dict[str, str], delegation_id: str | None) -> str | None:
    if not delegation_id:
        return None
    expert_dir = cwd / ".kady" / "expert" / delegation_id
    expert_dir.mkdir(parents=True, exist_ok=True)
    target = expert_dir / "env.lock"
    try:
        result = subprocess.run(
            ["uv", "pip", "freeze"],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    target.write_text(result.stdout, encoding="utf-8")
    return result.stdout


def _write_deliverables(cwd: Path, delegation_id: str | None, deliverables: list[str]) -> None:
    if not delegation_id:
        return
    expert_dir = cwd / ".kady" / "expert" / delegation_id
    expert_dir.mkdir(parents=True, exist_ok=True)
    (expert_dir / "deliverables.json").write_text(
        json.dumps(deliverables, indent=2) + "\n",
        encoding="utf-8",
    )


async def delegate_task(
    prompt: str,
    working_directory: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
) -> dict:
    env = os.environ.copy()
    paths = active_paths()

    project_meta = get_project(paths.id)
    if project_meta is not None and project_meta.spendLimitUsd is not None:
        budget = check_project_budget(paths.id, project_meta.spendLimitUsd)
        if budget["state"] == "exceeded":
            limit = float(budget["limitUsd"] or 0.0)
            spent = float(budget["totalUsd"] or 0.0)
            return {
                "result": (
                    f"Delegation blocked: project '{project_meta.name}' has "
                    f"reached its spend limit (${spent:.2f} / ${limit:.2f}). "
                    f"Raise the limit in the project settings and retry."
                ),
                "skills_used": [],
                "tools_used": {},
                "budgetBlocked": True,
                "projectId": paths.id,
                "totalUsd": spent,
                "limitUsd": limit,
            }

    cwd = _resolve_cwd(paths, working_directory)
    _ensure_agents_md(cwd)
    before_snapshot = _snapshot_workspace(cwd)

    state = tool_context.state if tool_context is not None else None
    turn_id: Optional[str] = None
    session_id: Optional[str] = None
    delegation_id: Optional[str] = None
    selected_model: Optional[str] = None
    selected_skills: list[str] = []
    if state is not None:
        turn_id = state.get("_turnId")
        session_id = state.get("_sessionId")
        raw_model = state.get("_expertModel") or state.get("_model")
        if isinstance(raw_model, str) and raw_model.strip():
            selected_model = raw_model.strip()
        raw_skills = state.get("_skills")
        if isinstance(raw_skills, list):
            selected_skills = [
                str(item).strip() for item in raw_skills if str(item).strip()
            ]

    if session_id and turn_id:
        env["KADY_SEED"] = session_seed(session_id)
        env["KADY_TURN_ID"] = turn_id
        env["KADY_SESSION_ID"] = session_id
        counter_key = f"_delegation_counter_{turn_id}"
        prev = state.get(counter_key) or 0
        delegation_id = f"{int(prev) + 1:03d}"
        state[counter_key] = int(prev) + 1
        env["KADY_DELEGATION_ID"] = delegation_id

    env["KADY_PROJECT_ID"] = paths.id
    if delegation_id:
        env.setdefault("KADY_EXPERT_ID", delegation_id)
        env.setdefault("KADY_EXPERT_LABEL", f"Expert #{delegation_id}")

    sandbox_venv = cwd / ".venv"
    if sandbox_venv.is_dir():
        venv_bin = str(sandbox_venv / "bin")
        env["VIRTUAL_ENV"] = str(sandbox_venv)
        path_parts = env.get("PATH", "").split(os.pathsep)
        old_venv = os.environ.get("VIRTUAL_ENV")
        if old_venv:
            old_bin = os.path.join(old_venv, "bin")
            path_parts = [p for p in path_parts if p != old_bin]
        env["PATH"] = os.pathsep.join([venv_bin] + path_parts)

    codex_home = paths.kady_dir / "codex-home" / (delegation_id or "adhoc")
    try:
        _write_codex_auth(codex_home)
        model_name = _codex_model_name(selected_model)
        _write_codex_config(codex_home, cwd, model_name)
        env["CODEX_HOME"] = str(codex_home)
        exec_prompt = _build_exec_prompt(prompt, selected_skills)

        cli_args = [
            "codex",
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            "-C",
            str(cwd),
            "-m",
            model_name,
            exec_prompt,
        ]

        started_at = time.time()
        proc = await asyncio.create_subprocess_exec(
            *cli_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
    finally:
        _remove_codex_auth(codex_home)
    duration_ms = int((time.time() - started_at) * 1000)

    raw = stdout_bytes.decode(errors="replace")
    result = _parse_exec_json(raw)
    if proc.returncode != 0:
        message = result.get("error_message") or stderr_bytes.decode(errors="replace").strip() or "codex command failed"
        raise RuntimeError(message)

    after_snapshot = _snapshot_workspace(cwd)
    deliverables = _collect_deliverables(before_snapshot, after_snapshot)
    _write_deliverables(cwd, delegation_id, deliverables)

    env_lock: str | None = None
    if result["tools_used"]:
        env_lock = _freeze_env_lock(cwd, env, delegation_id)

    if session_id and turn_id and delegation_id and result.get("usage"):
        record_cost(
            session_id=session_id,
            turn_id=turn_id,
            role="expert",
            model=selected_model or f"chatgpt/{model_name}",
            usage_dict=result["usage"],
            cost_usd=0.0,
            delegation_id=delegation_id,
            project_id=paths.id,
        )

    if session_id and turn_id and delegation_id:
        try:
            await attach_delegation(
                session_id=session_id,
                turn_id=turn_id,
                delegation_id=delegation_id,
                prompt=exec_prompt,
                cwd=str(cwd.relative_to(REPO_ROOT)) if cwd.is_relative_to(REPO_ROOT) else str(cwd),
                result=result,
                duration_ms=duration_ms,
                stdout=raw,
                env_lock=env_lock,
                deliverables=deliverables,
            )
        except Exception:
            pass

    return result
