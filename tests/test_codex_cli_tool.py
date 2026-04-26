"""Unit tests for ``kady_agent/tools/codex_cli.py``."""

from __future__ import annotations

import json
import types
from pathlib import Path

import kady_agent.tools.codex_cli as codex_cli


class _FakeProc:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def test_parse_exec_json_extracts_messages_tools_and_usage():
    raw = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thr_123"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_0",
                        "type": "agent_message",
                        "text": "Running pwd now.",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_1",
                        "type": "command_execution",
                        "command": "zsh -lc pwd",
                        "aggregated_output": "/tmp/demo\n",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_2",
                        "type": "agent_message",
                        "text": "OK",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 10,
                        "cached_input_tokens": 2,
                        "output_tokens": 3,
                    },
                }
            ),
        ]
    )

    parsed = codex_cli._parse_exec_json(raw)

    assert parsed["result"] == "Running pwd now.OK"
    assert parsed["tools_used"] == {"command_execution": 1}
    assert parsed["thread_id"] == "thr_123"
    assert parsed["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 3,
        "total_tokens": 13,
        "cached_prompt_tokens": 2,
    }


def test_build_selected_skill_prompt_prefix_mentions_exact_paths_and_linked_files(
    active_project,
):
    skill_dir = active_project.gemini_settings_dir / "skills" / "writing"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: writing\ndescription: Structured writing workflow\n---\n",
        encoding="utf-8",
    )
    (skill_dir / "references" / "checklist.md").write_text("checklist", encoding="utf-8")

    prefix = codex_cli._build_selected_skill_prompt_prefix(["writing"])

    assert "Before doing anything else, open and follow these skill files" in prefix
    assert "`.gemini/skills/writing/SKILL.md`" in prefix
    assert "`.gemini/skills/writing/references/checklist.md`" in prefix


async def test_delegate_task_executes_codex_and_records_cost_and_manifest(
    active_project, monkeypatch
):
    from kady_agent import manifest as manifest_module

    turn_id, _ = await manifest_module.open_turn(
        session_id="s1", user_text="p", model="chatgpt/gpt-5.4", expert_model="chatgpt/gpt-5.4"
    )
    state = {
        "_sessionId": "s1",
        "_turnId": turn_id,
        "_expertModel": "chatgpt/gpt-5.4",
        "_skills": ["writing"],
    }
    ctx = types.SimpleNamespace(state=state)

    monkeypatch.setattr(
        codex_cli,
        "resolve_chatgpt_runtime_credentials",
        lambda **kwargs: {
            "api_key": "chatgp...oken",
            "refresh_token": "chatgp...oken",
            "id_token": "chatgpt-id-token",
            "account_id": "acct_123",
            "last_refresh": "2026-04-22T22:19:48.691111Z",
        },
    )

    skill_dir = active_project.gemini_settings_dir / "skills" / "writing"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: writing\ndescription: Structured writing workflow\n---\n",
        encoding="utf-8",
    )
    (skill_dir / "references" / "checklist.md").write_text("checklist", encoding="utf-8")

    recorded_costs: list[dict] = []
    monkeypatch.setattr(
        codex_cli,
        "record_cost",
        lambda **kwargs: recorded_costs.append(kwargs) or "entry-1",
    )

    called: dict[str, object] = {}

    async def fake_exec(*args, **kwargs):
        called["args"] = args
        called["cwd"] = kwargs.get("cwd")
        called["env"] = kwargs.get("env")
        stream = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "thr_123"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_1",
                            "type": "command_execution",
                            "command": "zsh -lc pwd",
                            "aggregated_output": str(active_project.sandbox) + "\n",
                            "exit_code": 0,
                            "status": "completed",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_2",
                            "type": "agent_message",
                            "text": "OK",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 12,
                            "cached_input_tokens": 5,
                            "output_tokens": 7,
                        },
                    }
                ),
            ]
        ).encode()
        return _FakeProc(stream)

    monkeypatch.setattr(codex_cli.asyncio, "create_subprocess_exec", fake_exec)

    result = await codex_cli.delegate_task("analyze", tool_context=ctx)

    assert result["result"] == "OK"
    assert result["tools_used"] == {"command_execution": 1}
    assert called["args"][0] == "codex"
    assert "exec" in called["args"]
    assert "--json" in called["args"]
    assert "--skip-git-repo-check" in called["args"]
    assert "--dangerously-bypass-approvals-and-sandbox" in called["args"]
    model_idx = called["args"].index("-m")
    assert called["args"][model_idx + 1] == "gpt-5.4"
    exec_prompt = called["args"][-1]
    assert "MANDATORY SKILL LOADING" in exec_prompt
    assert "`.gemini/skills/writing/SKILL.md`" in exec_prompt
    assert "`.gemini/skills/writing/references/checklist.md`" in exec_prompt
    assert called["cwd"] == active_project.sandbox

    env = called["env"]
    codex_home = Path(env["CODEX_HOME"])
    assert not (codex_home / "auth.json").exists()
    assert env["KADY_PROJECT_ID"] == active_project.id
    agents_md = (active_project.sandbox / "AGENTS.md")
    assert agents_md.is_file()
    agents_text = agents_md.read_text(encoding="utf-8")
    assert "Start every task by scanning `.gemini/skills/`." in agents_text
    assert "`.gemini/skills/writing/SKILL.md`" in agents_text

    manifest = manifest_module.read_manifest("s1", turn_id)
    assert manifest is not None
    assert len(manifest["delegations"]) == 1
    assert manifest["delegations"][0]["id"] == "001"

    assert recorded_costs == [
        {
            "session_id": "s1",
            "turn_id": turn_id,
            "role": "expert",
            "model": "chatgpt/gpt-5.4",
            "usage_dict": {
                "prompt_tokens": 12,
                "completion_tokens": 7,
                "total_tokens": 19,
                "cached_prompt_tokens": 5,
            },
            "cost_usd": 0.0,
            "delegation_id": "001",
            "project_id": active_project.id,
        }
    ]
