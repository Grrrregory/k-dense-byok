# Architecture

This page explains how K-Dense BYOK runs on your computer. You do not need to read this to use the app - it is here if you are curious or troubleshooting.

![K-Dense BYOK Architecture](k-dense-byok-architecture.png)

## The three services

The `start.sh` script launches three local services that work together:

| Service | Port | What it does |
|---------|------|--------------|
| **Frontend** | 3000 | The web interface in your browser - chat, file browser, and file previews |
| **Backend** | 8000 | The "brain" - runs Kady, coordinates expert agents, manages your sandbox and files |
| **LiteLLM proxy** | 4000 | A translator that routes AI requests to the model you picked (via OpenRouter, Ollama, etc.) |

When you send a message:

1. The frontend passes it to the backend.
2. Kady (on the backend) decides whether to answer directly or delegate to an expert agent.
3. Any AI calls go through the LiteLLM proxy to the correct provider.
4. Responses stream back to your browser in real time.

## First-run setup

The first time you run `./start.sh`, it will automatically:

- Create a Python virtual environment in `.venv/`
- Install all Python dependencies
- Install Node.js dependencies for the frontend
- Install the Gemini CLI
- Download the scientific skills catalogue
- Run `uvx browser-use install` once to download a headless Chromium (used for browser automation)

Subsequent starts skip these steps via marker files and are much faster.

## Project layout

```
k-dense-byok/
├── start.sh              ← The one script that starts everything
├── server.py             ← Backend server
├── kady_agent/           ← Kady's brain: instructions, tools, and config
│   ├── env.example       ← Template for your API keys (copy to .env)
│   ├── .env              ← Your API keys (created from env.example)
│   ├── agent.py          ← Main agent definition
│   └── tools/            ← Tools Kady can use (web search, delegation, etc.)
├── web/                  ← Frontend (the UI you see in your browser)
├── docs/                 ← Extended documentation (this folder)
└── projects/             ← All user work, one subdirectory per named project
    ├── index.json        ← Project registry (names, tags, archived flag)
    └── default/          ← The "Default" project
        ├── project.json      ← Project metadata
        ├── sandbox/          ← Workspace for files and expert tasks
        ├── custom_mcps.json  ← Per-project custom MCP servers
        └── sessions.db       ← Chat history (SQLite, per project)
```

## A note on the expert model

The model you select in Kady's dropdown always applies to Kady (the main agent). When Kady delegates a task, the expert runner depends on the selected expert model:

- OpenRouter-hosted models (for example `openrouter/...`) run through the Gemini CLI expert runner via the local LiteLLM proxy.
- ChatGPT Pro-authenticated GPT-5.x models (for example `chatgpt/gpt-5.4`) run through a Codex CLI expert runner with isolated ChatGPT auth.
- local Ollama models (`ollama/...`) run through the Gemini CLI expert runner.

Both expert runners share the same sandbox, project-scoped MCP configuration, and provenance/manifest plumbing. The orchestrator decides when to delegate; the selected provider/runtime decides how the delegated expert executes.
