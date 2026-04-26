import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch, onProjectChange } = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  onProjectChange: vi.fn(() => () => {}),
}));

vi.mock("@/lib/projects", () => ({
  apiFetch,
  onProjectChange,
}));

import { useModels } from "./use-models";

const OLLAMA_MODEL = {
  id: "ollama/qwen3",
  label: "qwen3",
  provider: "Ollama",
  tier: "budget",
  context_length: 0,
  pricing: { prompt: 0, completion: 0 },
  modality: "text->text",
  description: "local",
} as const;

const CHATGPT_MODEL = {
  id: "chatgpt/gpt-5.4",
  label: "GPT-5.4",
  provider: "ChatGPT Pro",
  tier: "high",
  context_length: 0,
  pricing: { prompt: 0, completion: 0 },
  modality: "text+image->text",
  description: "chatgpt",
} as const;

describe("useModels", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    onProjectChange.mockClear();
  });

  it("merges static models with chatgpt and ollama models", async () => {
    apiFetch.mockImplementation((path: string) => {
      if (path === "/ollama/models") {
        return Promise.resolve(
          new Response(JSON.stringify({ available: true, models: [OLLAMA_MODEL] }), { status: 200 }),
        );
      }
      if (path === "/chatgpt/models") {
        return Promise.resolve(
          new Response(JSON.stringify({ available: true, models: [CHATGPT_MODEL] }), { status: 200 }),
        );
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    const { result } = renderHook(() => useModels());

    await waitFor(() => {
      expect(result.current.ollamaModels).toHaveLength(1);
      expect(result.current.chatgptModels).toHaveLength(1);
    });

    expect(result.current.ollamaAvailable).toBe(true);
    expect(result.current.chatgptAvailable).toBe(true);
    expect(result.current.models.some((m) => m.id === CHATGPT_MODEL.id)).toBe(true);
    expect(result.current.models.some((m) => m.id === OLLAMA_MODEL.id)).toBe(true);
  });

  it("silently omits chatgpt models when unavailable", async () => {
    apiFetch.mockImplementation((path: string) => {
      if (path === "/ollama/models") {
        return Promise.resolve(
          new Response(JSON.stringify({ available: false, models: [] }), { status: 200 }),
        );
      }
      if (path === "/chatgpt/models") {
        return Promise.resolve(
          new Response(JSON.stringify({ available: false, models: [] }), { status: 200 }),
        );
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    const { result } = renderHook(() => useModels());

    await waitFor(() => {
      expect(result.current.ollamaAvailable).toBe(false);
      expect(result.current.chatgptAvailable).toBe(false);
    });

    expect(result.current.chatgptModels).toEqual([]);
    expect(result.current.models.some((m) => m.id.startsWith("chatgpt/"))).toBe(false);
  });

  it("keeps refresh stable across rerenders", async () => {
    apiFetch.mockImplementation((path: string) => {
      if (path === "/ollama/models") {
        return Promise.resolve(
          new Response(JSON.stringify({ available: false, models: [] }), { status: 200 }),
        );
      }
      if (path === "/chatgpt/models") {
        return Promise.resolve(
          new Response(JSON.stringify({ available: false, models: [] }), { status: 200 }),
        );
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    const { result } = renderHook(() => useModels());
    const firstRefresh = result.current.refresh;

    await waitFor(() => expect(result.current.chatgptAvailable).toBe(false));

    expect(result.current.refresh).toBe(firstRefresh);
  });

  it("refreshes chatgpt models when a models-changed event fires", async () => {
    let chatgptAvailable = false;
    apiFetch.mockImplementation((path: string) => {
      if (path === "/ollama/models") {
        return Promise.resolve(
          new Response(JSON.stringify({ available: false, models: [] }), { status: 200 }),
        );
      }
      if (path === "/chatgpt/models") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              available: chatgptAvailable,
              models: chatgptAvailable ? [CHATGPT_MODEL] : [],
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    const { result } = renderHook(() => useModels());

    await waitFor(() => expect(result.current.chatgptAvailable).toBe(false));
    chatgptAvailable = true;
    window.dispatchEvent(new Event("kady:modelsChanged"));

    await waitFor(() => expect(result.current.chatgptAvailable).toBe(true));
    expect(result.current.models.some((m) => m.id === CHATGPT_MODEL.id)).toBe(true);
  });
});
