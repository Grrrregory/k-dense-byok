# Maintaining the ChatGPT Pro integration fork

This repository is now set up to track upstream separately from your custom ChatGPT-authenticated GPT-5.x work.

Current local setup
- Feature branch for the customization: `feat/chatgpt-pro-integration`
- Upstream remote: `upstream -> https://github.com/K-Dense-AI/k-dense-byok.git`
- Fork remote: `origin -> https://github.com/Grrrregory/k-dense-byok.git`
- Helpful git settings enabled locally:
  - `rerere.enabled = true`
  - `pull.rebase = true`

## 1. Keep ChatGPT auth outside the repo

The integration supports an external auth store via `KADY_CHATGPT_AUTH_PATH`.
Using that path keeps your ChatGPT login state stable across rebases, resets, fresh clones, and branch switches.

Recommended value:

```bash
export KADY_CHATGPT_AUTH_PATH="$HOME/.kady/chatgpt/auth.json"
```

If you want this loaded automatically by `start.sh`, add it to `kady_agent/.env`:

```bash
KADY_CHATGPT_AUTH_PATH="$HOME/.kady/chatgpt/auth.json"
```

Why this matters:
- the default fallback is repo-local
- repo-local auth is easier to lose during cleanup/reclone operations
- an external path preserves the ChatGPT auth functionality while the codebase evolves

## 2. Branching model

Use this structure:
- `main`: clean mirror of upstream `main`
- `feat/chatgpt-pro-integration`: your maintained customization branch

Do not do active feature work directly on `main`.

## 3. First cleanup step for the current working tree

The current ChatGPT integration work is still uncommitted. Before the next upstream sync, commit it as a small patch stack.

Recommended commit split:

1. `chatgpt-auth-core`
   - `kady_agent/chatgpt_auth.py`
   - `kady_agent/chatgpt_models.py`
   - related backend tests

2. `chatgpt-backend-routing`
   - `server.py`
   - `kady_agent/agent.py`
   - `litellm_config.yaml`
   - `start.sh`
   - related tests

3. `chatgpt-expert-codex-runner`
   - `kady_agent/tools/codex_cli.py`
   - `kady_agent/tools/gemini_cli.py`
   - `kady_agent/instructions/codex_cli.md`
   - related tests

4. `chatgpt-ui-and-docs`
   - `web/src/components/settings-dialog.tsx`
   - `web/src/lib/use-models.ts`
   - `web/src/lib/use-settings.ts`
   - docs/readme/frontend tests

Keeping the work in a patch stack makes future rebases much easier.

## 4. Standard upstream update workflow

### Sync local `main` to upstream

```bash
git fetch upstream --prune
git switch main
git reset --hard upstream/main
```

### Update fork `main`

```bash
git push --force-with-lease origin main
```

### Rebase the ChatGPT integration branch

```bash
git switch feat/chatgpt-pro-integration
git rebase upstream/main
```

If there are conflicts:
1. resolve them file-by-file
2. run the regression checks below
3. continue the rebase

```bash
git add <resolved-files>
git rebase --continue
```

If needed:

```bash
git rebase --abort
```

## 5. Regression checks after every rebase

Backend ChatGPT-specific regression suite:

```bash
uv run pytest -q \
  tests/test_chatgpt_auth.py \
  tests/test_chatgpt_models.py \
  tests/test_agent_chatgpt_provider.py \
  tests/test_codex_cli_tool.py \
  tests/test_server_chatgpt_auth.py \
  tests/test_litellm_config_chatgpt.py
```

Full backend suite:

```bash
uv run pytest
```

Frontend checks:

```bash
cd web
npm test
npm run build
```

## 6. Files most likely to conflict on future rebases

These are the main integration seam files and should be reviewed carefully whenever upstream changes them:
- `server.py`
- `kady_agent/agent.py`
- `kady_agent/tools/gemini_cli.py`
- `litellm_config.yaml`
- `web/src/components/settings-dialog.tsx`
- `web/src/lib/use-models.ts`
- `web/src/lib/use-settings.ts`

The custom logic is intentionally more isolated in these files, which should reduce merge pain:
- `kady_agent/chatgpt_auth.py`
- `kady_agent/chatgpt_models.py`
- `kady_agent/tools/codex_cli.py`
- `kady_agent/instructions/codex_cli.md`

## 7. Recommended push workflow

After your integration branch is green:

```bash
git push --force-with-lease origin feat/chatgpt-pro-integration
```

If you want a reviewable PR against your fork’s `main`:

```bash
gh pr create --base main --head feat/chatgpt-pro-integration --fill
```

## 8. Safety rules

- Never rebase with important uncommitted work unless it is stashed or committed.
- Keep ChatGPT auth state out of git and preferably out of the repo directory.
- Re-run the ChatGPT regression suite after any upstream rebase touching routing, settings, auth, or expert execution.
- If upstream introduces cleaner extension hooks, prefer moving custom glue into those hooks rather than growing diffs inside hot-path files.

## 9. Current known-good verification

The targeted ChatGPT integration regression suite passed locally with:

```bash
uv run pytest -q \
  tests/test_chatgpt_auth.py \
  tests/test_chatgpt_models.py \
  tests/test_agent_chatgpt_provider.py \
  tests/test_codex_cli_tool.py \
  tests/test_server_chatgpt_auth.py \
  tests/test_litellm_config_chatgpt.py
```

That verifies the core auth/model discovery/provider routing/Codex expert path after the branch and fork setup above.
