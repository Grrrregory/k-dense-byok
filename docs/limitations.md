# Known Limitations

K-Dense BYOK is in beta. The most important rough edges today are still on the expert-delegation path, which now uses a provider-specific expert runner: Gemini CLI for Gemini/OpenRouter/Ollama expert models, and Codex CLI for ChatGPT Pro-authenticated expert models.

## Expert delegation runners

Delegated tasks no longer go through a single runtime. Instead:

- `openrouter/...`, `ollama/...`, and Gemini-native expert models run through the Gemini CLI expert runner.
- `chatgpt/...` expert models run through a Codex CLI expert runner with isolated ChatGPT Pro auth.

The orchestrator is separate from both of these runners, so expert-side rough edges do not necessarily imply a bug in K-Dense BYOK's main agent loop.

## Gemini-based expert limitations

The Gemini-based expert runner still handles OpenRouter, Ollama, and Gemini-native expert models. While this works well for many workflows, there are some rough edges to be aware of:

- **Skill activation is not always reliable.** The expert model can sometimes skip a relevant skill, use it partially, or misinterpret the skill's instructions. This is especially noticeable with complex multi-step skills that require strict adherence to a procedure.
- **Tool-calling consistency varies.** The Gemini CLI can occasionally drop tool calls mid-execution or call tools with incorrect arguments, which can cause expert tasks to stall or produce incomplete results.
- **Long-context degradation.** When a skill injects a large amount of context (detailed protocols, multiple reference databases), the expert can lose track of earlier instructions or produce less focused output.
- **Structured output can drift.** For skills that require specific output formats (tables, JSON, citations), the expert can sometimes deviate from the requested structure.

These are primarily limitations of the current Gemini-based expert runner and the underlying model/tooling combinations, not bugs in K-Dense BYOK's orchestrator itself.

## Codex / ChatGPT Pro expert limitations

The Codex-based ChatGPT Pro expert path is newer. It is fully routed and authenticated, but it differs from the Gemini path in a few ways:

- Cost accounting is currently recorded as included / zero-cost rather than usage-priced.
- The runtime reads K-Dense skills from `.gemini/skills/` and uses the configured MCP servers, but behavior can still differ from the Gemini expert runner on the same task.
- If a delegated task depends heavily on a specific tool or skill choreography, it is still worth retrying or comparing against an OpenRouter expert model.

**Workarounds:**

- If a delegated task behaves oddly, retry once before changing the workflow.
- You can switch Kady's main model independently from the expert model.
- If one provider/model pair struggles on a delegated task, try another expert model before assuming the workflow is broken.

## Ollama / small local models

Local models served through Ollama are supported end-to-end, but they amplify the Gemini-based expert-runner caveats above:

- Tool-calling fidelity is noticeably weaker on sub-frontier models.
- Skills that rely on multi-tool choreography (browsing, running scripts, structured output) are the most fragile.

If a delegation loops or ignores its skill, try a larger local model (or temporarily switch back to an OpenRouter-hosted or ChatGPT-authenticated model) before assuming the workflow is broken. See [Local models with Ollama](./local-models-ollama.md).
